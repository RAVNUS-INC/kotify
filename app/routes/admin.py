"""관리자 라우트 — 설정, 발신번호, 감사 로그."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_role, require_setup_complete
from app.db import get_db
from app.models import AuditLog, Caller, User
from app.security.csrf import verify_csrf
from app.security.settings_store import SettingsStore
from app.services import audit

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")

_admin_dep = require_role("admin")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── 설정 ─────────────────────────────────────────────────────────────────────


@router.get("/settings", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_admin_dep),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """설정 페이지 — 시크릿은 mask 적용."""
    store = SettingsStore(db)

    # 공개 설정
    public_settings = store.get_all_public()

    # 시크릿 설정은 마스킹
    secret_keys = [
        "ncp.access_key",
        "ncp.secret_key",
        "ncp.service_id",
        "keycloak.client_secret",
        "session.secret",
    ]
    secret_display: dict[str, str] = {}
    for key in secret_keys:
        val = store.get(key)
        secret_display[key] = SettingsStore.mask(val) if val else ""

    try:
        user_roles = json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        user_roles = []

    return templates.TemplateResponse(
        "admin/settings.html",
        {
            "request": request,
            "user": user,
            "user_roles": user_roles,
            "public_settings": public_settings,
            "secret_display": secret_display,
        },
    )


@router.post("/settings")
async def settings_save(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_admin_dep),
    _csrf: None = Depends(verify_csrf),
    keycloak_issuer: str = Form(""),
    keycloak_client_id: str = Form(""),
    keycloak_client_secret: str = Form(""),
    ncp_access_key: str = Form(""),
    ncp_secret_key: str = Form(""),
    ncp_service_id: str = Form(""),
    app_public_url: str = Form(""),
    session_secret: str = Form(""),
) -> RedirectResponse:
    """설정 저장 — 빈 값인 시크릿은 변경하지 않음."""
    store = SettingsStore(db)

    # 공개 설정 (항상 저장)
    if keycloak_issuer:
        store.set("keycloak.issuer", keycloak_issuer, is_secret=False, updated_by=user.sub)
    if keycloak_client_id:
        store.set("keycloak.client_id", keycloak_client_id, is_secret=False, updated_by=user.sub)
    if app_public_url:
        store.set("app.public_url", app_public_url, is_secret=False, updated_by=user.sub)

    # 시크릿 — 빈 값이면 변경하지 않음
    if keycloak_client_secret:
        store.set("keycloak.client_secret", keycloak_client_secret, is_secret=True, updated_by=user.sub)
    if ncp_access_key:
        store.set("ncp.access_key", ncp_access_key, is_secret=True, updated_by=user.sub)
    if ncp_secret_key:
        store.set("ncp.secret_key", ncp_secret_key, is_secret=True, updated_by=user.sub)
    if ncp_service_id:
        store.set("ncp.service_id", ncp_service_id, is_secret=True, updated_by=user.sub)
    if session_secret:
        store.set("session.secret", session_secret, is_secret=True, updated_by=user.sub)

    audit.log(db, actor_sub=user.sub, action=audit.SETTINGS_UPDATE)
    db.commit()

    # NCP 설정 변경 가능성이 있으므로 클라이언트 재초기화 (#28)
    from app.main import reset_ncp_client
    reset_ncp_client()

    return RedirectResponse("/admin/settings?saved=1", status_code=303)


@router.post("/settings/test-ncp", response_class=HTMLResponse)
async def test_ncp(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_admin_dep),
    _csrf: None = Depends(verify_csrf),
) -> HTMLResponse:
    """HTMX — 현재 저장된 NCP 키로 인증 테스트."""
    from app.ncp.client import NCPAuthError, NCPClient

    store = SettingsStore(db)
    access_key = store.get("ncp.access_key")
    secret_key = store.get("ncp.secret_key")
    service_id = store.get("ncp.service_id")

    if not (access_key and secret_key and service_id):
        return HTMLResponse('<span class="err">✗ NCP 설정이 저장되지 않았습니다.</span>')

    client = NCPClient(access_key=access_key, secret_key=secret_key, service_id=service_id)
    try:
        await client.list_by_request_id("TEST-PROBE-0000")
        return HTMLResponse('<span class="ok">✓ NCP 인증 성공</span>')
    except NotImplementedError:
        return HTMLResponse('<span class="warn">⚠ signature.py 미구현 (stub)</span>')
    except (NCPAuthError,) as exc:
        # #7: 인증 실패는 명확히 에러로 표시
        return HTMLResponse(f'<span class="err">✗ 인증 실패: {exc}</span>')
    except Exception as exc:
        from app.ncp.client import NCPError, NCPForbidden
        if isinstance(exc, (NCPAuthError, NCPForbidden)):
            return HTMLResponse(f'<span class="err">✗ 인증 실패: {exc}</span>')
        # 404 등 → 인증 통과 (requestId 없음)
        return HTMLResponse('<span class="ok">✓ NCP 인증 성공 (requestId 없음 응답)</span>')
    finally:
        await client.aclose()


# ── 발신번호 ─────────────────────────────────────────────────────────────────


@router.get("/callers", response_class=HTMLResponse)
async def callers_list(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_admin_dep),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """발신번호 목록."""
    callers = list(
        db.execute(select(Caller).order_by(Caller.is_default.desc(), Caller.id)).scalars().all()
    )
    try:
        user_roles = json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        user_roles = []

    return templates.TemplateResponse(
        "admin/callers.html",
        {
            "request": request,
            "user": user,
            "user_roles": user_roles,
            "callers": callers,
        },
    )


@router.post("/callers")
async def caller_create(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_admin_dep),
    _csrf: None = Depends(verify_csrf),
    number: str = Form(...),
    label: str = Form(...),
) -> RedirectResponse:
    """발신번호 추가."""
    # 숫자만 추출
    normalized = "".join(c for c in number if c.isdigit())
    if not normalized:
        return RedirectResponse("/admin/callers?error=invalid_number", status_code=303)

    existing = db.execute(
        select(Caller).where(Caller.number == normalized)
    ).scalar_one_or_none()

    if existing:
        return RedirectResponse("/admin/callers?error=duplicate", status_code=303)

    caller = Caller(
        number=normalized,
        label=label,
        active=1,
        is_default=0,
        created_at=_now_iso(),
    )
    db.add(caller)
    db.flush()

    audit.log(
        db,
        actor_sub=user.sub,
        action=audit.CALLER_CREATE,
        target=f"caller:{caller.id}",
        detail={"number": normalized, "label": label},
    )
    db.commit()
    return RedirectResponse("/admin/callers?created=1", status_code=303)


@router.post("/callers/{caller_id}/toggle")
async def caller_toggle(
    caller_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_admin_dep),
    _csrf: None = Depends(verify_csrf),
) -> RedirectResponse:
    """발신번호 활성/비활성 토글."""
    caller = db.get(Caller, caller_id)
    if caller is None:
        raise HTTPException(status_code=404)

    caller.active = 0 if caller.active else 1
    audit.log(
        db,
        actor_sub=user.sub,
        action=audit.CALLER_UPDATE,
        target=f"caller:{caller_id}",
        detail={"active": caller.active},
    )
    db.commit()
    return RedirectResponse("/admin/callers", status_code=303)


@router.post("/callers/{caller_id}/default")
async def caller_set_default(
    caller_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_admin_dep),
    _csrf: None = Depends(verify_csrf),
) -> RedirectResponse:
    """기본 발신번호 지정 — 다른 기본은 자동 해제."""
    caller = db.get(Caller, caller_id)
    if caller is None:
        raise HTTPException(status_code=404)

    # 기존 default 해제
    all_callers = list(db.execute(select(Caller)).scalars().all())
    for c in all_callers:
        c.is_default = 0

    caller.is_default = 1
    audit.log(
        db,
        actor_sub=user.sub,
        action=audit.CALLER_DEFAULT,
        target=f"caller:{caller_id}",
    )
    db.commit()
    return RedirectResponse("/admin/callers", status_code=303)


@router.post("/callers/{caller_id}/delete")
async def caller_delete(
    caller_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_admin_dep),
    _csrf: None = Depends(verify_csrf),
) -> RedirectResponse:
    """발신번호 삭제."""
    caller = db.get(Caller, caller_id)
    if caller is None:
        raise HTTPException(status_code=404)

    audit.log(
        db,
        actor_sub=user.sub,
        action=audit.CALLER_DELETE,
        target=f"caller:{caller_id}",
        detail={"number": caller.number, "label": caller.label},
    )
    db.delete(caller)
    db.commit()
    return RedirectResponse("/admin/callers?deleted=1", status_code=303)


# ── 감사 로그 ─────────────────────────────────────────────────────────────────


@router.get("/audit", response_class=HTMLResponse)
async def audit_log_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_admin_dep),
    _: None = Depends(require_setup_complete),
    page: int = Query(1, ge=1),
) -> HTMLResponse:
    """감사 로그 조회 (페이지네이션 50건)."""
    per_page = 50
    offset = (page - 1) * per_page

    logs = list(
        db.execute(
            select(AuditLog)
            .order_by(AuditLog.created_at.desc())
            .offset(offset)
            .limit(per_page)
        ).scalars().all()
    )

    # #14: COUNT 쿼리로 OOM 방지 (전체 조회 대신)
    total_count = db.execute(
        select(func.count()).select_from(select(AuditLog).subquery())
    ).scalar_one()

    try:
        user_roles = json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        user_roles = []

    return templates.TemplateResponse(
        "admin/audit.html",
        {
            "request": request,
            "user": user,
            "user_roles": user_roles,
            "logs": logs,
            "page": page,
            "per_page": per_page,
            "total_count": total_count,
        },
    )
