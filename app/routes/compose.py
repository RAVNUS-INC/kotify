"""발송 작성 라우트."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_role, require_setup_complete
from app.db import get_db
from app.models import Caller, User
from app.security.csrf import verify_csrf
from app.services import audit
from app.services.compose import MAX_RECIPIENTS_PER_CAMPAIGN, validate_message, validate_phone_list
from app.web import templates

router = APIRouter()

_sender_dep = require_role("sender", "admin")


@router.get("/compose", response_class=HTMLResponse)
async def compose_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """발송 작성 화면."""
    callers = list(
        db.execute(
            select(Caller).where(Caller.active == 1).order_by(Caller.is_default.desc())
        ).scalars().all()
    )
    default_caller = next((c for c in callers if c.is_default), callers[0] if callers else None)

    try:
        user_roles = json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        user_roles = []

    return templates.TemplateResponse(
        request,
        "compose.html",
        {
            "user": user,
            "user_roles": user_roles,
            "callers": callers,
            "default_caller": default_caller,
            "preview": None,
        },
    )


@router.post("/compose/preview", response_class=HTMLResponse)
async def compose_preview(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _csrf: None = Depends(verify_csrf),
    caller_id: int = Form(...),
    content: str = Form(...),
    recipients_text: str = Form(...),
) -> HTMLResponse:
    """HTMX — 미리보기 (번호 검증 + byte 길이 + SMS/LMS 판정)."""
    # 번호 검증
    valid_numbers, invalid_numbers = validate_phone_list(recipients_text)
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


@router.post("/compose/send")
async def compose_send(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _: None = Depends(require_setup_complete),
    _csrf: None = Depends(verify_csrf),
    caller_id: int = Form(...),
    content: str = Form(...),
    recipients_text: str = Form(...),
) -> RedirectResponse:
    """실제 발송 처리."""
    from app.services.compose import dispatch_campaign

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
        return RedirectResponse("/compose?error=invalid_caller", status_code=303)

    # 번호 검증
    valid_numbers, invalid_numbers = validate_phone_list(recipients_text)

    if invalid_numbers:
        audit.log(
            db,
            actor_sub=user.sub,
            action=audit.SEND,
            target=None,
            detail={"rejected": True, "reason": "invalid_numbers", "count": len(invalid_numbers)},
        )
        db.commit()
        return RedirectResponse(
            f"/compose?error=invalid_numbers&count={len(invalid_numbers)}",
            status_code=303,
        )
    if not valid_numbers:
        return RedirectResponse("/compose?error=no_recipients", status_code=303)

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
        return RedirectResponse("/compose?error=too_many_recipients", status_code=303)

    # 메시지 검증
    msg_result = validate_message(content)
    if not msg_result["ok"]:
        return RedirectResponse("/compose?error=invalid_message", status_code=303)

    # 싱글턴 NCP 클라이언트 사용 (C3) — circular import 방지를 위해 함수 안에서 import
    from app.main import get_ncp_client  # noqa: PLC0415
    ncp_client = get_ncp_client()
    if ncp_client is None:
        return RedirectResponse("/compose?error=ncp_not_configured", status_code=303)

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
        return RedirectResponse(f"/campaigns/{campaign.id}", status_code=303)
    except ValueError as exc:
        return RedirectResponse(f"/compose?error={exc}", status_code=303)
