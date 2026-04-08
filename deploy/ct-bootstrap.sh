#!/usr/bin/env bash
# deploy/ct-bootstrap.sh
# Proxmox LXC CT (Debian 12) 초기 셋업 스크립트
# 사용법: root 계정으로 실행
#   bash deploy/ct-bootstrap.sh
# 또는:
#   bash <(curl -fsSL https://raw.githubusercontent.com/RAVNUS-INC/sms-sys/main/deploy/ct-bootstrap.sh)

set -euo pipefail

# ── 설정 변수 ────────────────────────────────────────────────────────────────
# Private repo인 경우 GITHUB_TOKEN 환경변수 또는 REPO_URL 직접 지정
#   GITHUB_TOKEN=ghp_xxx bash ct-bootstrap.sh
#   REPO_URL=https://<token>@github.com/RAVNUS-INC/sms-sys.git bash ct-bootstrap.sh
if [[ -n "${REPO_URL:-}" ]]; then
    : # 사용자가 명시적으로 지정함
elif [[ -n "${GITHUB_TOKEN:-}" ]]; then
    REPO_URL="https://${GITHUB_TOKEN}@github.com/RAVNUS-INC/sms-sys.git"
else
    REPO_URL="https://github.com/RAVNUS-INC/sms-sys.git"
fi
INSTALL_DIR="/opt/sms"
DATA_DIR="/var/lib/sms"
LOG_DIR="/var/log/sms"
BACKUP_DIR="/var/backups/sms"
SERVICE_USER="sms"
SERVICE_GROUP="sms"
SERVICE_FILE="/etc/systemd/system/sms.service"
PYTHON="python3.12"

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
echo "║       사내 SMS 발송 시스템 — CT 부트스트랩            ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ── Step 1: Debian 12 확인 ───────────────────────────────────────────────────
step "1. OS 확인"
if [[ ! -f /etc/os-release ]]; then
    fail "/etc/os-release 없음. Debian 12 이 아닌 환경입니다."
fi

# shellcheck source=/dev/null
source /etc/os-release
if [[ "${ID}" != "debian" ]]; then
    fail "Debian이 아닙니다 (감지된 OS: ${ID}). 이 스크립트는 Debian 12 전용입니다."
fi
if [[ "${VERSION_ID}" != "12" ]]; then
    warn "Debian ${VERSION_ID} 감지. 이 스크립트는 Debian 12(Bookworm)를 기준으로 작성되었습니다."
fi
ok "Debian ${VERSION_ID} (${VERSION_CODENAME}) 확인"

# ── Step 2: apt 업데이트 + 필수 패키지 설치 ──────────────────────────────────
step "2. 시스템 패키지 설치"
info "apt 업데이트 중..."
apt-get update -q

# python3.12 설치 가능 여부 확인
# Debian 12(Bookworm) 기본 저장소에는 python3.11이 기본이고,
# python3.12는 backports 또는 deadsnakes PPA가 필요할 수 있습니다.
# 만약 아래 설치가 실패하면:
#   - deadsnakes PPA (Ubuntu 전용이라 Debian에선 직접 지원 안 됨):
#       add-apt-repository ppa:deadsnakes/ppa (Ubuntu only)
#   - Debian backports 활성화:
#       echo "deb http://deb.debian.org/debian bookworm-backports main" >> /etc/apt/sources.list
#       apt-get update && apt-get install -t bookworm-backports python3.12 python3.12-venv
#   - 또는 pyenv로 빌드:
#       curl https://pyenv.run | bash && pyenv install 3.12.x
if ! apt-get install -y -q \
        python3.12 \
        python3.12-venv \
        git \
        curl \
        ca-certificates \
        systemd-timesyncd \
        sqlite3; then
    warn "python3.12 패키지 설치 실패. backports 시도 중..."
    if ! grep -q "bookworm-backports" /etc/apt/sources.list /etc/apt/sources.list.d/*.list 2>/dev/null; then
        echo "deb http://deb.debian.org/debian bookworm-backports main" \
            > /etc/apt/sources.list.d/backports.list
        apt-get update -q
    fi
    apt-get install -y -q -t bookworm-backports python3.12 python3.12-venv || \
        fail "python3.12 설치 실패. 수동으로 python3.12를 설치한 후 재실행하세요."
    apt-get install -y -q git curl ca-certificates systemd-timesyncd sqlite3
fi
ok "필수 패키지 설치 완료"

# python3.12 경로 확인
PYTHON_BIN=$(command -v python3.12) || fail "python3.12 바이너리를 찾을 수 없습니다."
ok "Python: $($PYTHON_BIN --version)"

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

# ── Step 4: sms 시스템 사용자/그룹 생성 ─────────────────────────────────────
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
        --comment "SMS Service Account" \
        "${SERVICE_USER}"
    ok "사용자 '${SERVICE_USER}' 생성"
else
    info "사용자 '${SERVICE_USER}' 이미 존재"
fi

# ── Step 5: 디렉토리 생성 + 권한 설정 ───────────────────────────────────────
step "5. 디렉토리 생성 및 권한 설정"

# /opt/sms (root:root 755) — git clone 대상이므로 root가 소유
install -d -m 755 -o root -g root "${INSTALL_DIR}"
ok "${INSTALL_DIR} (root:root 755)"

# 데이터/로그/백업 디렉토리 (sms:sms 700)
install -d -m 700 -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" "${DATA_DIR}"
ok "${DATA_DIR} (${SERVICE_USER}:${SERVICE_GROUP} 700)"

install -d -m 700 -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" "${LOG_DIR}"
ok "${LOG_DIR} (${SERVICE_USER}:${SERVICE_GROUP} 700)"

install -d -m 700 -o "${SERVICE_USER}" -g "${SERVICE_GROUP}" "${BACKUP_DIR}"
ok "${BACKUP_DIR} (${SERVICE_USER}:${SERVICE_GROUP} 700)"

# ── Step 6: 코드 배포 ────────────────────────────────────────────────────────
step "6. 코드 배포 (git)"
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    info "이미 클론됨. git pull 실행..."
    git -C "${INSTALL_DIR}" pull --ff-only
    ok "코드 업데이트 완료"
else
    info "git clone: ${REPO_URL} → ${INSTALL_DIR}"
    git clone "${REPO_URL}" "${INSTALL_DIR}"
    ok "코드 클론 완료"
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

# ── Step 8: DB 초기화 (alembic) ──────────────────────────────────────────────
step "8. 데이터베이스 초기화"
info "alembic upgrade head 실행..."
# DB를 /var/lib/sms/에 생성하려면 sms 사용자 권한으로 실행
sudo -u "${SERVICE_USER}" \
    env "PATH=${INSTALL_DIR}/.venv/bin:$PATH" \
    bash -c "cd ${INSTALL_DIR} && ${INSTALL_DIR}/.venv/bin/alembic upgrade head"
ok "DB 마이그레이션 완료 (${DATA_DIR}/sms.db)"

# ── Step 9: systemd 서비스 등록 ─────────────────────────────────────────────
step "9. systemd 서비스 등록"
if [[ -f "${INSTALL_DIR}/deploy/sms.service" ]]; then
    cp "${INSTALL_DIR}/deploy/sms.service" "${SERVICE_FILE}"
    ok "sms.service 복사 완료: ${SERVICE_FILE}"
else
    fail "${INSTALL_DIR}/deploy/sms.service 파일이 없습니다."
fi

systemctl daemon-reload
systemctl enable sms
systemctl restart sms
ok "sms 서비스 활성화 및 시작"

# ── Step 10: 서비스 기동 확인 ────────────────────────────────────────────────
step "10. 서비스 상태 확인"
sleep 3
if systemctl is-active --quiet sms; then
    ok "sms 서비스 실행 중"
else
    warn "sms 서비스가 시작되지 않았습니다. 로그를 확인하세요:"
    journalctl -u sms -n 30 --no-pager
    fail "서비스 시작 실패"
fi

# 헬스체크
if curl -sf http://127.0.0.1:8080/healthz > /dev/null; then
    ok "헬스체크 통과 (http://127.0.0.1:8080/healthz)"
else
    warn "헬스체크 실패. 서비스가 아직 준비 중일 수 있습니다."
    warn "잠시 후 수동으로 확인: curl http://127.0.0.1:8080/healthz"
fi

# ── Step 11: 백업 cron 설정 ─────────────────────────────────────────────────
step "11. 백업 cron 설정"
if [[ -f "${INSTALL_DIR}/deploy/sms-backup.sh" ]]; then
    chmod +x "${INSTALL_DIR}/deploy/sms-backup.sh"
    CRON_FILE="/etc/cron.d/sms-backup"
    cp "${INSTALL_DIR}/deploy/sms-backup.cron" "${CRON_FILE}"
    chmod 644 "${CRON_FILE}"
    ok "백업 cron 설치: ${CRON_FILE}"
else
    warn "deploy/sms-backup.sh 없음. 백업 cron을 수동으로 설정하세요."
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
echo "  2. NPM(Nginx Proxy Manager)에서 sms.example.com 호스트 설정:"
echo "     - 이 CT의 IP → 포트 8080 으로 프록시"
echo "     - Let's Encrypt SSL 발급 + Force SSL ON"
echo "     - 가이드: ${INSTALL_DIR}/deploy/npm-config.md"
echo ""
echo "  3. 브라우저에서 Setup Wizard 실행:"
echo -e "     ${YELLOW}https://sms.example.com/setup${NC}"
echo ""
echo "  4. Wizard 완료 후 master.key 백업 (중요!):"
echo -e "     ${YELLOW}cat ${DATA_DIR}/master.key${NC}"
echo "     → 1Password 또는 사내 비밀 저장소에 안전하게 보관"
echo ""
echo "  5. E2E 검증:"
echo "     - 가이드: ${INSTALL_DIR}/claudedocs/E2E-CHECKLIST.md"
echo ""
echo -e "${BLUE}서비스 상태 확인: systemctl status sms${NC}"
echo -e "${BLUE}로그 확인:        journalctl -u sms -f${NC}"
echo -e "${BLUE}stdout 로그:      tail -f ${LOG_DIR}/stdout.log${NC}"
echo ""
