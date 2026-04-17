"""관리자 라우트 — 설정, 발신번호, 감사 로그, 시스템 업데이트."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_role, require_setup_complete
from app.db import get_db
from app.models import AuditLog, Caller, User
from app.security.csrf import verify_csrf
from app.security.settings_store import SettingsStore
from app.services import audit
from app.web import templates

_update_log = logging.getLogger("kotify.update")

router = APIRouter(prefix="/admin")

_admin_dep = require_role("admin")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


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
        "msghub.api_key",
        "msghub.api_pwd",
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
        request,
        "admin/settings.html",
        {
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
    msghub_api_key: str = Form(""),
    msghub_api_pwd: str = Form(""),
    msghub_env: str = Form(""),
    msghub_brand_id: str = Form(""),
    msghub_chatbot_id: str = Form(""),
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
    if msghub_env:
        store.set("msghub.env", msghub_env, is_secret=False, updated_by=user.sub)
    if msghub_brand_id:
        store.set("msghub.brand_id", msghub_brand_id, is_secret=False, updated_by=user.sub)
    if msghub_chatbot_id:
        store.set("msghub.chatbot_id", msghub_chatbot_id, is_secret=False, updated_by=user.sub)

    # 시크릿 — 빈 값이면 변경하지 않음
    if keycloak_client_secret:
        store.set("keycloak.client_secret", keycloak_client_secret, is_secret=True, updated_by=user.sub)
    if msghub_api_key:
        store.set("msghub.api_key", msghub_api_key, is_secret=True, updated_by=user.sub)
    if msghub_api_pwd:
        store.set("msghub.api_pwd", msghub_api_pwd, is_secret=True, updated_by=user.sub)
    if session_secret:
        store.set("session.secret", session_secret, is_secret=True, updated_by=user.sub)

    audit.log(db, actor_sub=user.sub, action=audit.SETTINGS_UPDATE)
    db.commit()

    # msghub 설정 변경 시 클라이언트 재초기화
    from app.main import reset_msghub_client
    reset_msghub_client()

    return RedirectResponse("/admin/settings?saved=1", status_code=303)


@router.post("/settings/test-msghub", response_class=HTMLResponse)
async def test_msghub(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_admin_dep),
    _csrf: None = Depends(verify_csrf),
) -> HTMLResponse:
    """HTMX — 현재 저장된 msghub 키로 인증 테스트."""
    from app.msghub.auth import AuthError
    from app.msghub.client import MsghubClient

    store = SettingsStore(db)
    api_key = store.get("msghub.api_key")
    api_pwd = store.get("msghub.api_pwd")
    env = store.get("msghub.env") or "production"

    if not (api_key and api_pwd):
        return HTMLResponse('<span class="err">✗ msghub 설정이 저장되지 않았습니다.</span>')

    client = MsghubClient(env=env, api_key=api_key, api_pwd=api_pwd)
    try:
        await client.test_auth()
        return HTMLResponse('<span class="ok">✓ msghub 인증 성공</span>')
    except AuthError as exc:
        return HTMLResponse(f'<span class="err">✗ 인증 실패: {exc}</span>')
    except Exception as exc:
        return HTMLResponse(f'<span class="err">✗ 연결 실패: {exc}</span>')
    finally:
        await client.aclose()


# ── 발신번호 ─────────────────────────────────────────────────────────────────


@router.get("/callers", response_class=HTMLResponse)
async def callers_list(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("viewer", "sender", "admin")),
    _: None = Depends(require_setup_complete),
    per_page: int = Query(50),
) -> HTMLResponse:
    """발신번호 목록. H7 per_page 지원."""
    # H7: clamp
    per_page = max(1, min(per_page, 200))
    callers = list(
        db.execute(select(Caller).order_by(Caller.is_default.desc(), Caller.id)).scalars().all()
    )
    try:
        user_roles = json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        user_roles = []

    return templates.TemplateResponse(
        request,
        "admin/callers.html",
        {
            "user": user,
            "user_roles": user_roles,
            "callers": callers,
            "per_page": per_page,
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
    rcs_enabled: str = Form(""),
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
        rcs_enabled=1 if rcs_enabled == "on" else 0,
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
    """발신번호 삭제. H8: 활성 번호는 삭제 불가."""
    caller = db.get(Caller, caller_id)
    if caller is None:
        raise HTTPException(status_code=404)

    # H8: 활성 번호는 삭제 불가 — 먼저 비활성화 후 삭제
    if caller.active:
        return RedirectResponse("/admin/callers?error=active_cannot_delete", status_code=303)

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
    per_page: int = Query(50),
    sort: str = Query("created_at"),
    order: str = Query("desc"),
    action_filter: str = Query(""),
    actor_filter: str = Query(""),
    date_from: str = Query(""),
    date_to: str = Query(""),
) -> HTMLResponse:
    """감사 로그 조회 (페이지네이션, M7 필터, M8 email join, H7 per_page)."""
    # H7: per_page clamp
    per_page = max(1, min(per_page, 200))
    offset = (page - 1) * per_page

    # H5: 정렬
    sort_expr = AuditLog.created_at.desc() if order != "asc" else AuditLog.created_at.asc()

    # M8: User join으로 email 가져오기
    from sqlalchemy import and_

    stmt = (
        select(AuditLog, User.email.label("actor_email"))
        .outerjoin(User, User.sub == AuditLog.actor_sub)
    )

    # M7: 필터 적용
    filters = []
    if action_filter:
        filters.append(AuditLog.action == action_filter)
    if actor_filter:
        pattern = f"%{actor_filter}%"
        filters.append(
            (AuditLog.actor_sub.like(pattern)) | (User.email.like(pattern))
        )
    if date_from:
        filters.append(AuditLog.created_at >= date_from)
    if date_to:
        filters.append(AuditLog.created_at <= date_to + "T23:59:59.999999+00:00")
    if filters:
        stmt = stmt.where(and_(*filters))

    stmt = stmt.order_by(sort_expr)

    # COUNT
    count_stmt = select(func.count()).select_from(
        select(AuditLog)
        .outerjoin(User, User.sub == AuditLog.actor_sub)
        .where(and_(*filters) if filters else True)
        .subquery()
    )
    total_count = db.execute(count_stmt).scalar_one()

    rows = db.execute(stmt.offset(offset).limit(per_page)).all()

    # AuditLog 객체에 actor_email 속성 주입
    class _LogWithEmail:
        def __init__(self, log: AuditLog, email: str | None) -> None:
            self._log = log
            self.actor_email = email

        def __getattr__(self, name: str):  # type: ignore[override]
            return getattr(self._log, name)

    logs = [_LogWithEmail(row[0], row[1]) for row in rows]

    # M7: 감사 로그에 존재하는 action 목록
    audit_actions = list(
        db.execute(
            select(AuditLog.action).distinct().order_by(AuditLog.action)
        ).scalars().all()
    )

    try:
        user_roles = json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        user_roles = []

    return templates.TemplateResponse(
        request,
        "admin/audit.html",
        {
            "user": user,
            "user_roles": user_roles,
            "logs": logs,
            "page": page,
            "per_page": per_page,
            "total_count": total_count,
            "sort": sort,
            "order": order,
            "action_filter": action_filter,
            "actor_filter": actor_filter,
            "date_from": date_from,
            "date_to": date_to,
            "audit_actions": audit_actions,
        },
    )


# ── 시스템 업데이트 ─────────────────────────────────────────────────────────────


_UPDATE_SCRIPT = "/opt/kotify/deploy/kotify-update.sh"


async def _run_update_script(action: str) -> tuple[int, str, str]:
    """업데이트 스크립트를 subprocess로 실행한다.

    asyncio.create_subprocess_exec를 사용하여 셸을 거치지 않으므로
    command injection 위험이 없다.
    """
    proc = await asyncio.create_subprocess_exec(
        "sudo", _UPDATE_SCRIPT, action,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    return proc.returncode or 0, stdout.decode(), stderr.decode()


@router.post("/system/check-update", response_class=HTMLResponse)
async def check_update(
    request: Request,
    user: User = Depends(_admin_dep),
    _csrf: None = Depends(verify_csrf),
) -> HTMLResponse:
    """HTMX — git fetch 후 업데이트 가능 여부를 표시한다."""
    try:
        rc, stdout, stderr = await _run_update_script("check")
    except asyncio.TimeoutError:
        return HTMLResponse('<span class="err">시간 초과. 서버 네트워크를 확인하세요.</span>')
    except FileNotFoundError:
        return HTMLResponse('<span class="err">업데이트 스크립트를 찾을 수 없습니다.</span>')

    if rc != 0:
        _update_log.warning("check-update failed: rc=%d stderr=%s", rc, stderr)
        return HTMLResponse(f'<span class="err">확인 실패: {stderr[:200]}</span>')

    try:
        data = json.loads(stdout.strip().split("\n")[-1])
    except (json.JSONDecodeError, IndexError):
        return HTMLResponse('<span class="err">응답 파싱 실패</span>')

    if not data.get("update_available"):
        return HTMLResponse(
            f'<span class="ok">\u2713 최신 버전입니다 ({data.get("current", "?")})</span>'
        )

    commits = data.get("commits", [])
    count = data.get("count", len(commits))
    html_parts = [
        f'<div style="margin-bottom:8px"><strong class="warn">\u2b06 {count}건의 업데이트가 있습니다</strong>'
        f' <span class="text-muted">({data.get("current", "?")} \u2192 {data.get("remote", "?")})</span></div>',
        '<div style="max-height:160px;overflow-y:auto;font-size:11px;font-family:monospace;'
        'background:var(--bg-elevated);padding:8px;border-radius:var(--radius);border:1px solid var(--border);margin-bottom:8px">',
    ]
    for c in commits[:15]:
        html_parts.append(
            f'<div><span class="text-muted">{c.get("hash", "")}</span> {c.get("message", "")}</div>'
        )
    if count > 15:
        html_parts.append(f'<div class="text-muted">... 외 {count - 15}건</div>')
    html_parts.append("</div>")
    html_parts.append(
        '<button class="btn btn-primary btn-sm" '
        'hx-post="/admin/system/apply-update" '
        'hx-target="#update-result" '
        'hx-swap="innerHTML" '
        'hx-confirm="업데이트를 설치하시겠습니까? 서비스가 잠시 재시작됩니다.">'
        '<i data-lucide="download"></i> 업데이트 설치'
        '<span class="htmx-indicator spinner"></span>'
        '</button>'
    )
    return HTMLResponse("".join(html_parts))


@router.post("/system/apply-update", response_class=HTMLResponse)
async def apply_update(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_admin_dep),
    _csrf: None = Depends(verify_csrf),
) -> HTMLResponse:
    """HTMX — 업데이트 적용 (git pull + pip install + restart)."""
    audit.log(db, actor_sub=user.sub, action="system.update")
    db.commit()

    try:
        rc, stdout, stderr = await _run_update_script("apply")
    except asyncio.TimeoutError:
        return HTMLResponse('<span class="err">업데이트 시간 초과 (2분). 수동 확인 필요.</span>')
    except FileNotFoundError:
        return HTMLResponse('<span class="err">업데이트 스크립트를 찾을 수 없습니다.</span>')

    if rc != 0:
        _update_log.error("apply-update failed: rc=%d stderr=%s", rc, stderr)
        return HTMLResponse(f'<span class="err">업데이트 실패: {stderr[:300]}</span>')

    lines = stdout.strip().split("\n")
    try:
        result = json.loads(lines[-1])
        version = result.get("version", "?")
    except (json.JSONDecodeError, IndexError):
        version = "?"

    return HTMLResponse(
        f'<span class="ok">✓ 업데이트 완료 ({version}). 서비스가 재시작됩니다...</span>'
        '<script>setTimeout(function(){location.reload()}, 5000)</script>'
    )
