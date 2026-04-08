"""발송 작성 라우트."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_role, require_setup_complete
from app.db import get_db
from app.models import Caller, User
from app.security.csrf import verify_csrf
from app.services import audit
from app.services.compose import (
    MAX_RECIPIENTS_PER_CAMPAIGN,
    resolve_recipients,
    validate_message,
)
from app.web import templates

router = APIRouter()

_sender_dep = require_role("sender", "admin")


def _parse_roles(user: User) -> list[str]:
    try:
        return json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        return []


def _get_compose_context(
    db: Session,
    user: User,
    group_id: int = 0,
    error_slug: str | None = None,
    content: str = "",
    recipients_text: str = "",
    preserved_caller_id: int | None = None,
) -> dict:
    """compose.html에 필요한 공통 컨텍스트를 구성한다."""
    callers = list(
        db.execute(
            select(Caller).where(Caller.active == 1).order_by(Caller.is_default.desc())
        ).scalars().all()
    )
    # 보존된 발신번호 또는 기본 발신번호
    if preserved_caller_id:
        default_caller = next((c for c in callers if c.id == preserved_caller_id), None)
    else:
        default_caller = next((c for c in callers if c.is_default), callers[0] if callers else None)

    from app.services.contacts import list_contacts
    from app.services.groups import get_group_size, list_groups
    groups_raw, _ = list_groups(db, per_page=500)
    groups = [
        {"id": g.id, "name": g.name, "member_count": get_group_size(db, g.id)}
        for g in groups_raw
    ]
    contacts, _ = list_contacts(db, per_page=1000)

    return {
        "user": user,
        "user_roles": _parse_roles(user),
        "callers": callers,
        "default_caller": default_caller,
        "preview": None,
        "groups": groups,
        "contacts": contacts,
        "preselect_group_id": group_id,
        "error_slug": error_slug,
        "content": content,
        "recipients_text": recipients_text,
        "preserved_caller_id": preserved_caller_id,
    }


@router.get("/compose", response_class=HTMLResponse)
async def compose_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _: None = Depends(require_setup_complete),
    group_id: int = Query(0),
) -> HTMLResponse:
    """발송 작성 화면."""
    return templates.TemplateResponse(
        request,
        "compose.html",
        _get_compose_context(db, user, group_id=group_id),
    )


@router.post("/compose/preview", response_class=HTMLResponse)
async def compose_preview(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _csrf: None = Depends(verify_csrf),
    caller_id: int = Form(...),
    content: str = Form(...),
    recipients_text: str = Form(""),
    source: str = Form("manual"),
) -> HTMLResponse:
    """HTMX — 미리보기 (번호 검증 + byte 길이 + SMS/LMS 판정)."""
    # form에서 다중 값 추출
    form_data = await request.form()
    raw_group_ids = form_data.getlist("group_ids")
    raw_contact_ids = form_data.getlist("contact_ids")
    group_ids = [int(v) for v in raw_group_ids if v]
    contact_ids = [int(v) for v in raw_contact_ids if v]

    valid_numbers, invalid_numbers, _ = resolve_recipients(
        db, source, recipients_text, group_ids, contact_ids
    )
    phone_error = None

    # 메시지 검증
    msg_result = validate_message(content)

    # 1,000명 초과 시 can_send=False (C4)
    too_many = len(valid_numbers) > MAX_RECIPIENTS_PER_CAMPAIGN

    context = {
        "valid_count": len(valid_numbers),
        "invalid_numbers": invalid_numbers,
        "phone_error": phone_error,
        "byte_len": msg_result["byte_len"],
        "message_type": msg_result["message_type"],
        "msg_ok": msg_result["ok"],
        "msg_error": msg_result["error"],
        "too_many": too_many,
        "max_recipients": MAX_RECIPIENTS_PER_CAMPAIGN,
        "can_send": (
            phone_error is None
            and not invalid_numbers
            and msg_result["ok"]
            and len(valid_numbers) > 0
            and not too_many
        ),
    }
    return templates.TemplateResponse(request, "_compose_preview.html", context)


@router.post("/compose/send", response_model=None)
async def compose_send(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _: None = Depends(require_setup_complete),
    _csrf: None = Depends(verify_csrf),
    caller_id: int = Form(...),
    content: str = Form(...),
    recipients_text: str = Form(""),
    source: str = Form("manual"),
) -> HTMLResponse | RedirectResponse:
    """실제 발송 처리. 검증 실패 시 form 보존하여 재렌더링 (#I9)."""
    from app.services.compose import dispatch_campaign

    # form에서 다중 값 추출
    form_data = await request.form()
    raw_group_ids = form_data.getlist("group_ids")
    raw_contact_ids = form_data.getlist("contact_ids")
    group_ids = [int(v) for v in raw_group_ids if v]
    contact_ids = [int(v) for v in raw_contact_ids if v]

    def _render_error(slug: str) -> HTMLResponse:
        """검증 실패 시 입력 보존하여 compose.html 재렌더링."""
        ctx = _get_compose_context(
            db,
            user,
            error_slug=slug,
            content=content,
            recipients_text=recipients_text,
            preserved_caller_id=caller_id,
        )
        return templates.TemplateResponse(
            request,
            "compose.html",
            ctx,
            status_code=422,
        )

    # 발신번호 확인
    caller = db.get(Caller, caller_id)
    if caller is None or not caller.active:
        audit.log(
            db,
            actor_sub=user.sub,
            action=audit.SEND,
            target=None,
            detail={"rejected": True, "reason": "invalid_caller"},
        )
        db.commit()
        return _render_error("invalid_caller")

    # 수신자 해석
    valid_numbers, invalid_numbers, marking_ids = resolve_recipients(
        db, source, recipients_text, group_ids, contact_ids
    )

    if invalid_numbers:
        audit.log(
            db,
            actor_sub=user.sub,
            action=audit.SEND,
            target=None,
            detail={"rejected": True, "reason": "invalid_numbers", "count": len(invalid_numbers)},
        )
        db.commit()
        return _render_error("invalid_numbers")

    if not valid_numbers:
        return _render_error("no_recipients")

    # 1,000명 초과 사전 차단 (C4)
    if len(valid_numbers) > MAX_RECIPIENTS_PER_CAMPAIGN:
        audit.log(
            db,
            actor_sub=user.sub,
            action=audit.SEND,
            target=None,
            detail={"rejected": True, "reason": "too_many_recipients", "count": len(valid_numbers)},
        )
        db.commit()
        return _render_error("too_many_recipients")

    # 메시지 검증
    msg_result = validate_message(content)
    if not msg_result["ok"]:
        return _render_error("invalid_message")

    # 싱글턴 NCP 클라이언트 사용 — circular import 방지를 위해 함수 안에서 import
    from app.main import get_ncp_client  # noqa: PLC0415
    ncp_client = get_ncp_client()
    if ncp_client is None:
        return _render_error("ncp_not_configured")

    try:
        campaign = await dispatch_campaign(
            db=db,
            ncp_client=ncp_client,
            created_by=user.sub,
            caller_number=caller.number,
            content=content,
            recipients=valid_numbers,
            message_type=msg_result["message_type"],
        )

        # 연락처 last_sent_at 업데이트
        if marking_ids:
            from app.services.contacts import bulk_mark_sent
            bulk_mark_sent(db, marking_ids, channel="sms")
            db.commit()

        return RedirectResponse(f"/campaigns/{campaign.id}", status_code=303)
    except ValueError as exc:
        return _render_error(str(exc))
