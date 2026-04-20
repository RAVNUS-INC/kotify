"""대화방(RCS 양방향) 라우트 — 인박스 + 스레드 + 답장."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.deps import require_role, require_setup_complete
from app.db import get_db
from app.models import User
from app.security.csrf import verify_csrf
from app.services import chat as chat_service
from app.web import templates

router = APIRouter(prefix="/chat", tags=["chat"])

_sender_dep = require_role("sender", "admin")


def _parse_roles(user: User) -> list[str]:
    try:
        return json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        return []


@router.get("", response_class=HTMLResponse)
async def list_threads(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _: None = Depends(require_setup_complete),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=10, le=200),
) -> HTMLResponse:
    """대화방 인박스 — 스레드 목록."""
    offset = (page - 1) * per_page
    threads, total = chat_service.list_threads(db, per_page, offset)
    total_pages = max(1, (total + per_page - 1) // per_page)
    return templates.TemplateResponse(
        request,
        "chat/list.html",
        {
            "user": user,
            "user_roles": _parse_roles(user),
            "threads": threads,
            "total": total,
            "page": page,
            "per_page": per_page,
            "total_pages": total_pages,
        },
    )


@router.get("/{caller}/{phone}", response_class=HTMLResponse)
async def thread_detail(
    request: Request,
    caller: str,
    phone: str,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """대화 상세 — MT/MO 머지 + 답장 폼."""
    messages = chat_service.get_thread(db, caller, phone)
    if not messages:
        raise HTTPException(status_code=404, detail="대화 내역이 없습니다")
    session = chat_service.chat_session_summary(messages)
    return templates.TemplateResponse(
        request,
        "chat/thread.html",
        {
            "user": user,
            "user_roles": _parse_roles(user),
            "caller": caller,
            "phone": phone,
            "messages": messages,
            "session": session,
        },
    )


@router.post("/{caller}/{phone}/reply", response_model=None)
async def reply(
    request: Request,
    caller: str,
    phone: str,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _: None = Depends(require_setup_complete),
    _csrf: None = Depends(verify_csrf),
    content: str = Form(""),
) -> HTMLResponse | RedirectResponse:
    """답장 전송 — RCS 양방향 CHAT(8원) → 실패 시 webhook이 SMS fallback."""
    content = (content or "").strip()

    def _render_error(error: str) -> HTMLResponse:
        messages = chat_service.get_thread(db, caller, phone)
        session = chat_service.chat_session_summary(messages)
        return templates.TemplateResponse(
            request,
            "chat/thread.html",
            {
                "user": user,
                "user_roles": _parse_roles(user),
                "caller": caller,
                "phone": phone,
                "messages": messages,
                "session": session,
                "error": error,
                "draft": content,
            },
            status_code=422,
        )

    if not content:
        return _render_error("답장 내용을 입력해주세요.")

    result = chat_service.validate_reply_content(content)
    if not result["ok"]:
        return _render_error(result["error"] or "답장 본문이 유효하지 않습니다.")

    from app.main import get_msghub_client  # noqa: PLC0415

    msghub_client = get_msghub_client()
    if msghub_client is None:
        return _render_error("msghub 설정이 완료되지 않았습니다.")

    try:
        await chat_service.send_reply(
            db=db,
            msghub_client=msghub_client,
            user=user,
            caller=caller,
            phone=phone,
            content=content,
        )
    except ValueError as exc:
        return _render_error(str(exc))

    return RedirectResponse(f"/chat/{caller}/{phone}", status_code=303)
