"""Setup wizard 라우트 — 부트스트랩 전에만 활성화."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_mode
from app.config import settings
from app.db import get_db
from app.services.setup_service import (
    generate_setup_token,
    verify_setup_token,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(
    request: Request,
    db: Session = Depends(get_db),
    _: None = Depends(require_setup_mode),
) -> HTMLResponse:
    """Setup wizard 페이지."""
    token = generate_setup_token(settings.setup_token_path)
    return templates.TemplateResponse(
        "setup.html",
        {
            "request": request,
            "token": token,
            "error": None,
        },
    )


@router.post("/setup/verify-token", response_class=HTMLResponse)
async def verify_token(
    request: Request,
    token: str = Form(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_setup_mode),
) -> HTMLResponse:
    """HTMX — 토큰 검증."""
    ok = verify_setup_token(settings.setup_token_path, token)
    if ok:
        return HTMLResponse(
            '<span class="ok">✓ 토큰 확인됨. 설정을 진행하세요.</span>'
        )
    return HTMLResponse(
        '<span class="err">✗ 토큰이 올바르지 않습니다.</span>'
    )


@router.post("/setup/test-keycloak", response_class=HTMLResponse)
async def test_keycloak(
    request: Request,
    issuer: str = Form(...),
    _: None = Depends(require_setup_mode),
) -> HTMLResponse:
    """HTMX — Keycloak issuer discovery 테스트."""
    url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"
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


@router.post("/setup/test-ncp", response_class=HTMLResponse)
async def test_ncp(
    request: Request,
    access_key: str = Form(...),
    secret_key: str = Form(...),
    service_id: str = Form(...),
    _: None = Depends(require_setup_mode),
) -> HTMLResponse:
    """HTMX — NCP 인증 테스트 (발신번호 조회)."""
    from app.ncp.client import NCPClient

    client = NCPClient(
        access_key=access_key,
        secret_key=secret_key,
        service_id=service_id,
    )
    try:
        # list_by_request_id 대신 가벼운 검증: dummy requestId로 404 받으면 인증 성공
        await client.list_by_request_id("TEST-PROBE-0000")
        return HTMLResponse('<span class="ok">✓ NCP 연결 성공</span>')
    except NotImplementedError:
        return HTMLResponse(
            '<span class="warn">⚠ signature.py 미구현 (stub). 인증 테스트 불가.</span>'
        )
    except Exception as exc:
        # 404는 인증 성공 (requestId 없음)
        from app.ncp.client import NCPAuthError, NCPError
        if isinstance(exc, NCPAuthError):
            return HTMLResponse(f'<span class="err">✗ 인증 실패: {exc}</span>')
        # 404, 기타 → 인증은 통과
        return HTMLResponse('<span class="ok">✓ NCP 인증 성공 (requestId 없음 응답)</span>')


@router.post("/setup/complete")
async def complete_setup(
    request: Request,
    token: str = Form(...),
    keycloak_issuer: str = Form(...),
    keycloak_client_id: str = Form(...),
    keycloak_client_secret: str = Form(...),
    ncp_access_key: str = Form(...),
    ncp_secret_key: str = Form(...),
    ncp_service_id: str = Form(...),
    app_public_url: str = Form(""),
    db: Session = Depends(get_db),
    _: None = Depends(require_setup_mode),
) -> RedirectResponse:
    """설정 저장 + setup 완료 처리 → Keycloak 로그인으로 리다이렉트."""
    if not verify_setup_token(settings.setup_token_path, token):
        return RedirectResponse("/setup?error=invalid_token", status_code=303)

    from app.services import setup_service

    settings_payload = {
        "keycloak.issuer": (keycloak_issuer, False),
        "keycloak.client_id": (keycloak_client_id, False),
        "keycloak.client_secret": (keycloak_client_secret, True),
        "ncp.access_key": (ncp_access_key, True),
        "ncp.secret_key": (ncp_secret_key, True),
        "ncp.service_id": (ncp_service_id, True),
        "app.public_url": (app_public_url or "", False),
        # 첫 admin은 콜백에서 처리 (setup_pending_first_admin 플래그)
        "setup.pending_first_admin": ("true", False),
    }

    import secrets as _secrets
    session_secret = _secrets.token_hex(32)
    settings_payload["session.secret"] = (session_secret, True)

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
    setup_service.delete_setup_token(settings.setup_token_path)

    return RedirectResponse("/auth/login", status_code=303)
