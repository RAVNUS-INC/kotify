#!/usr/bin/env bash
# deploy/kotify-update-worker.sh
#
# kotify-update.sh (trampoline) 가 git pull 직후 exec 으로 넘겨주는 실제
# 업데이트 로직. 분리 이유는 trampoline 의 주석 참조.
#
# trampoline 이 이미 한 일:
#   - flock (fd 200) — 동시 실행 차단
#   - stdout/stderr → /var/log/kotify/update.log
#   - git pull (fetch + reset --hard origin/main)
#
# worker 가 하는 일:
#   - pip install
#   - SQLite .backup (pre-migrate)
#   - alembic upgrade (kotify 사용자로)  → 실패 시 ERR trap 이 백업 복원 + git rollback
#   - pnpm install + build
#   - .next/static / public merge-copy (race 회피)
#   - chown — 서비스 사용자가 읽을 수 있게
#   - systemctl restart (2초 딜레이 비동기)

set -euo pipefail

# ── Env 명시 (sudo invoke 경로 독립화) ──────────────────────────────────────
# 이 스크립트는 두 가지 경로로 실행된다:
#   A) 터미널 수동: 관리자가 `sudo /opt/kotify/deploy/kotify-update.sh apply`
#   B) 웹 UI 버튼 : kotify 서비스(systemd)가 subprocess 로 `sudo ...` 호출
#
# sudo 는 env_reset 기본 + /etc/sudoers 의 secure_path 로 PATH 만 세팅하는데,
# HOME 처리가 배포판마다 다르다 (always_set_home on/off). kotify 사용자는
# nologin + HOME=/var/lib/kotify 라 경로 B 에서 HOME 이 거기로 유지되면
# pnpm store/cache 가 /var/lib/kotify 하위로 튀어 권한/상태 꼬임 → rc=254
# (pnpm internal failure) 가 재현된다.
#
# 해결: invoke 경로와 무관하게 worker 내부에서 PATH/HOME 을 **항상** 동일
# 하게 고정. /usr/local/bin 은 ct-bootstrap 의 `npm install -g pnpm` 설치
# 위치. HOME=/root 로 두면 pnpm store 는 /root/.local/share/pnpm, cache 는
# /root/.cache/pnpm — root 소유라 권한 충돌 없음.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export HOME="/root"

# pnpm 은 store/cache 를 `$HOME/.local/share/pnpm`, `$HOME/.cache/pnpm` 에
# 만드는데 내부적으로 `fs.mkdir` 호출 시 `{recursive: true}` 를 주지 않아
# 부모 디렉토리 (`.local`, `.cache`) 가 없으면 `ENOENT` 로 rc=254 실패.
# 일부 최소 컨테이너 이미지는 root 홈에 이 경로가 없으니 pre-create.
mkdir -p "${HOME}/.local/share" "${HOME}/.cache"

INSTALL_DIR="/opt/kotify"
WEB_DIR="${INSTALL_DIR}/web"
VENV="${INSTALL_DIR}/.venv"
DB_PATH="/var/lib/kotify/sms.db"
DB_BACKUP="/var/lib/kotify/pre-migrate.db"
SERVICE_API="kotify"
SERVICE_WEB="kotify-web"
SERVICE_USER="kotify"
SERVICE_GROUP="kotify"
BRANCH="main"

cd "${INSTALL_DIR}"

# trampoline 이 git reset --hard 했으므로 여기 HEAD 는 이미 remote 와 일치.
# 하지만 rollback 지점으로 이전 HEAD 가 필요 — git reflog 로 바로 직전 HEAD 회수.
# reflog 첫 엔트리는 HEAD{0} = current. 그 이전은 HEAD@{1}.
PREV_HEAD=$(git rev-parse "HEAD@{1}" 2>/dev/null || git rev-parse HEAD)

cleanup_on_error() {
    local rc=$?
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] worker ERR rc=${rc} — rollback" >&2
    echo "{\"phase\": \"error\", \"rollback\": true, \"to\": \"${PREV_HEAD:0:7}\"}"
    # 1. git 코드 rollback.
    git -C "${INSTALL_DIR}" reset --hard "${PREV_HEAD}" >/dev/null 2>&1 || true
    # 2. DB 롤백 — 사전 백업이 있으면 복원.
    if [[ -f "${DB_BACKUP}" ]]; then
        cp -f "${DB_BACKUP}" "${DB_PATH}" 2>/dev/null || true
        # WAL / SHM 정리 — 복원 후 남은 journal 이 DB 와 불일치할 수 있음.
        rm -f "${DB_PATH}-wal" "${DB_PATH}-shm" 2>/dev/null || true
        chown "${SERVICE_USER}:${SERVICE_GROUP}" "${DB_PATH}" 2>/dev/null || true
    fi
    # 3. .next/standalone 정리 — 버전 불일치 하이브리드 상태 방지.
    #    rollback 후엔 standalone 이 미완 빌드일 수 있어 제거. 서비스 재시작
    #    시 ExecStartPre 나 다음 update 에서 새로 빌드하도록 강제.
    rm -rf "${WEB_DIR}/.next/standalone" 2>/dev/null || true
    exit "${rc}"
}
trap cleanup_on_error ERR

# Phase 2a: Python 의존성 설치.
echo '{"phase": "install_backend"}'
"${VENV}/bin/pip" install -e "${INSTALL_DIR}" --quiet

# Phase 2b: DB 스냅샷 — 마이그레이션 실패 시 복원용.
# sqlite3 .backup 은 WAL-safe 하이 live DB 에 대해 안전한 snapshot.
# 실행 전 옛 백업 제거 (크기 누적 방지).
rm -f "${DB_BACKUP}"
if [[ -f "${DB_PATH}" ]]; then
    sqlite3 "${DB_PATH}" ".backup '${DB_BACKUP}'"
fi

# Phase 2c: alembic 을 **서비스 사용자** 로 실행 — 파일 소유권 일관.
# root 로 돌면 WAL/SHM 파일이 root 소유가 되어 다음 서비스 기동에서 EACCES.
echo '{"phase": "migrate"}'
if ! runuser -u "${SERVICE_USER}" -- \
        "${VENV}/bin/alembic" -c "${INSTALL_DIR}/alembic.ini" upgrade head 2>&1; then
    echo '{"phase": "error", "step": "migrate", "message": "alembic upgrade failed"}'
    exit 1
fi

# Phase 3a: Next.js 의존성 (변경 없으면 fast no-op).
# --silent 제거 — 이전에 rc=254 나는데 원인이 로그에 안 남아 디버깅 불가
# 했던 이슈. 에러 세부는 /var/log/kotify/update.log 로 전부 tee.
echo '{"phase": "install_web"}'
cd "${WEB_DIR}"
pnpm install --frozen-lockfile 2>&1

# Phase 3b: Next.js 빌드.
# >/dev/null 도 제거 — 빌드 출력(chunk 크기, 에러) 은 log 에 남겨야 post-mortem
# 가능. stderr 는 set -e 가 비정상 종료 트리거 하므로 exit code 로 실패 감지.
echo '{"phase": "build_web"}'
FASTAPI_URL=http://127.0.0.1:8080 pnpm build 2>&1

# Phase 3c: standalone 에 static/public **merge** (race-safe).
# 삭제하지 않는다 — 옛 hash 가 재시작 전까지 디스크에 살아있어 구 process 가
# 404 없이 서빙 가능. 새 hash 는 추가만 됨. 옛 hash 누적은 다음 ct-bootstrap
# 로 정리.
mkdir -p "${WEB_DIR}/.next/standalone/.next/static"
cp -R "${WEB_DIR}/.next/static/." "${WEB_DIR}/.next/standalone/.next/static/"
if [[ -d "${WEB_DIR}/public" ]]; then
    mkdir -p "${WEB_DIR}/.next/standalone/public"
    cp -R "${WEB_DIR}/public/." "${WEB_DIR}/.next/standalone/public/"
fi

# Phase 3d: 소유권 정상화 — root 로 쓴 새 파일을 kotify 로.
#   git pull / pnpm install / pnpm build / cp -R 모두 root 로 실행했으므로
#   새 파일들은 root 소유. 서비스 재시작 시 kotify 사용자가 읽을 수 있도록
#   recursive chown.
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" \
    "${WEB_DIR}/.next" \
    "${WEB_DIR}/node_modules" 2>/dev/null || true

# 빌드 완료 — 이후 실패는 롤백 불가 (코드는 이미 바뀌었고 서비스 재시작만 남음).
trap - ERR

NEW_HASH=$(git -C "${INSTALL_DIR}" rev-parse --short HEAD)

# Phase 4: 재시작 (2초 지연, 비동기).
# unit 이름 은 PID 뿐 아니라 timestamp 까지 포함해 동시 실행 충돌 방지.
# (flock 이 선제 차단하지만 이중 방어.)
echo '{"phase": "restart_scheduled"}'
UNIT_NAME="kotify-restart-$(date +%s)-$$"
if command -v systemd-run >/dev/null 2>&1; then
    systemd-run --on-active=2s --unit="${UNIT_NAME}" \
        /bin/systemctl restart "${SERVICE_API}" "${SERVICE_WEB}" >/dev/null 2>&1 || \
        (nohup bash -c "sleep 2 && systemctl restart ${SERVICE_API} ${SERVICE_WEB}" >/dev/null 2>&1 &)
else
    nohup bash -c "sleep 2 && systemctl restart ${SERVICE_API} ${SERVICE_WEB}" >/dev/null 2>&1 &
fi
disown 2>/dev/null || true

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] worker done, version=${NEW_HASH}" >&2
echo '{"phase": "done", "version": "'"${NEW_HASH}"'"}'
