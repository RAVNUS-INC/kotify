"""발송 작성 라우트."""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_role, require_setup_complete
from app.db import get_db
from app.models import Attachment, Caller, User
from app.security.csrf import verify_csrf
from app.services import audit
from app.services.compose import (
    MAX_RECIPIENTS_PER_CAMPAIGN,
    resolve_recipients,
    validate_message,
)
from app.services.image import (
    MMS_MAX_BYTES,
    ImageProcessingError,
    preprocess_mms_image,
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
    subject: str = "",
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
        "subject": subject,
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
    resend_campaign: int = Query(0),
) -> HTMLResponse:
    """발송 작성 화면. resend_campaign이 있으면 실패 수신자 + 본문 prefill."""
    # C2: 재발송 prefill — 실패 수신자 번호 + 본문 자동 채우기
    prefill_recipients = ""
    prefill_content = ""
    if resend_campaign:
        from sqlalchemy import select as sa_select  # noqa: PLC0415

        from app.models import Campaign, Message  # noqa: PLC0415
        orig = db.get(Campaign, resend_campaign)
        if orig and (_is_sender_or_admin(user) or orig.created_by == user.sub):
            prefill_content = orig.content or ""
            fail_msgs = list(
                db.execute(
                    sa_select(Message).where(
                        Message.campaign_id == resend_campaign,
                        Message.result_status == "fail",
                    )
                ).scalars().all()
            )
            prefill_recipients = "\n".join(msg.to_number_raw for msg in fail_msgs)

    return templates.TemplateResponse(
        request,
        "compose.html",
        _get_compose_context(
            db, user, group_id=group_id,
            content=prefill_content,
            recipients_text=prefill_recipients,
        ),
    )


def _is_sender_or_admin(user: User) -> bool:
    try:
        roles = set(json.loads(user.roles))
        return bool(roles & {"sender", "admin"})
    except (json.JSONDecodeError, TypeError):
        return False


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
    subject: str = Form(""),
    recipients_text: str = Form(""),
    source: str = Form("manual"),
    reserve_enabled: str = Form(""),           # "on" 이면 예약 모드
    reserve_time: str = Form(""),              # datetime-local: "YYYY-MM-DDTHH:mm"
    reserve_timezone: str = Form("Asia/Seoul"),
    attachment_id: int = Form(0),              # 0 이면 첨부 없음
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
            subject=subject,
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

    # 첨부가 있으면 MMS 로 강제 — content type 자동 판정 결과를 덮어쓴다.
    if attachment_id:
        msg_result["message_type"] = "MMS"

    from app.main import get_msghub_client  # noqa: PLC0415
    msghub_client = get_msghub_client()
    if msghub_client is None:
        return _render_error("ncp_not_configured")

    # subject는 LMS/MMS 일 때만 의미 있음 (SMS는 제목 미지원)
    final_subject = subject.strip() if msg_result["message_type"] in ("LMS", "MMS") else None

    # 예약 발송 파라미터 처리.
    is_reserved = reserve_enabled == "on" and bool(reserve_time.strip())
    reserve_time_arg: str | None = reserve_time.strip() if is_reserved else None

    try:
        campaign = await dispatch_campaign(
            db=db,
            msghub_client=msghub_client,
            created_by=user.sub,
            caller_number=caller.number,
            content=content,
            recipients=valid_numbers,
            message_type=msg_result["message_type"],
            subject=final_subject,
            reserve_time_local=reserve_time_arg,
            attachment_id=attachment_id or None,
        )

        # 연락처 last_sent_at 업데이트
        if marking_ids:
            from app.services.contacts import bulk_mark_sent
            bulk_mark_sent(db, marking_ids, channel="sms")
            db.commit()

        return RedirectResponse(f"/campaigns/{campaign.id}", status_code=303)
    except ValueError as exc:
        return _render_error(str(exc))


# 업로드 가능한 최대 원본 파일 크기 (전처리 전).
# 너무 크면 메모리/CPU 낭비라서 컷. 전처리 후 MMS 제약(300KB)에 자동으로 맞춰진다.
MAX_RAW_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB


@router.post("/compose/upload-attachment")
async def compose_upload_attachment(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _: None = Depends(require_setup_complete),
    _csrf: None = Depends(verify_csrf),
    file: UploadFile = File(...),
) -> JSONResponse:
    """MMS 첨부 이미지 업로드 (multipart/form-data).

    파이프라인:
    1. 원본 파일 읽기 (최대 10MB)
    2. preprocess_mms_image() — Pillow로 MMS 제약에 맞게 변환
    3. msghub upload_file() — 파일 사전등록, fileId 수신
    4. attachments 테이블에 BLOB + 메타 저장
    5. JSON 응답 — UI 가 attachment_id 를 form hidden 으로 보존
    """
    # 1. 원본 읽기 + 크기 체크
    raw = await file.read()
    if not raw:
        return JSONResponse({"error": "빈 파일입니다."}, status_code=400)
    if len(raw) > MAX_RAW_UPLOAD_BYTES:
        return JSONResponse(
            {"error": f"원본 파일이 너무 큽니다 (최대 {MAX_RAW_UPLOAD_BYTES // (1024 * 1024)}MB)."},
            status_code=400,
        )

    # 2. 전처리
    try:
        processed, width, height = preprocess_mms_image(raw)
    except ImageProcessingError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    # 3. msghub 업로드 (RCS + MMS 양쪽)
    from app.main import get_msghub_client  # noqa: PLC0415
    from app.msghub.schemas import MsghubError  # noqa: PLC0415

    msghub_client = get_msghub_client()
    if msghub_client is None:
        return JSONResponse(
            {"error": "msghub 설정이 완료되지 않았습니다."}, status_code=503
        )

    file_id = uuid.uuid4().hex
    stored_filename = f"{file_id}.jpg"
    try:
        # MMS fallback용 업로드 (300KB JPEG)
        upload_resp = await msghub_client.upload_file(
            channel="mms",
            file_id=f"mms-{file_id}",
            file_bytes=processed,
            content_type="image/jpeg",
        )
    except MsghubError as exc:
        return JSONResponse(
            {"error": f"msghub 업로드 실패: {exc}"}, status_code=502
        )

    # 4. DB 저장
    now = datetime.now(UTC).isoformat()
    attachment = Attachment(
        campaign_id=None,  # compose_send 시점에 연결됨
        msghub_file_id=upload_resp.file_id,
        original_filename=file.filename or stored_filename,
        stored_filename=stored_filename,
        content_blob=processed,
        file_size_bytes=len(processed),
        width=width,
        height=height,
        uploaded_by=user.sub,
        uploaded_at=now,
        file_expires_at=upload_resp.file_exp_dt or None,
        channel="mms",
    )
    db.add(attachment)
    db.commit()

    return JSONResponse(
        {
            "attachment_id": attachment.id,
            "width": width,
            "height": height,
            "file_size_bytes": len(processed),
            "original_filename": attachment.original_filename,
        }
    )
