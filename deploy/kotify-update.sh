#!/usr/bin/env bash
# deploy/kotify-update.sh
# kotify 원클릭 업데이트 스크립트.
# 웹 UI에서 sudo로 호출됨 (kotify-sudoers 참조).
#
# 사용법:
#   sudo /opt/kotify/deploy/kotify-update.sh check   # 업데이트 확인 (JSON 출력)
#   sudo /opt/kotify/deploy/kotify-update.sh apply    # 업데이트 적용 + 재시작

set -euo pipefail

INSTALL_DIR="/opt/kotify"
VENV="${INSTALL_DIR}/.venv"
SERVICE="kotify"
BRANCH="main"

cd "${INSTALL_DIR}"

case "${1:-}" in
    check)
        # 원격 fetch
        git fetch origin "${BRANCH}" --quiet 2>/dev/null

        LOCAL=$(git rev-parse HEAD)
        REMOTE=$(git rev-parse "origin/${BRANCH}")

        if [[ "${LOCAL}" == "${REMOTE}" ]]; then
            echo '{"update_available": false, "current": "'"${LOCAL:0:7}"'", "commits": []}'
            exit 0
        fi

        # 새 커밋 목록 (최대 20개)
        COMMITS=$(git log --oneline HEAD.."origin/${BRANCH}" --max-count=20 \
            | sed 's/"/\\"/g' \
            | awk '{printf "%s{\"hash\": \"%s\", \"message\": \"%s\"}", (NR>1?",":""), substr($1,1,7), substr($0, index($0,$2))}')

        COUNT=$(git rev-list --count HEAD.."origin/${BRANCH}")

        echo '{"update_available": true, "current": "'"${LOCAL:0:7}"'", "remote": "'"${REMOTE:0:7}"'", "count": '"${COUNT}"', "commits": ['"${COMMITS}"']}'
        ;;

    apply)
        echo '{"phase": "pull"}'
        git pull --ff-only origin "${BRANCH}" --quiet

        echo '{"phase": "install"}'
        "${VENV}/bin/pip" install -e "${INSTALL_DIR}" --quiet 2>/dev/null

        NEW_HASH=$(git rev-parse --short HEAD)

        # 재시작은 2초 뒤 비동기로. HTTP 응답이 클라이언트에 먼저 도달하도록
        # 하여 '업데이트 실패:' 오해를 방지하고, 클라이언트가 /healthz의 버전
        # 필드로 재시작 완료를 정확히 감지할 수 있게 한다.
        # systemd-run은 현재 프로세스의 cgroup에서 분리된 transient unit을
        # 생성하므로 systemctl restart가 자신을 죽이는 문제가 없다.
        echo '{"phase": "restart_scheduled"}'
        if command -v systemd-run >/dev/null 2>&1; then
            systemd-run --on-active=2s --unit="kotify-restart-$$" \
                /bin/systemctl restart "${SERVICE}" >/dev/null 2>&1 || \
                (nohup bash -c "sleep 2 && systemctl restart ${SERVICE}" >/dev/null 2>&1 &)
        else
            nohup bash -c "sleep 2 && systemctl restart ${SERVICE}" >/dev/null 2>&1 &
        fi
        disown 2>/dev/null || true

        echo '{"phase": "done", "version": "'"${NEW_HASH}"'"}'
        ;;

    *)
        echo "Usage: $0 {check|apply}" >&2
        exit 1
        ;;
esac
