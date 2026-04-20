"""관리자 라우트 — 설정, 발신번호, 감사 로그, 시스템 업데이트."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
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
    # 업데이트 UX:
    # 1) apply-update는 git pull + pip install만 동기 실행하고 systemctl restart는
    #    2초 뒤로 schedule (deploy/kotify-update.sh). 응답이 먼저 클라이언트에 도달.
    # 2) 응답 JSON에 target version 포함. 클라이언트는 /healthz를 1초 간격으로
    #    폴링하며 버전이 target과 일치하면 즉시 새로고침.
    # 3) 진행 경과(초 단위)가 UI에 실시간 표시되어 "멍때리는 대기" 대신 피드백.
    # 4) 60초 timeout 시 수동 새로고침 안내.
    html_parts.append(
        "<script>window.kotifyApplyUpdate=async function(){"
        "if(!confirm('업데이트를 설치하시겠습니까? 서비스가 잠시 재시작됩니다.'))return;"
        "var el=document.getElementById('update-result');"
        "if(!el)return;"
        "el.className='text-muted';"
        "el.textContent='\u23f3 \ud604\uc7ac \ubc84\uc804 \ud655\uc778...';"
        "var prevVersion=null;"
        "try{var r0=await fetch('/healthz',{cache:'no-store'});"
        "if(r0.ok){var j0=await r0.json();prevVersion=j0.version;}}catch(e){}"
        "el.textContent='\u23f3 \uc5c5\ub370\uc774\ud2b8 \ub2e4\uc6b4\ub85c\ub4dc + \uc124\uce58 \uc911...';"
        "var csrf='';var m=document.querySelector('meta[name=\"csrf-token\"]');"
        "if(m)csrf=m.getAttribute('content')||'';"
        "var targetVersion=null;var errMsg=null;"
        "try{var resp=await fetch('/admin/system/apply-update',"
        "{method:'POST',headers:{'X-CSRF-Token':csrf}});"
        "if(resp.ok){var data=await resp.json();targetVersion=data.version;}"
        "else{try{var e2=await resp.json();errMsg=e2.message||('HTTP '+resp.status);}"
        "catch(_){errMsg='HTTP '+resp.status;}}"
        "}catch(e){errMsg=String(e);}"
        "if(errMsg){el.className='err';el.textContent='\u2717 '+errMsg;return;}"
        "el.textContent='\u23f3 \uc11c\ube44\uc2a4 \uc7ac\uc2dc\uc791 \uc911... (0s)';"
        "var elapsed=0;var maxWait=60;"
        "var timer=setInterval(async function(){"
        "elapsed++;"
        "el.textContent='\u23f3 \uc11c\ube44\uc2a4 \uc7ac\uc2dc\uc791 \uc911... ('+elapsed+'s)';"
        "try{var r2=await fetch('/healthz',{cache:'no-store'});"
        "if(r2.ok){var j2=await r2.json();"
        "var done=targetVersion?(j2.version===targetVersion):"
        "(prevVersion&&j2.version&&j2.version!==prevVersion);"
        "if(done){clearInterval(timer);el.className='ok';"
        "el.textContent='\u2713 \uc5c5\ub370\uc774\ud2b8 \uc644\ub8cc ('+j2.version+'). \uc0c8\ub85c\uace0\uce68 \uc911...';"
        "setTimeout(function(){location.reload();},500);return;}}"
        "}catch(e){}"
        "if(elapsed>=maxWait){clearInterval(timer);el.className='err';"
        "el.textContent='\u2717 \uc2dc\uac04 \ucd08\uacfc (60\ucd08). \uc218\ub3d9\uc73c\ub85c \uc0c8\ub85c\uace0\uce68\ud574\uc8fc\uc138\uc694.';}"
        "},1000);};</script>"
    )
    html_parts.append(
        '<button type="button" class="btn btn-primary btn-sm" '
        'onclick="kotifyApplyUpdate()">'
        '<i data-lucide="download"></i> 업데이트 설치'
        '</button>'
    )
    return HTMLResponse("".join(html_parts))


@router.post("/system/apply-update")
async def apply_update(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_admin_dep),
    _csrf: None = Depends(verify_csrf),
) -> JSONResponse:
    """업데이트 적용 — git pull + pip install 즉시 실행, 재시작은 2초 뒤.

    응답에 target version을 담아 보내면 클라이언트가 /healthz를 폴링하며
    버전이 바뀌는 순간을 업데이트 완료로 감지한다.
    """
    audit.log(db, actor_sub=user.sub, action="system.update")
    db.commit()

    try:
        rc, stdout, stderr = await _run_update_script("apply")
    except asyncio.TimeoutError:
        return JSONResponse(
            {"status": "error", "error": "timeout", "message": "업데이트 시간 초과 (2분)"},
            status_code=504,
        )
    except FileNotFoundError:
        return JSONResponse(
            {"status": "error", "error": "script_missing",
             "message": "업데이트 스크립트를 찾을 수 없습니다."},
            status_code=500,
        )

    # stdout에서 "done" phase 먼저 탐색. systemctl restart가 비동기로 스케줄되어
    # 스크립트 exit 직후 uvicorn이 죽을 수도 있어 rc가 비정상으로 돌아올 수
    # 있는데, "done" 찍혔다면 업데이트는 성공한 상태. rc에 앞서 stdout을 신뢰.
    version: str | None = None
    for line in reversed(stdout.strip().split("\n")):
        try:
            result = json.loads(line)
            if result.get("phase") == "done" and result.get("version"):
                version = result["version"]
                break
        except (json.JSONDecodeError, AttributeError):
            continue

    if version:
        return JSONResponse({"status": "ok", "version": version})

    # "done" 못 찾았고 rc도 비정상이면 실제 실패
    if rc != 0:
        _update_log.error("apply-update failed: rc=%d stderr=%s", rc, stderr)
        return JSONResponse(
            {"status": "error", "error": "script_failed",
             "message": f"업데이트 실패: {stderr[:300]}"},
            status_code=500,
        )

    # rc=0인데 phase=done이 없는 경우 — 구버전 스크립트이거나 출력 이상.
    # 업데이트는 일단 반영된 것으로 가정하고 ok 반환 (client가 /healthz로 검증).
    return JSONResponse({"status": "ok", "version": "?"})


# ── 통계 대조 ──────────────────────────────────────────────────────────────────


@router.get("/system/msghub-stats", response_model=None)
async def msghub_daily_stats(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_admin_dep),
    ymd: str = Query(..., description="조회 일자 (YYYYMMDD)"),
    project_id: str = Query(..., description="msghub 프로젝트 ID"),
) -> JSONResponse:
    """msghub 서버측 일자별 발송 통계 조회 + 우리 DB 집계와 비교.

    관리자가 과금/누락 감사용으로 호출. 우리 DB는 webhook 기반이라
    이론상 msghub 통계와 일치해야 하며, 차이가 나면 webhook 유실 등의
    신호로 활용한다.
    """
    from app.main import get_msghub_client  # noqa: PLC0415
    from app.models import Campaign, Message  # noqa: PLC0415

    client = get_msghub_client()
    if client is None:
        return JSONResponse(
            {"error": "msghub 설정이 완료되지 않았습니다"}, status_code=503,
        )

    # 1) msghub 통계 조회
    try:
        msghub_stats = await client.get_daily_stats(ymd, project_id)
    except Exception as exc:
        return JSONResponse(
            {"error": f"msghub 통계 조회 실패: {exc}"}, status_code=502,
        )

    # 2) 우리 DB 집계 (UTC ISO 접두 기준 발송일)
    from sqlalchemy import case

    ymd_iso = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"
    rows = db.execute(
        select(
            Message.channel,
            func.count().label("total"),
            func.sum(
                case((Message.result_code == "10000", 1), else_=0)
            ).label("succ"),
        )
        .join(Campaign, Campaign.id == Message.campaign_id)
        .where(Campaign.created_at.like(f"{ymd_iso}%"))
        .group_by(Message.channel)
    ).all()
    local_counts: dict[str, dict] = {}
    for r in rows:
        ch = r.channel or "UNKNOWN"
        total = int(r.total or 0)
        succ = int(r.succ or 0)
        local_counts[ch] = {"total": total, "succ": succ, "fail": total - succ}

    return JSONResponse({
        "ymd": ymd,
        "project_id": project_id,
        "msghub": msghub_stats,
        "local_db": local_counts,
    })
