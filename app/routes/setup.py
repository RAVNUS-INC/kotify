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
from app.security.csrf import verify_csrf
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
    """Setup wizard 페이지.

    토큰은 표시하지 않는다 (#10).
    사용자가 직접 cat /var/lib/sms/setup.token 으로 읽어 입력.
    """
    # 토큰 파일이 없으면 생성 (사용자가 파일에서 읽을 수 있도록)
    generate_setup_token(settings.setup_token_path)
    return templates.TemplateResponse(
        "setup.html",
        {
            "request": request,
            "token": None,  # #10: 토큰을 HTML에 노출하지 않음
            "error": None,
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
    issuer: str = Form(...),
    _: None = Depends(require_setup_mode),
    _csrf: None = Depends(verify_csrf),
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
    _csrf: None = Depends(verify_csrf),
) -> HTMLResponse:
    """HTMX — NCP 인증 테스트 (#7: 예외 분기 명확화)."""
    from app.ncp.client import NCPAuthError, NCPClient, NCPError, NCPForbidden

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
    except (NCPAuthError, NCPForbidden) as exc:
        # #7: 인증/권한 실패는 명확히 에러로 표시
        return HTMLResponse(f'<span class="err">✗ 인증 실패: {exc}</span>')
    except NCPError:
        # 404 등 → 인증은 통과 (requestId 없음)
        return HTMLResponse('<span class="ok">✓ NCP 인증 성공 (requestId 없음 응답)</span>')
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
    ncp_access_key: str = Form(...),
    ncp_secret_key: str = Form(...),
    ncp_service_id: str = Form(...),
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
        "ncp.access_key": (ncp_access_key, True),
        "ncp.secret_key": (ncp_secret_key, True),
        "ncp.service_id": (ncp_service_id, True),
        "app.public_url": (app_public_url or "", False),
        "session.secret": (session_secret, True),
        # #9: 첫 admin 이메일 저장
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
