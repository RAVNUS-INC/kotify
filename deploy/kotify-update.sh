#!/usr/bin/env bash
# deploy/kotify-update.sh — trampoline
#
# 웹 UI 의 "업데이트 설치" 버튼이 sudo 로 이 스크립트를 호출한다. 역할은
# 최소한:
#   1) flock 으로 동시 실행 차단
#   2) persistent log 로 출력 tee
#   3) git pull 로 최신 코드 확보
#   4) 새로 풀한 kotify-update-worker.sh 를 exec 으로 넘겨 실제 작업 수행
#
# 왜 분리했나 — bash 는 실행 중 열린 스크립트 파일의 fd 를 유지한다.
# git pull 이 파일을 unlink+rename 으로 교체해도 현재 bash 프로세스는 옛
# inode 를 계속 읽기 때문에, 스크립트 변경사항은 **다음 실행** 에야 반영된다.
# trampoline 은 git pull 직후 `exec worker` 로 새 프로세스를 띄워 새 worker
# 코드가 즉시 적용되게 한다. 이후 worker 변경은 첫 배포에 바로 효력 발생.
#
# 사용법:
#   sudo /opt/kotify/deploy/kotify-update.sh check
#   sudo /opt/kotify/deploy/kotify-update.sh apply

set -euo pipefail

INSTALL_DIR="/opt/kotify"
LOCK_FILE="/var/run/kotify-update.lock"
LOG_DIR="/var/log/kotify"
LOG_FILE="${LOG_DIR}/update.log"
WORKER="${INSTALL_DIR}/deploy/kotify-update-worker.sh"
BRANCH="main"

ACTION="${1:-}"
if [[ "${ACTION}" != "check" && "${ACTION}" != "apply" ]]; then
    echo '{"phase":"error","message":"허용되지 않은 action (check|apply 만 가능)"}' >&2
    exit 2
fi

# check 모드는 부작용이 없어 동시 실행 허용 + 로그도 간소.
if [[ "${ACTION}" == "check" ]]; then
    cd "${INSTALL_DIR}"
    git fetch origin "${BRANCH}" --quiet 2>/dev/null || true
    LOCAL=$(git rev-parse HEAD)
    REMOTE=$(git rev-parse "origin/${BRANCH}" 2>/dev/null || echo "${LOCAL}")
    if [[ "${LOCAL}" == "${REMOTE}" ]]; then
        echo '{"update_available": false, "current": "'"${LOCAL:0:7}"'", "commits": []}'
        exit 0
    fi
    COMMITS=$(git log --oneline HEAD.."origin/${BRANCH}" --max-count=20 \
        | sed 's/"/\\"/g' \
        | awk '{printf "%s{\"hash\": \"%s\", \"message\": \"%s\"}", (NR>1?",":""), substr($1,1,7), substr($0, index($0,$2))}')
    COUNT=$(git rev-list --count HEAD.."origin/${BRANCH}")
    echo '{"update_available": true, "current": "'"${LOCAL:0:7}"'", "remote": "'"${REMOTE:0:7}"'", "count": '"${COUNT}"', "commits": ['"${COMMITS}"']}'
    exit 0
fi

# apply 모드 — lock + log + git pull + exec worker.
mkdir -p "${LOG_DIR}"
chmod 755 "${LOG_DIR}" 2>/dev/null || true

# flock 비동시 실행 — 둘째 admin 이 눌러도 즉시 409.
exec 200>"${LOCK_FILE}"
if ! flock -n 200; then
    echo '{"phase":"error","code":"in_progress","message":"업데이트가 이미 진행 중입니다"}' >&2
    exit 9
fi

# 모든 stdout/stderr 을 log 에 동시 기록 (persistent post-mortem).
# stdout 은 tee -a 로 log + 원래 stdout (Python subprocess 가 parse 함).
# stderr 는 log 에만 append.
exec > >(tee -a "${LOG_FILE}") 2> >(tee -a "${LOG_FILE}" >&2)

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] === kotify-update apply start ===" >&2

cd "${INSTALL_DIR}"

# Phase 1 (trampoline): git pull.
# `--ff-only` 는 force-push (history 재작성) 시 실패하므로 fetch + reset 으로
# 대체해 prod CT 에 로컬 변경 없다는 전제 하에 항상 원격과 일치시킨다.
git fetch origin "${BRANCH}" --quiet
echo '{"phase": "pull"}'
git reset --hard "origin/${BRANCH}" --quiet

# Worker 존재 확인 — 최초 배포 시 없을 수 있음.
if [[ ! -x "${WORKER}" ]]; then
    # 실행 권한 부여 후 재확인.
    chmod +x "${WORKER}" 2>/dev/null || true
    if [[ ! -f "${WORKER}" ]]; then
        echo '{"phase":"error","code":"worker_missing","message":"kotify-update-worker.sh 가 리포에 없습니다"}' >&2
        exit 3
    fi
fi

# Phase 이후는 WORKER 에 위임 — exec 으로 새 프로세스 교체. git pull 로
# 새로 쓰여진 파일 내용이 exec 의 새 프로세스에 적용됨.
# lock fd 200 은 exec 해도 유지되어 WORKER 내부에서도 mutex 보장.
exec bash "${WORKER}"
