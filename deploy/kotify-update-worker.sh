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

# ── Env 명시 (sudo invoke 경로 독립화 + systemd hardening 우회) ────────────
# 이 스크립트는 두 가지 경로로 실행된다:
#   A) 터미널 수동: 관리자가 `sudo /opt/kotify/deploy/kotify-update.sh apply`
#   B) 웹 UI 버튼 : kotify 서비스(systemd)가 subprocess 로 `sudo ...` 호출
#
# 두 경로에서 환경이 달라 pnpm/alembic 이 다른 지점에서 실패하는 증상이
# 반복됐다. 핵심은 **HOME**:
#   - sudo 는 `always_set_home` on/off 에 따라 HOME 을 (invoking user) 로
#     유지하거나 (target root) 로 덮어씀 — 배포판별로 다름.
#   - 경로 B 는 systemd 의 `ProtectHome=true` + `ProtectSystem=strict` 라
#     `/root`, `/home` 등 대부분의 시스템 경로가 ReadOnly. pnpm 이 store
#     를 만들려다 EROFS 로 죽는다.
#   - ReadWritePaths 에 있는 경로(`/opt/kotify`, `/var/lib/kotify`,
#     `/var/log/kotify`) 만 쓰기 가능.
#
# 해결: HOME 을 `/opt/kotify/.worker-home` 으로 고정. pnpm 은
# `$HOME/.local/share/pnpm` 에 store, `$HOME/.cache/pnpm` 에 cache 를
# 만드는데 이 경로는 ReadWritePaths 에 포함되므로 모든 배포판/모든 invoke
# 경로에서 확실히 동작. pnpm 은 내부적으로 `fs.mkdir` 를 `recursive:false`
# 로 호출하니 조부모 (`.local`, `.cache`) 까지는 미리 만들어야 한다.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
export HOME="/opt/kotify/.worker-home"
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
    # 3. .next/standalone 은 **건드리지 않는다**.
    #    과거엔 "rollback 후 미완 빌드 제거" 명분으로 `rm -rf` 했는데 오히려
    #    서비스를 무너뜨린다: 빌드 실패 시 git 은 직전 성공 커밋으로 되돌아
    #    갔지만, 이 성공 커밋이 만들어낸 standalone 까지 지우면 구동 중인
    #    Next.js 가 static chunk 를 못 찾아 "Loading chunk failed" 500 에러
    #    가 사용자에게 노출됨. Next 빌드는 standalone 을 매번 새로 덮어
    #    씌우므로 미완 빌드가 남을 가능성도 거의 없다 (build 최종 단계에서
    #    한 번에 copy). 다음 apply 가 성공하면 자연히 덮여진다.
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
