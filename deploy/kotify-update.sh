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
        # 롤백 지점: git pull 전 HEAD 기록. 이후 단계에서 실패하면
        # trap ERR 에서 자동으로 이 커밋으로 되돌린다.
        PREV_HEAD=$(git -C "${INSTALL_DIR}" rev-parse HEAD)
        trap '
            echo "{\"phase\": \"error\", \"rollback\": true, \"to\": \"'"${PREV_HEAD:0:7}"'\"}"
            git -C "'"${INSTALL_DIR}"'" reset --hard "'"${PREV_HEAD}"'" >/dev/null 2>&1 || true
        ' ERR

        # Phase 1: git pull
        echo '{"phase": "pull"}'
        git pull --ff-only origin "${BRANCH}" --quiet

        # Phase 2a: Python 의존성 설치 (변경 없어도 빠름)
        echo '{"phase": "install_backend"}'
        "${VENV}/bin/pip" install -e "${INSTALL_DIR}" --quiet

        # Phase 2b: DB 마이그레이션 — 실패 시 중단 (silent swallow 금지).
        # 실패를 숨기면 신규 코드가 구 스키마로 구동되어 모든 요청이 크래시한다.
        echo '{"phase": "migrate"}'
        if ! "${VENV}/bin/alembic" -c "${INSTALL_DIR}/alembic.ini" upgrade head 2>&1; then
            echo '{"phase": "error", "step": "migrate", "message": "alembic upgrade failed"}'
            exit 1
        fi

        # Phase 3: Next.js 의존성 + 빌드
        echo '{"phase": "install_web"}'
        cd "${WEB_DIR}"
        pnpm install --frozen-lockfile --silent

        echo '{"phase": "build_web"}'
        # FASTAPI_URL 은 빌드 타임에 next.config.mjs rewrites destination 에 baked 된다.
        # 누락 시 localhost:8000 로 빠지는 과거 버그 재발 방지 목적으로 명시.
        FASTAPI_URL=http://127.0.0.1:8080 pnpm build >/dev/null

        # standalone 산출물에 정적 자원 merge
        # (Next.js output: 'standalone' 은 server.js 만 만들고 static/public 을
        # 따로 두지 않는다. 런타임에 필요한 파일이 빠져 있으면 404 가 뜸.)
        #
        # ⚠ race 주의: 과거엔 `rm -rf static && cp -R ...` 였는데 systemctl
        # restart 가 2초 뒤 비동기라, rm~restart 사이의 짧은 window 에 구
        # process 가 메모리의 옛 hash 를 디스크에서 못 찾아 **404** 발생.
        # 브라우저가 이 404 를 캐시하면 지속적으로 CSS 가 깨져 보임.
        #
        # 해결: 삭제하지 않고 `cp -R <src>/. <dst>/` 로 내용물만 merge.
        # 새/옛 hash 는 파일명이 달라 충돌 없고, 재시작 후에는 신규 HTML 이
        # 신규 hash 를 참조. 옛 hash 파일들은 누적되지만 ct-bootstrap 재실행
        # 시 fresh install 로 정리됨 (문제없음).
        mkdir -p "${WEB_DIR}/.next/standalone/.next/static"
        cp -R "${WEB_DIR}/.next/static/." "${WEB_DIR}/.next/standalone/.next/static/"
        if [[ -d "${WEB_DIR}/public" ]]; then
            mkdir -p "${WEB_DIR}/.next/standalone/public"
            # public 은 파일명 충돌 가능하지만 덮어쓰기가 정답 (새 우선).
            cp -R "${WEB_DIR}/public/." "${WEB_DIR}/.next/standalone/public/"
        fi

        # 빌드 성공까지 왔으니 ERR trap 해제 (재시작 단계에서는 롤백 불필요)
        trap - ERR

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
