#!/usr/bin/env bash
# deploy/kotify-post-restart.sh
#
# kotify-update-worker.sh 가 빌드를 마친 뒤 systemd-run 으로 2초 뒤 실행한다.
# worker 는 웹 UI 요청을 처리 중인 kotify 서비스에서 뻗어 나왔기 때문에 서비스를
# 직접 재시작하면 자기 자신이 죽는다. 그래서 재시작과 그 뒤 확인은 systemd 가
# 띄우는 별도 unit 에서 한다.
#
# 하는 일:
#   1) kotify / kotify-web 재시작
#   2) 기동 확인 — API /healthz 가 status=ok 이고 새 커밋 버전을 내는지, 웹이
#      /api/healthz 를 프록시하는지. 제한 시간 안에 안 되면
#   3) 롤백 — 서비스 정지 → git 을 이전 커밋으로 → (이번 배포에서 마이그레이션이
#      바뀌었으면) DB 를 pre-migrate 백업으로 복원 → 의존성·웹 재빌드 → 재시작 → 재확인
#
# 사용법 (worker 가 호출): kotify-post-restart.sh <이전 커밋> <새 커밋>
# 결과는 /var/log/kotify/update.log 에 남는다. 실패하면 exit 1 (unit 도 failed).
#
# KOTIFY_* 환경변수는 테스트(tests/test_post_restart_script.py)에서 경로와 명령을
# 바꾸기 위한 것. systemd-run 은 깨끗한 환경으로 실행하므로 운영에선 기본값만 쓴다.

set -Eeuo pipefail

INSTALL_DIR="${KOTIFY_INSTALL_DIR:-/opt/kotify}"
WEB_DIR="${INSTALL_DIR}/web"
VENV="${KOTIFY_VENV:-${INSTALL_DIR}/.venv}"
DB_PATH="${KOTIFY_DB_PATH:-/var/lib/kotify/sms.db}"
DB_BACKUP="${KOTIFY_DB_BACKUP:-/var/lib/kotify/pre-migrate.db}"
LOG_FILE="${KOTIFY_UPDATE_LOG:-/var/log/kotify/update.log}"
LOCK_FILE="${KOTIFY_UPDATE_LOCK:-/var/run/kotify-update.lock}"
API_HEALTH_URL="${KOTIFY_API_HEALTH_URL:-http://127.0.0.1:8080/healthz}"
WEB_HEALTH_URL="${KOTIFY_WEB_HEALTH_URL:-http://127.0.0.1:3000/api/healthz}"
HEALTH_TIMEOUT_SEC="${KOTIFY_HEALTH_TIMEOUT_SEC:-120}"
HEALTH_INTERVAL_SEC="${KOTIFY_HEALTH_INTERVAL_SEC:-2}"
SYSTEMCTL="${KOTIFY_SYSTEMCTL:-systemctl}"
FLOCK="${KOTIFY_FLOCK:-flock}"
SERVICE_API="kotify"
SERVICE_WEB="kotify-web"
SERVICE_USER="kotify"
SERVICE_GROUP="kotify"

# pnpm store 를 worker 와 같은 위치로 — 롤백 재빌드 때 패키지를 다시 받지 않게.
# PATH 는 systemd 기본값(/usr/local/bin, /usr/bin 포함)을 그대로 쓴다.
export HOME="${KOTIFY_WORKER_HOME:-${INSTALL_DIR}/.worker-home}"

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] post-restart: $*"
}

# 1회 확인. API 가 status=ok·기대 버전이고 웹 프록시가 200 이면 0.
healthy_once() {
    python3 - "${API_HEALTH_URL}" "${WEB_HEALTH_URL}" "$1" <<'PY'
import json
import sys
import urllib.request

api_url, web_url, expected = sys.argv[1:4]


def same_commit(version):
    # 서비스 사용자로 git 해시를 못 읽는 환경이면 unknown — 버전 비교 생략.
    # 짧은 해시 길이가 root 와 다를 수 있어 접두어가 같으면 같은 커밋으로 본다.
    if version == "unknown":
        return True
    return len(version) >= 7 and (version.startswith(expected) or expected.startswith(version))


try:
    with urllib.request.urlopen(api_url, timeout=3) as res:
        data = json.loads(res.read())
    if data.get("status") != "ok" or not same_commit(str(data.get("version", ""))):
        sys.exit(1)
    with urllib.request.urlopen(web_url, timeout=3) as res:
        sys.exit(0 if res.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
}

# 최소 1회는 확인하고, 제한 시간까지 간격을 두고 재시도.
wait_healthy() {
    local deadline=$((SECONDS + HEALTH_TIMEOUT_SEC))
    until healthy_once "$1"; do
        if ((SECONDS >= deadline)); then
            return 1
        fi
        sleep "${HEALTH_INTERVAL_SEC}"
    done
}

migrations_changed() {
    ! git -C "${INSTALL_DIR}" diff --quiet "$1" "$2" -- alembic/versions
}

# worker 의 cleanup_on_error 와 같은 방식.
restore_db() {
    cp -f "${DB_BACKUP}" "${DB_PATH}"
    rm -f "${DB_PATH}-wal" "${DB_PATH}-shm"
    chown "${SERVICE_USER}:${SERVICE_GROUP}" "${DB_PATH}" 2>/dev/null || true
}

# worker 의 Phase 2a·3a~3d 와 같은 순서 (마이그레이션은 제외 — DB 는 restore_db 담당).
rebuild() {
    "${VENV}/bin/pip" install -e "${INSTALL_DIR}" --quiet
    (cd "${WEB_DIR}" && pnpm install --frozen-lockfile && FASTAPI_URL=http://127.0.0.1:8080 pnpm build)
    mkdir -p "${WEB_DIR}/.next/standalone/.next/static"
    cp -R "${WEB_DIR}/.next/static/." "${WEB_DIR}/.next/standalone/.next/static/"
    if [[ -d "${WEB_DIR}/public" ]]; then
        mkdir -p "${WEB_DIR}/.next/standalone/public"
        cp -R "${WEB_DIR}/public/." "${WEB_DIR}/.next/standalone/public/"
    fi
    chown -R "${SERVICE_USER}:${SERVICE_GROUP}" \
        "${WEB_DIR}/.next" \
        "${WEB_DIR}/node_modules" 2>/dev/null || true
}

main() {
    local prev="$1" new="$2"

    mkdir -p "$(dirname "${LOG_FILE}")"
    exec >>"${LOG_FILE}" 2>&1
    trap 'rc=$?; log "스크립트 오류 (line ${LINENO}, rc=${rc}) — 수동 확인 필요"' ERR

    # 확인·롤백 중에 다른 업데이트가 끼어들지 않게 worker 와 같은 lock 을 잡는다.
    exec 200>"${LOCK_FILE}"
    "${FLOCK}" -w 300 200

    local prev_short new_short
    prev_short=$(git -C "${INSTALL_DIR}" rev-parse --short "${prev}")
    new_short=$(git -C "${INSTALL_DIR}" rev-parse --short "${new}")

    log "재시작 — ${new_short} 기동 확인 (최대 ${HEALTH_TIMEOUT_SEC}s)"
    "${SYSTEMCTL}" restart "${SERVICE_API}" "${SERVICE_WEB}"
    if wait_healthy "${new_short}"; then
        log "정상 기동 — ${new_short}"
        exit 0
    fi

    log "기동 확인 실패 — ${new_short}"
    "${SYSTEMCTL}" status --no-pager --lines=30 "${SERVICE_API}" "${SERVICE_WEB}" || true

    if [[ "${prev_short}" == "${new_short}" ]]; then
        log "되돌릴 이전 커밋이 없음 — 수동 확인 필요"
        exit 1
    fi

    log "롤백 시작 — ${new_short} → ${prev_short}"
    "${SYSTEMCTL}" stop "${SERVICE_API}" "${SERVICE_WEB}"
    local restore=false
    if migrations_changed "${prev}" "${new}"; then
        restore=true
    fi
    git -C "${INSTALL_DIR}" reset --hard "${prev}" --quiet
    if [[ "${restore}" == true && -f "${DB_BACKUP}" ]]; then
        log "이번 배포에 마이그레이션 변경이 있어 DB 를 pre-migrate 백업으로 복원"
        restore_db
    fi
    rebuild
    "${SYSTEMCTL}" restart "${SERVICE_API}" "${SERVICE_WEB}"
    if wait_healthy "${prev_short}"; then
        log "롤백 완료 — ${prev_short} 정상 기동"
    else
        log "롤백 후에도 기동 확인 실패 — 수동 확인 필요"
    fi
    exit 1
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
