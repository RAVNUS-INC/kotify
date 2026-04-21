#!/usr/bin/env bash
# deploy/kotify-update.sh
# kotify 원클릭 업데이트 스크립트.
# 웹 UI에서 sudo로 호출됨 (kotify-sudoers 참조).
#
# 사용법:
#   sudo /opt/kotify/deploy/kotify-update.sh check   # 업데이트 확인 (JSON 출력)
#   sudo /opt/kotify/deploy/kotify-update.sh apply   # 업데이트 적용 + 두 서비스 재시작

set -euo pipefail

INSTALL_DIR="/opt/kotify"
WEB_DIR="${INSTALL_DIR}/web"
VENV="${INSTALL_DIR}/.venv"
SERVICE_API="kotify"       # FastAPI
SERVICE_WEB="kotify-web"   # Next.js
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
        # Phase 1: git pull
        echo '{"phase": "pull"}'
        git pull --ff-only origin "${BRANCH}" --quiet

        # Phase 2a: Python 의존성 설치 (변경 없어도 빠름)
        echo '{"phase": "install_backend"}'
        "${VENV}/bin/pip" install -e "${INSTALL_DIR}" --quiet 2>/dev/null

        # Phase 2b: DB 마이그레이션
        echo '{"phase": "migrate"}'
        "${VENV}/bin/alembic" -c "${INSTALL_DIR}/alembic.ini" upgrade head --quiet 2>/dev/null || true

        # Phase 3: Next.js 의존성 + 빌드
        # pnpm store 는 kotify 홈 밖이라 web 디렉토리 안에 격리.
        # standalone 빌드 후 static/public 자원을 standalone 디렉토리 안으로 복사.
        echo '{"phase": "install_web"}'
        cd "${WEB_DIR}"
        pnpm install --frozen-lockfile --silent 2>/dev/null

        echo '{"phase": "build_web"}'
        pnpm build 2>/dev/null >/dev/null

        # standalone 산출물에 필요한 정적 자원 복사
        # (Next.js output: 'standalone' 은 server.js 만 만들고 static/public 을
        # 따로 두지 않는다. 런타임에 필요한 파일이 빠져 있으면 404 가 뜸.)
        cp -R "${WEB_DIR}/.next/static" "${WEB_DIR}/.next/standalone/.next/"
        if [[ -d "${WEB_DIR}/public" ]]; then
            cp -R "${WEB_DIR}/public" "${WEB_DIR}/.next/standalone/"
        fi

        NEW_HASH=$(git -C "${INSTALL_DIR}" rev-parse --short HEAD)

        # Phase 4: 재시작 (2초 지연, 비동기)
        # 응답을 먼저 돌려받게 해서 웹 UI 에 '업데이트 실패' 오해 방지.
        # 두 서비스를 동시에 재시작(uvicorn 먼저, 직후 Next.js).
        echo '{"phase": "restart_scheduled"}'
        if command -v systemd-run >/dev/null 2>&1; then
            systemd-run --on-active=2s --unit="kotify-restart-$$" \
                /bin/systemctl restart "${SERVICE_API}" "${SERVICE_WEB}" >/dev/null 2>&1 || \
                (nohup bash -c "sleep 2 && systemctl restart ${SERVICE_API} ${SERVICE_WEB}" >/dev/null 2>&1 &)
        else
            nohup bash -c "sleep 2 && systemctl restart ${SERVICE_API} ${SERVICE_WEB}" >/dev/null 2>&1 &
        fi
        disown 2>/dev/null || true

        echo '{"phase": "done", "version": "'"${NEW_HASH}"'"}'
        ;;

    *)
        echo "Usage: $0 {check|apply}" >&2
        exit 1
        ;;
esac
