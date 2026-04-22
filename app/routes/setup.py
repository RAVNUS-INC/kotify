"""Setup wizard JSON API — fresh install 부트스트랩 전용.

fresh install 플로우:
    1. GET  /setup/status              공용, 부팅 여부 + CSRF 토큰 반환
    2. POST /setup/verify-token        토큰 파일 내용과 일치하는지 검증
    3. POST /setup/test-keycloak       (옵션) issuer discovery 성공 여부
    4. POST /setup/test-msghub         (옵션) 입력한 키로 인증 성공 여부
    5. POST /setup/complete            모든 설정 저장 + bootstrap.completed=true

bootstrap 완료 이후에는 GET /setup/status 만 응답(`completed=true`) 하고
나머지 엔드포인트는 모두 404 (`require_setup_mode`). 토큰 파일은 complete
성공 시 자동 삭제.

보안 모델:
  - 128-bit hex setup token (setup.token 파일, 600 권한)
  - bootstrap 완료 후 영구 비활성 (require_setup_mode 가 방어)
  - CSRF 토큰 필수 (POST). 세션은 로그인 이전이라도 pre-login 쿠키로 유지.
"""
from __future__ import annotations

import ipaddress
import secrets as _secrets
import socket
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_mode
from app.config import settings
from app.db import get_db
from app.security.csrf import get_csrf_token, verify_csrf
from app.security.settings_store import SettingsStore
from app.services import audit, setup_service

router = APIRouter()


def _validate_keycloak_issuer(url: str) -> Optional[str]:
    """SSRF 방지 — issuer URL 이 http(s) 이고 사설/링크로컬 IP 가 아닌지 확인.

    성공 시 None, 실패 시 에러 메시지를 돌려준다.
    개발 편의를 위해 localhost/127.x 는 허용 (dev 환경에서 자주 쓰임).
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "유효한 URL 형식이 아닙니다"
    if parsed.scheme not in ("http", "https"):
        return "http(s) URL 만 허용됩니다"
    host = parsed.hostname or ""
    if not host:
        return "호스트명을 확인할 수 없습니다"
    # localhost 는 명시적 허용 (dev).
    if host in ("localhost",):
        return None
    try:
        resolved = socket.gethostbyname(host)
        ip = ipaddress.ip_address(resolved)
    except (socket.gaierror, ValueError):
        # DNS 실패 시엔 issuer 테스트 자체가 실패하므로 여기서 차단할 필요 없음.
        return None
    # 사설망/링크로컬/loopback/reserved 차단 (127 은 localhost 별칭 허용 예외).
    if ip.is_loopback:
        return None
    if ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        return "사설망/링크로컬 IP 주소는 허용되지 않습니다"
    return None


# ── GET /setup/status ───────────────────────────────────────────────────────
# 공용. bootstrap 완료 여부 + CSRF 토큰을 반환. 프론트가 wizard 표시 여부
# 결정 + 첫 POST 를 위해 CSRF 토큰 확보.


@router.get("/setup/status")
def setup_status(request: Request, db: Session = Depends(get_db)) -> dict:
    store = SettingsStore(db)
    completed = store.is_bootstrap_completed()
    # 토큰 파일이 없으면 자동 생성 — 운영자가 cat 으로 읽어 입력할 수 있게.
    if not completed:
        setup_service.generate_setup_token(settings.setup_token_path)
    csrf_token = get_csrf_token(request)
    token_verified = bool(request.session.get("setup_token_verified"))
    return {
        "data": {
            "completed": completed,
            "tokenPath": str(settings.setup_token_path),
            "tokenVerified": token_verified,
            "csrfToken": csrf_token,
        }
    }


# ── POST /setup/verify-token ────────────────────────────────────────────────


class VerifyTokenBody(BaseModel):
    token: str = Field(..., min_length=1, max_length=256)


@router.post(
    "/setup/verify-token",
    dependencies=[Depends(require_setup_mode), Depends(verify_csrf)],
    response_model=None,
)
def verify_token(
    body: VerifyTokenBody, request: Request
) -> dict | JSONResponse:
    ok = setup_service.verify_setup_token(settings.setup_token_path, body.token)
    if not ok:
        return JSONResponse(
            {"error": {
                "code": "invalid_token",
                "message": "토큰이 올바르지 않습니다",
            }},
            status_code=422,
        )
    request.session["setup_token_verified"] = True
    return {"data": {"verified": True}}


# ── POST /setup/test-keycloak ───────────────────────────────────────────────


class TestKeycloakBody(BaseModel):
    keycloakIssuer: str = Field(..., min_length=1)


@router.post(
    "/setup/test-keycloak",
    dependencies=[Depends(require_setup_mode), Depends(verify_csrf)],
    response_model=None,
)
async def test_keycloak(body: TestKeycloakBody) -> dict | JSONResponse:
    """Keycloak issuer discovery 엔드포인트(.well-known/openid-configuration) 호출."""
    err = _validate_keycloak_issuer(body.keycloakIssuer)
    if err:
        return JSONResponse(
            {"error": {"code": "invalid_url", "message": err}},
            status_code=422,
        )
    url = f"{body.keycloakIssuer.rstrip('/')}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
    except Exception as exc:
        return JSONResponse(
            {"error": {"code": "connect_failed", "message": f"연결 실패: {exc}"}},
            status_code=502,
        )
    if resp.status_code != 200:
        return JSONResponse(
            {"error": {
                "code": "discovery_failed",
                "message": f"HTTP {resp.status_code}",
            }},
            status_code=502,
        )
    try:
        meta = resp.json()
        issuer_val = meta.get("issuer") or ""
    except Exception:
        issuer_val = ""
    return {"data": {"ok": True, "issuer": issuer_val}}


# ── POST /setup/test-msghub ─────────────────────────────────────────────────


class TestMsghubBody(BaseModel):
    msghubApiKey: str = Field(..., min_length=1)
    msghubApiPwd: str = Field(..., min_length=1)
    msghubEnv: str = Field(default="production")


@router.post(
    "/setup/test-msghub",
    dependencies=[Depends(require_setup_mode), Depends(verify_csrf)],
    response_model=None,
)
async def test_msghub(body: TestMsghubBody) -> dict | JSONResponse:
    """setup 단계에서는 DB 저장 전 값으로 테스트 — 본문 필드를 직접 사용."""
    try:
        from app.msghub.auth import AuthError
        from app.msghub.client import MsghubClient
    except ImportError:
        return JSONResponse(
            {"error": {"code": "msghub_unavailable", "message": "msghub 모듈 로드 실패"}},
            status_code=503,
        )

    client = MsghubClient(
        env=body.msghubEnv,
        api_key=body.msghubApiKey,
        api_pwd=body.msghubApiPwd,
    )
    try:
        await client.test_auth()
        return {"data": {"ok": True, "env": body.msghubEnv}}
    except AuthError as exc:
        return JSONResponse(
            {"error": {"code": "auth_failed", "message": f"인증 실패: {exc}"}},
            status_code=422,
        )
    except Exception as exc:
        return JSONResponse(
            {"error": {"code": "connect_failed", "message": f"연결 실패: {exc}"}},
            status_code=502,
        )
    finally:
        try:
            await client.aclose()
        except Exception:
            pass


# ── POST /setup/complete ────────────────────────────────────────────────────


class CompleteSetupBody(BaseModel):
    token: str = Field(..., min_length=1, max_length=256)
    # Keycloak (필수)
    keycloakIssuer: str = Field(..., min_length=1)
    keycloakClientId: str = Field(..., min_length=1)
    keycloakClientSecret: str = Field(..., min_length=1)
    # msghub (필수)
    msghubApiKey: str = Field(..., min_length=1)
    msghubApiPwd: str = Field(..., min_length=1)
    msghubEnv: str = Field(default="production")
    msghubBrandId: Optional[str] = None
    msghubChatbotId: Optional[str] = None
    # App (옵션)
    appPublicUrl: Optional[str] = None
    # 첫 admin email — Keycloak 에서 이 이메일로 로그인한 사용자가 자동 admin 승격.
    firstAdminEmail: Optional[str] = None


@router.post(
    "/setup/complete",
    dependencies=[Depends(require_setup_mode), Depends(verify_csrf)],
    response_model=None,
)
async def complete_setup(
    body: CompleteSetupBody,
    request: Request,
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    """설정 저장 + bootstrap.completed=true. 이후 `/auth/login` 으로 진행해
    설정한 Keycloak 에서 로그인하면 firstAdminEmail 과 일치하는 사용자가 admin
    으로 승격된다 (auth.callback 로직).

    세션 검증 또는 form 토큰 중 하나라도 유효하면 통과 (이중 검증).
    """
    # 세션 검증 우선 — verify-token 거친 정상 경로.
    session_verified = bool(request.session.get("setup_token_verified"))
    if not session_verified:
        # 직접 complete 만 호출하는 경우 — 파일 재검증.
        if not setup_service.verify_setup_token(
            settings.setup_token_path, body.token
        ):
            return JSONResponse(
                {"error": {
                    "code": "invalid_token",
                    "message": "setup 토큰이 올바르지 않습니다",
                }},
                status_code=422,
            )

    # Keycloak issuer 가 동작하는지 *커밋 전* 검증 — 설치 직후 /auth/login 500
    # (bricking) 을 예방. discovery 엔드포인트 도달 가능성만 확인.
    err = _validate_keycloak_issuer(body.keycloakIssuer)
    if err:
        return JSONResponse(
            {"error": {"code": "invalid_keycloak_url", "message": err}},
            status_code=422,
        )
    try:
        url = (
            f"{body.keycloakIssuer.rstrip('/')}"
            "/.well-known/openid-configuration"
        )
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return JSONResponse(
                {"error": {
                    "code": "keycloak_unreachable",
                    "message": f"Keycloak discovery 응답 HTTP {resp.status_code}",
                }},
                status_code=422,
            )
    except Exception as exc:
        return JSONResponse(
            {"error": {
                "code": "keycloak_unreachable",
                "message": f"Keycloak 연결 실패: {exc}",
            }},
            status_code=422,
        )

    # session.secret 은 서버가 랜덤 생성. 클라이언트가 제공하지 않는다.
    session_secret = _secrets.token_hex(32)

    payload: dict[str, tuple[str, bool]] = {
        "keycloak.issuer": (body.keycloakIssuer.strip(), False),
        "keycloak.client_id": (body.keycloakClientId.strip(), False),
        "keycloak.client_secret": (body.keycloakClientSecret, True),
        "msghub.api_key": (body.msghubApiKey, True),
        "msghub.api_pwd": (body.msghubApiPwd, True),
        "msghub.env": (body.msghubEnv.strip(), False),
        "msghub.brand_id": ((body.msghubBrandId or "").strip(), False),
        "msghub.chatbot_id": ((body.msghubChatbotId or "").strip(), False),
        "app.public_url": ((body.appPublicUrl or "").strip().rstrip("/"), False),
        "session.secret": (session_secret, True),
        "setup.first_admin_email": ((body.firstAdminEmail or "").strip(), False),
        "setup.pending_first_admin": ("true", False),
    }

    store = SettingsStore(db)
    for key, (value, is_secret) in payload.items():
        store.set(key, value, is_secret=is_secret, updated_by="setup")
    store.mark_bootstrap_completed("setup")
    audit.log(db, actor_sub=None, action=audit.BOOTSTRAP_INIT)
    db.commit()

    # setup token 파일 삭제
    setup_service.delete_setup_token(settings.setup_token_path)
    # 세션에서 검증 플래그 제거
    request.session.pop("setup_token_verified", None)

    return {
        "data": {
            "completed": True,
            # 다음 이동할 경로 — 프론트가 window.location.href 로 이동.
            "next": "/auth/login",
            # 앱 재시작 권장 — SessionMiddleware 는 startup 시점의 secret 을
            # 그대로 쓰므로 새 session.secret 이 활성화되려면 프로세스 재시작
            # 필요. 재시작 전 세션은 fallback secret 으로 서명되어 재시작 후
            # 무효화됨. 프론트가 사용자에게 안내하도록 시그널.
            "restartRecommended": True,
        }
    }
