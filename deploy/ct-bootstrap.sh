#!/usr/bin/env bash
# deploy/ct-bootstrap.sh
# Proxmox LXC CT (Debian 12/13) 초기 셋업 스크립트
# 사용법: root 계정으로 실행
#   bash deploy/ct-bootstrap.sh
# 또는:
#   bash <(curl -fsSL https://raw.githubusercontent.com/RAVNUS-INC/kotify/main/deploy/ct-bootstrap.sh)

set -euo pipefail

# ── 설정 변수 ────────────────────────────────────────────────────────────────
# Private repo인 경우 GITHUB_TOKEN 환경변수 또는 REPO_URL 직접 지정
#   GITHUB_TOKEN=ghp_xxx bash ct-bootstrap.sh
#   REPO_URL=https://<token>@github.com/RAVNUS-INC/kotify.git bash ct-bootstrap.sh
if [[ -n "${REPO_URL:-}" ]]; then
    : # 사용자가 명시적으로 지정함
elif [[ -n "${GITHUB_TOKEN:-}" ]]; then
    REPO_URL="https://${GITHUB_TOKEN}@github.com/RAVNUS-INC/kotify.git"
else
    REPO_URL="https://github.com/RAVNUS-INC/kotify.git"
fi
INSTALL_DIR="/opt/kotify"
DATA_DIR="/var/lib/kotify"
LOG_DIR="/var/log/kotify"
BACKUP_DIR="/var/backups/kotify"
SERVICE_USER="kotify"
SERVICE_GROUP="kotify"
SERVICE_FILE="/etc/systemd/system/kotify.service"
# Python 바이너리는 OS 버전에 따라 동적으로 결정 (Step 2에서 PYTHON_BIN 설정)

# ── ANSI 색상 ────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "${GREEN}[OK]${NC}  $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*" >&2; exit 1; }
info() { echo -e "${BLUE}[--]${NC}  $*"; }
warn() { echo -e "${YELLOW}[!!]${NC}  $*"; }
step() { echo -e "\n${BOLD}==> $*${NC}"; }

# ── 루트 확인 ────────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    fail "이 스크립트는 root로 실행해야 합니다."
fi

echo -e "${BOLD}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║           kotify — CT 부트스트랩                      ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── Step 1: OS 확인 ──────────────────────────────────────────────────────────
step "1. OS 확인"
if [[ ! -f /etc/os-release ]]; then
    fail "/etc/os-release 없음. 지원되는 환경이 아닙니다."
fi

# shellcheck source=/dev/null
source /etc/os-release
if [[ "${ID}" != "debian" ]]; then
    fail "Debian이 아닙니다 (감지된 OS: ${ID}). 이 스크립트는 Debian 12/13을 지원합니다."
fi
case "${VERSION_ID}" in
    12|13) ;;
    *) warn "Debian ${VERSION_ID} 감지. 검증된 버전은 12(Bookworm)/13(Trixie)입니다." ;;
esac
ok "Debian ${VERSION_ID} (${VERSION_CODENAME}) 확인"

# ── Step 2: apt 업데이트 + 필수 패키지 설치 ──────────────────────────────────
step "2. 시스템 패키지 설치"
info "apt 업데이트 중..."
apt-get update -q

# Debian 버전에 따라 python 패키지명 결정
# - Debian 12 (bookworm): python3.11 기본, python3.12는 backports 필요
# - Debian 13 (trixie):   python3.13 기본
# pyproject.toml은 python>=3.12를 요구하므로 둘 다 호환
if [[ "${VERSION_ID}" == "13" ]]; then
    PY_PKG="python3.13"
    PY_VENV_PKG="python3.13-venv"
    PY_CMD="python3.13"
elif [[ "${VERSION_ID}" == "12" ]]; then
    PY_PKG="python3.12"
    PY_VENV_PKG="python3.12-venv"
    PY_CMD="python3.12"
else
    # 알 수 없는 버전 — python3 기본 사용 시도
    PY_PKG="python3"
    PY_VENV_PKG="python3-venv"
    PY_CMD="python3"
fi

info "Python 패키지: ${PY_PKG}"
if ! apt-get install -y -q \
        "${PY_PKG}" \
        "${PY_VENV_PKG}" \
        git \
        curl \
        ca-certificates \
        systemd-timesyncd \
        sqlite3; then
    # Debian 12에서 python3.12 실패 시 backports 시도
    if [[ "${VERSION_ID}" == "12" ]]; then
        warn "python3.12 패키지 설치 실패. backports 시도 중..."
        if ! grep -q "bookworm-backports" /etc/apt/sources.list /etc/apt/sources.list.d/*.list 2>/dev/null; then
            echo "deb http://deb.debian.org/debian bookworm-backports main" \
                > /etc/apt/sources.list.d/backports.list
            apt-get update -q
        fi
        apt-get install -y -q -t bookworm-backports python3.12 python3.12-venv || \
            fail "python3.12 설치 실패. 수동 설치 후 재실행하세요."
        apt-get install -y -q git curl ca-certificates systemd-timesyncd sqlite3
    else
        fail "${PY_PKG} 설치 실패. 수동 설치 후 재실행하세요."
    fi
fi
ok "필수 패키지 설치 완료"

# Python 바이너리 확인 — 버전이 >= 3.12이기만 하면 OK
PYTHON_BIN=$(command -v "${PY_CMD}") || fail "${PY_CMD} 바이너리를 찾을 수 없습니다."
PYTHON_VERSION=$($PYTHON_BIN --version 2>&1 | awk '{print $2}')
PY_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 12 ]]; }; then
    fail "Python ${PYTHON_VERSION} 감지. >= 3.12 가 필요합니다."
fi
ok "Python: ${PYTHON_VERSION}"

# ── Step 2b: Node.js 20 LTS + pnpm 설치 ─────────────────────────────────────
# Next.js 14가 Node 18.17+ / 20+ 를 요구. Debian 기본 저장소 버전은 보통 오래됐으므로
# NodeSource 공식 저장소를 추가해 20 LTS 설치.
step "2b. Node.js 20 LTS + pnpm 설치"
NODE_MAJOR=0
if command -v node >/dev/null 2>&1; then
    NODE_MAJOR=$(node --version | sed 's/v//' | cut -d. -f1)
fi

if [[ "${NODE_MAJOR}" -lt 20 ]]; then
    info "NodeSource 저장소 추가 + Node 20 설치 중..."
    curl -fsSL https://deb.nodesource.com/setup_20.x -o /tmp/nodesource_setup.sh
    bash /tmp/nodesource_setup.sh >/dev/null 2>&1
    apt-get install -y -q nodejs
    rm -f /tmp/nodesource_setup.sh
fi
NODE_VERSION=$(node --version)
ok "Node ${NODE_VERSION}"

# pnpm — Next.js 프로젝트가 pnpm-lock.yaml 기반. npm i -g 가 가장 보수적.
if ! command -v pnpm >/dev/null 2>&1; then
    info "pnpm 설치 중..."
    npm install -g pnpm --silent
fi
PNPM_VERSION=$(pnpm --version)
ok "pnpm ${PNPM_VERSION}"

# ── Step 3: NTP 활성화 + 시간 동기화 ────────────────────────────────────────
step "3. NTP 시간 동기화"
systemctl enable systemd-timesyncd --quiet
systemctl start systemd-timesyncd
timedatectl set-ntp true

# 최대 30초 대기하며 동기화 확인
SYNC_OK=false
for i in $(seq 1 6); do
    if timedatectl status | grep -q "synchronized: yes"; then
        SYNC_OK=true
        break
    fi
    info "NTP 동기화 대기 중... (${i}/6)"
    sleep 5
done

if [[ "$SYNC_OK" == "true" ]]; then
    ok "NTP 동기화 완료"
    timedatectl status | grep -E "Local time|synchronized"
else
    warn "NTP 동기화 미완료 (네트워크 확인 필요). NCP API는 5분 이내 시간 오차를 요구합니다."
    timedatectl status
fi

# ── Step 4: kotify 시스템 사용자/그룹 생성 ──────────────────────────────────
step "4. 시스템 사용자/그룹 생성"
if ! getent group "${SERVICE_GROUP}" > /dev/null 2>&1; then
    groupadd --system "${SERVICE_GROUP}"
    ok "그룹 '${SERVICE_GROUP}' 생성"
else
    info "그룹 '${SERVICE_GROUP}' 이미 존재"
fi

if ! id "${SERVICE_USER}" > /dev/null 2>&1; then
    useradd --system \
        --gid "${SERVICE_GROUP}" \
        --no-create-home \
        --shell /usr/sbin/nologin \
        --comment "kotify Service Account" \
        "${SERVICE_USER}"
    ok "사용자 '${SERVICE_USER}' 생성"
else
    info "사용자 '${SERVICE_USER}' 이미 존재"
fi

# ── Step 5: 디렉토리 생성 + 권한 설정 ───────────────────────────────────────
step "5. 디렉토리 생성 및 권한 설정"

# /opt/kotify (root:root 755) — git clone 대상이므로 root가 소유
install -d -m 755 -o root -g root "${INSTALL_DIR}"
ok "${INSTALL_DIR} (root:root 755)"

# 데이터/로그/백업 디렉토리 (kotify:kotify 700)
install -d -m 700 -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" "${DATA_DIR}"
ok "${DATA_DIR} (${SERVICE_USER}:${SERVICE_GROUP} 700)"

install -d -m 700 -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" "${LOG_DIR}"
ok "${LOG_DIR} (${SERVICE_USER}:${SERVICE_GROUP} 700)"

install -d -m 700 -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" "${BACKUP_DIR}"
ok "${BACKUP_DIR} (${SERVICE_USER}:${SERVICE_GROUP} 700)"

# ── Step 6: 코드 배포 ────────────────────────────────────────────────────────
step "6. 코드 배포 (git)"
# REPO_URL에서 인증 정보 제거한 표시용 URL (토큰 노출 방지)
DISPLAY_URL=$(echo "${REPO_URL}" | sed -E 's|https://[^@]+@|https://***@|')
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    info "이미 클론됨. git pull 실행..."
    git -C "${INSTALL_DIR}" pull --ff-only --quiet
    ok "코드 업데이트 완료"
else
    info "git clone: ${DISPLAY_URL} → ${INSTALL_DIR}"
    git clone --quiet "${REPO_URL}" "${INSTALL_DIR}"
    # 보안: clone 후 git remote에서 토큰 제거
    # (토큰이 평문으로 .git/config에 남는 것을 방지)
    git -C "${INSTALL_DIR}" remote set-url origin \
        "https://github.com/RAVNUS-INC/kotify.git"
    ok "코드 클론 완료 (remote URL에서 토큰 제거됨)"
fi

# ── Step 7: Python 가상환경 + 의존성 설치 ───────────────────────────────────
step "7. Python 가상환경 및 의존성 설치"
info "venv 생성: ${INSTALL_DIR}/.venv"
"${PYTHON_BIN}" -m venv "${INSTALL_DIR}/.venv"

info "pip 업그레이드..."
"${INSTALL_DIR}/.venv/bin/pip" install --upgrade pip --quiet

info "애플리케이션 의존성 설치..."
"${INSTALL_DIR}/.venv/bin/pip" install -e "${INSTALL_DIR}" --quiet
ok "Python 패키지 설치 완료"

# ── Step 7b: Next.js 빌드 (pnpm, standalone) ────────────────────────────────
step "7b. Next.js 빌드 (pnpm, standalone 모드)"
cd "${INSTALL_DIR}/web"

info "pnpm 의존성 설치 (--frozen-lockfile)..."
pnpm install --frozen-lockfile --silent

info "pnpm build (next build)..."
pnpm build

# standalone 산출물에 정적 자원 복사.
# Next.js `output: 'standalone'`은 server.js만 만들고 .next/static 과 public/ 은
# 따로 두지 않는다. 런타임에 필요한 파일이 빠져 있으면 HTTP 404가 발생하므로
# 부트스트랩 시점에 한 번 복사해둔다.
info "standalone 산출물에 static/public 복사..."
mkdir -p "${INSTALL_DIR}/web/.next/standalone/.next"
cp -R "${INSTALL_DIR}/web/.next/static" "${INSTALL_DIR}/web/.next/standalone/.next/"
if [[ -d "${INSTALL_DIR}/web/public" ]]; then
    cp -R "${INSTALL_DIR}/web/public" "${INSTALL_DIR}/web/.next/standalone/"
fi

# 소유권 정리 — systemd(kotify-web.service)가 kotify 유저로 읽을 수 있도록
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" \
    "${INSTALL_DIR}/web/.next" \
    "${INSTALL_DIR}/web/node_modules"
ok "Next.js 빌드 완료 (standalone + static/public 병합)"

cd "${INSTALL_DIR}"

# ── Step 8: DB 초기화 (alembic) ──────────────────────────────────────────────
step "8. 데이터베이스 초기화"
info "alembic upgrade head 실행..."
# DB를 /var/lib/kotify/에 생성하려면 kotify 사용자 권한으로 실행
# minimal CT는 sudo가 없을 수 있어 runuser(util-linux) 사용
runuser -u "${SERVICE_USER}" -- \
    env "PATH=${INSTALL_DIR}/.venv/bin:$PATH" \
    bash -c "cd ${INSTALL_DIR} && ${INSTALL_DIR}/.venv/bin/alembic upgrade head"
ok "DB 마이그레이션 완료 (${DATA_DIR}/sms.db)"

# ── Step 9: systemd 서비스 등록 ─────────────────────────────────────────────
step "9. systemd 서비스 등록 (kotify + kotify-web)"

# 9a. FastAPI (kotify.service)
if [[ -f "${INSTALL_DIR}/deploy/kotify.service" ]]; then
    cp "${INSTALL_DIR}/deploy/kotify.service" "${SERVICE_FILE}"
    ok "kotify.service 복사 완료: ${SERVICE_FILE}"
else
    fail "${INSTALL_DIR}/deploy/kotify.service 파일이 없습니다."
fi

# 9b. Next.js (kotify-web.service)
SERVICE_WEB_FILE="/etc/systemd/system/kotify-web.service"
if [[ -f "${INSTALL_DIR}/deploy/kotify-web.service" ]]; then
    cp "${INSTALL_DIR}/deploy/kotify-web.service" "${SERVICE_WEB_FILE}"
    ok "kotify-web.service 복사 완료: ${SERVICE_WEB_FILE}"
else
    fail "${INSTALL_DIR}/deploy/kotify-web.service 파일이 없습니다."
fi

systemctl daemon-reload

# FastAPI 먼저 (Next.js가 /api/* 로 호출하므로)
systemctl enable kotify kotify-web
systemctl restart kotify
ok "kotify(FastAPI) 서비스 활성화 및 시작"

systemctl restart kotify-web
ok "kotify-web(Next.js) 서비스 활성화 및 시작"

# sudoers — 웹 UI 원클릭 업데이트용
SUDOERS_SRC="${INSTALL_DIR}/deploy/kotify-sudoers"
SUDOERS_DST="/etc/sudoers.d/kotify-update"
if [[ -f "${SUDOERS_SRC}" ]]; then
    install -m 440 -o root -g root "${SUDOERS_SRC}" "${SUDOERS_DST}"
    chmod +x "${INSTALL_DIR}/deploy/kotify-update.sh"
    ok "sudoers 설치: ${SUDOERS_DST} (웹 UI 업데이트 허용)"
else
    warn "deploy/kotify-sudoers 없음. 웹 UI 업데이트가 동작하지 않습니다."
fi

# ── Step 10: 서비스 기동 확인 ────────────────────────────────────────────────
step "10. 서비스 상태 확인 (FastAPI + Next.js)"
sleep 5

# 10a. FastAPI
if systemctl is-active --quiet kotify; then
    ok "kotify(FastAPI) 서비스 실행 중"
else
    warn "kotify(FastAPI) 서비스가 시작되지 않았습니다. 로그를 확인하세요:"
    journalctl -u kotify -n 30 --no-pager
    fail "kotify(FastAPI) 서비스 시작 실패"
fi

if curl -sf http://127.0.0.1:8080/healthz > /dev/null; then
    ok "FastAPI 헬스체크 통과 (http://127.0.0.1:8080/healthz)"
else
    warn "FastAPI 헬스체크 실패. 서비스가 아직 준비 중일 수 있습니다."
    warn "잠시 후 수동으로 확인: curl http://127.0.0.1:8080/healthz"
fi

# 10b. Next.js
if systemctl is-active --quiet kotify-web; then
    ok "kotify-web(Next.js) 서비스 실행 중"
else
    warn "kotify-web(Next.js) 서비스가 시작되지 않았습니다. 로그를 확인하세요:"
    journalctl -u kotify-web -n 30 --no-pager
    fail "kotify-web(Next.js) 서비스 시작 실패"
fi

# Next.js는 로그인 전 `/`에서 login으로 302, /login은 200. 두 코드 모두 수용.
NEXT_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/login || echo 000)
if [[ "${NEXT_CODE}" == "200" ]]; then
    ok "Next.js 응답 정상 (http://127.0.0.1:3000/login → 200)"
else
    warn "Next.js 응답 비정상 (code=${NEXT_CODE}). 서비스 기동 직후일 수 있음."
    warn "잠시 후 수동 확인: curl -I http://127.0.0.1:3000/login"
fi

# ── Step 11: 백업 cron 설정 ─────────────────────────────────────────────────
step "11. 백업 cron 설정"
if [[ -f "${INSTALL_DIR}/deploy/kotify-backup.sh" ]]; then
    chmod +x "${INSTALL_DIR}/deploy/kotify-backup.sh"
    CRON_FILE="/etc/cron.d/kotify-backup"
    cp "${INSTALL_DIR}/deploy/kotify-backup.cron" "${CRON_FILE}"
    chmod 644 "${CRON_FILE}"
    ok "백업 cron 설치: ${CRON_FILE}"
else
    warn "deploy/kotify-backup.sh 없음. 백업 cron을 수동으로 설정하세요."
fi

# ── 완료 안내 ────────────────────────────────────────────────────────────────
SETUP_TOKEN_PATH="${DATA_DIR}/setup.token"

echo -e "\n${GREEN}${BOLD}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║              부트스트랩 완료!                         ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"

echo -e "${BOLD}다음 단계:${NC}"
echo ""
echo "  1. setup.token 확인:"
echo -e "     ${YELLOW}cat ${SETUP_TOKEN_PATH}${NC}"
echo ""
echo "  2. NPM(Nginx Proxy Manager)에서 도메인 호스트 설정:"
echo "     - 이 CT의 IP → 포트 8080 으로 프록시"
echo "     - Let's Encrypt SSL 발급 + Force SSL ON"
echo "     - 가이드: ${INSTALL_DIR}/deploy/npm-config.md"
echo ""
echo "  3. 브라우저에서 Setup Wizard 실행:"
echo -e "     ${YELLOW}https://your-domain.example.com/setup${NC}"
echo ""
echo "  4. Wizard 완료 후 master.key 백업 (중요!):"
echo -e "     ${YELLOW}cat ${DATA_DIR}/master.key${NC}"
echo "     → 안전한 위치에 보관 (DB와 분리)"
echo ""
echo "  5. E2E 검증:"
echo "     - 가이드: ${INSTALL_DIR}/claudedocs/E2E-CHECKLIST.md"
echo ""
echo -e "${BLUE}서비스 상태 확인: systemctl status kotify${NC}"
echo -e "${BLUE}로그 확인:        journalctl -u kotify -f${NC}"
echo -e "${BLUE}stdout 로그:      tail -f ${LOG_DIR}/stdout.log${NC}"
echo ""
