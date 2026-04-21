"""Setup wizard 라우트 — 부트스트랩 전에만 활성화."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_mode
from app.config import settings
from app.db import get_db
from app.security.csrf import verify_csrf
from app.services.setup_service import (
    generate_setup_token,
    verify_setup_token,
)
from app.web import templates

router = APIRouter()


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_setup_mode),
) -> HTMLResponse:
    """Setup wizard 페이지.

    토큰은 표시하지 않는다 (#10).
    사용자가 직접 cat /var/lib/kotify/setup.token 으로 읽어 입력.
    """
    # 토큰 파일이 없으면 생성 (사용자가 파일에서 읽을 수 있도록)
    generate_setup_token(settings.setup_token_path)
    return templates.TemplateResponse(
        request,
        "setup.html",
        {
            "token": None,  # #10: 토큰을 HTML에 노출하지 않음
            "error": None,
            "setup_token_path": str(settings.setup_token_path),  # R9
        },
    )


@router.post("/setup/verify-token", response_class=HTMLResponse)
async def verify_token(
    request: Request,
    token: str = Form(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_setup_mode),
    _csrf: None = Depends(verify_csrf),
) -> HTMLResponse:
    """HTMX — 토큰 검증. 성공 시 세션에 검증 상태 저장 (#10)."""
    ok = verify_setup_token(settings.setup_token_path, token)
    if ok:
        request.session["setup_token_verified"] = True
        return HTMLResponse(
            '<span class="ok">✓ 토큰 확인됨. 설정을 진행하세요.</span>'
        )
    return HTMLResponse(
        '<span class="err">✗ 토큰이 올바르지 않습니다.</span>'
    )


@router.post("/setup/test-keycloak", response_class=HTMLResponse)
async def test_keycloak(
    request: Request,
    keycloak_issuer: str = Form(...),
    _: None = Depends(require_setup_mode),
    _csrf: None = Depends(verify_csrf),
) -> HTMLResponse:
    """HTMX — Keycloak issuer discovery 테스트.

    HTML form 필드명 keycloak_issuer를 그대로 받음 (/setup/complete와 일관).
    """
    url = f"{keycloak_issuer.rstrip('/')}/.well-known/openid-configuration"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
        if resp.status_code == 200:
            return HTMLResponse('<span class="ok">✓ Keycloak 연결 성공</span>')
        return HTMLResponse(
            f'<span class="err">✗ HTTP {resp.status_code}</span>'
        )
    except Exception as exc:
        return HTMLResponse(f'<span class="err">✗ 연결 실패: {exc}</span>')


@router.post("/setup/test-msghub", response_class=HTMLResponse)
async def test_msghub(
    request: Request,
    msghub_api_key: str = Form(...),
    msghub_api_pwd: str = Form(...),
    _: None = Depends(require_setup_mode),
    _csrf: None = Depends(verify_csrf),
) -> HTMLResponse:
    """HTMX — msghub 인증 테스트."""
    from app.msghub.auth import AuthError
    from app.msghub.client import MsghubClient

    client = MsghubClient(
        env="production",
        api_key=msghub_api_key,
        api_pwd=msghub_api_pwd,
    )
    try:
        await client.test_auth()
        return HTMLResponse('<span class="ok">✓ msghub 연결 성공</span>')
    except AuthError as exc:
        return HTMLResponse(f'<span class="err">✗ 인증 실패: {exc}</span>')
    except Exception as exc:
        return HTMLResponse(f'<span class="err">✗ 연결 실패: {exc}</span>')
    finally:
        await client.aclose()


@router.post("/setup/complete")
async def complete_setup(
    request: Request,
    token: str = Form(...),
    keycloak_issuer: str = Form(...),
    keycloak_client_id: str = Form(...),
    keycloak_client_secret: str = Form(...),
    msghub_api_key: str = Form(...),
    msghub_api_pwd: str = Form(...),
    msghub_env: str = Form("production"),
    msghub_brand_id: str = Form(""),
    msghub_chatbot_id: str = Form(""),
    app_public_url: str = Form(""),
    first_admin_email: str = Form(""),
    db: Session = Depends(get_db),
    _: None = Depends(require_setup_mode),
    _csrf: None = Depends(verify_csrf),
) -> RedirectResponse:
    """설정 저장 + setup 완료 처리 → Keycloak 로그인으로 리다이렉트.

    #8: setup_service.complete_setup 위임으로 중복 제거.
    #10: 세션 검증 상태 또는 form 토큰으로 이중 검증.
    #9: first_admin_email 저장.
    """
    # #10: 세션 검증 상태 확인 (verify-token 단계 우회 방지)
    session_verified = request.session.get("setup_token_verified", False)
    if not session_verified:
        # 세션에 없으면 file-based 재검증
        if not verify_setup_token(settings.setup_token_path, token):
            return RedirectResponse("/setup?error=invalid_token", status_code=303)

    import secrets as _secrets
    session_secret = _secrets.token_hex(32)

    settings_payload: dict = {
        "keycloak.issuer": (keycloak_issuer, False),
        "keycloak.client_id": (keycloak_client_id, False),
        "keycloak.client_secret": (keycloak_client_secret, True),
        "msghub.api_key": (msghub_api_key, True),
        "msghub.api_pwd": (msghub_api_pwd, True),
        "msghub.env": (msghub_env, False),
        "msghub.brand_id": (msghub_brand_id, False),
        "msghub.chatbot_id": (msghub_chatbot_id, False),
        "app.public_url": (app_public_url or "", False),
        "session.secret": (session_secret, True),
        "setup.first_admin_email": (first_admin_email or "", False),
        "setup.pending_first_admin": ("true", False),
    }

    from app.security.settings_store import SettingsStore
    from app.services.audit import BOOTSTRAP_INIT, log

    store = SettingsStore(db)
    for key, val in settings_payload.items():
        value, is_secret = val
        store.set(key, value, is_secret=is_secret, updated_by="setup")

    store.mark_bootstrap_completed("setup")

    log(db, actor_sub=None, action=BOOTSTRAP_INIT)
    db.commit()

    # setup token 삭제
    from app.services import setup_service
    setup_service.delete_setup_token(settings.setup_token_path)

    # 세션에서 검증 상태 제거
    request.session.pop("setup_token_verified", None)

    return RedirectResponse("/auth/login", status_code=303)
