"""캠페인 API 라우트 — S2 Compose 발송 / S3 이력 / S4 상세.

실 DB (campaigns + messages) 기반. POST /campaigns 는 services.compose.
dispatch_campaign() 호출로 실 msghub 발송.

api-contract.md §S3/S4 계약 준수 — web/types/campaign.ts 의 Campaign /
CampaignDetail shape 반환.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import List, Optional
from zoneinfo import ZoneInfo

import csv
import io
import json
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_complete, require_user
from app.db import get_db
from app.models import Attachment, Campaign, Message, User
from app.msghub.codes import SUCCESS_CODE
from app.security.csrf import verify_csrf
from app.services import audit
from app.services.image import ImageProcessingError, preprocess_mms_image
from app.util.csv_safe import safe_csv_cell as _safe_csv_cell

# MMS 원본 업로드 상한 (전처리 전). 프론트가 초과분을 차단해도 서버가
# 최종 방어선. 10 MiB.
_MAX_RAW_UPLOAD_BYTES = 10 * 1024 * 1024

router = APIRouter(
    dependencies=[Depends(require_user), Depends(require_setup_complete)],
)

KST = ZoneInfo("Asia/Seoul")


# ── Campaign.state → CampaignStatus 매핑 ─────────────────────────────────────
# web/types/campaign.ts: 'draft' | 'scheduled' | 'sending' | 'sent' | 'failed' | 'cancelled'
_STATUS_MAP = {
    "DRAFT": "draft",
    "DISPATCHING": "sending",
    "DISPATCHED": "sent",
    "COMPLETED": "sent",
    "PARTIAL_FAILED": "sent",  # UX 측면: 일부 성공이면 sent, 내부 breakdown 으로 실패분 노출
    "FAILED": "failed",
    "RESERVED": "scheduled",
    "RESERVE_FAILED": "failed",
    "RESERVE_CANCELED": "cancelled",
}

# Message/result 상태 → RecipientStatus 매핑
# web/types/campaign.ts: 'queued' | 'delivered' | 'read' | 'replied' | 'failed' | 'fallback_sms'
_RECIPIENT_STATUS = {
    "REG": "queued",
    "ING": "queued",
    "PENDING": "queued",
    "FB_PENDING": "fallback_sms",
    "DONE": "delivered",  # SUCCESS_CODE 인지는 별도 분기
    "FAILED": "failed",
}


def _fmt_kst(iso_utc: str | None) -> str:
    """UTC ISO → 'YYYY-MM-DD HH:MM' KST. 실패 시 빈 문자열."""
    if not iso_utc:
        return ""
    try:
        dt = datetime.fromisoformat(iso_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return ""


def _campaign_name(c: Campaign) -> str:
    """목록 표시용 이름. subject > content 앞 24자 > '캠페인 #{id}'."""
    if c.subject:
        return c.subject
    if c.content:
        first = c.content.strip().split("\n", 1)[0]
        return first[:24] + ("…" if len(first) > 24 else "")
    return f"캠페인 #{c.id}"


def _campaign_channel(c: Campaign) -> str:
    """실제 사용된 채널. rcs_count>0 → rcs, 아니면 message_type 파생."""
    if c.rcs_count and c.rcs_count > 0:
        return "rcs"
    if c.message_type == "short":
        return "sms"
    if c.message_type == "long":
        return "lms"
    if c.message_type == "image":
        return "mms"
    return "sms"


def _campaign_to_dict(c: Campaign) -> dict:
    """Campaign ORM → Next.js Campaign shape."""
    status = _STATUS_MAP.get(c.state, "sending")
    reach: int | None = c.ok_count if status in ("sent", "failed") else None
    replies: int | None = None  # MO 는 thread 단위라 캠페인별 매핑 필요 — 추후.
    # reserve_time 은 services/compose.parse_reserve_time 에서 이미 KST
    # "YYYY-MM-DD HH:MM" 포맷으로 저장됨 (UTC 재변환 금지).
    scheduled_at = c.reserve_time if c.reserve_time else None
    row: dict = {
        "id": str(c.id),
        "name": _campaign_name(c),
        "status": status,
        "sender": c.caller_number,
        "channel": _campaign_channel(c),
        "createdAt": _fmt_kst(c.created_at),
        "recipients": c.total_count or 0,
        "reach": reach,
        "replies": replies,
        "cost": c.total_cost or 0,
    }
    if scheduled_at:
        row["scheduledAt"] = scheduled_at
    # 실패 사유: state 가 failed 계열이면 첫 실패 메시지의 result_desc 를 추정.
    # 목록 조회에서 메시지를 별도로 가져오진 않으므로 여기서는 biz 힌트만.
    if status == "failed":
        row["failureReason"] = "발송 실패 — 상세 페이지에서 수신자별 사유 확인"
    return row


def _message_to_recipient(m: Message) -> dict:
    """Message ORM → Next.js Recipient shape."""
    if m.status == "DONE":
        if m.result_code == SUCCESS_CODE:
            # 채널이 fallback(SMS/LMS/MMS)이면 fallback_sms 로 표현 (UX 의미: RCS 에서 떨어짐)
            if m.channel in ("SMS", "LMS", "MMS"):
                rstatus = "fallback_sms"
            else:
                rstatus = "delivered"
        else:
            rstatus = "failed"
    else:
        rstatus = _RECIPIENT_STATUS.get(m.status or "", "queued")

    row: dict = {
        "id": f"m-{m.id}",
        "name": m.to_number_raw or m.to_number,
        "phone": m.to_number,
        "status": rstatus,
    }
    sent_at = _fmt_kst(m.complete_time or m.report_dt)
    if sent_at and rstatus != "queued":
        row["sentAt"] = sent_at
    if rstatus == "failed" and m.result_desc:
        row["failureReason"] = m.result_desc
    return row


class CampaignCreateBody(BaseModel):
    """POST /campaigns 요청 body."""

    sender: str = Field(..., min_length=1)
    recipients: List[str] = Field(..., min_length=1, max_length=1000)
    message: str = Field(..., min_length=1)
    sendAt: Optional[str] = None
    channel: Optional[str] = None  # 참조용, 실제로는 서버가 재분류
    # MMS 첨부 — POST /campaigns/attachments 업로드 후 돌려받은 attachmentId.
    attachmentId: Optional[int] = Field(default=None, ge=1)

    @field_validator("sender", "message")
    @classmethod
    def _strip_non_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("비어 있을 수 없습니다")
        return stripped


# ── S3: GET /campaigns ───────────────────────────────────────────────────────


@router.get("/campaigns")
def list_campaigns(
    q: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
) -> dict:
    """캠페인 목록 — 최신순, q / status 필터."""
    stmt = select(Campaign)

    if status and status != "all":
        # 역매핑: CampaignStatus → Campaign.state 후보들
        state_candidates = [
            state for state, mapped in _STATUS_MAP.items() if mapped == status
        ]
        if state_candidates:
            stmt = stmt.where(Campaign.state.in_(state_candidates))

    if q:
        pat = f"%{q}%"
        stmt = stmt.where(or_(Campaign.subject.ilike(pat), Campaign.content.ilike(pat)))

    # WHERE 뒤에 ORDER BY + LIMIT — 독자 혼동 방지 위해 필터 뒤로 배치.
    stmt = stmt.order_by(Campaign.created_at.desc()).limit(200)

    campaigns = db.execute(stmt).scalars().all()
    rows = [_campaign_to_dict(c) for c in campaigns]
    return {"data": rows, "meta": {"total": len(rows)}}


# ── S4: GET /campaigns/{id} ─────────────────────────────────────────────────


@router.get("/campaigns/{cid}", response_model=None)
def get_campaign(cid: str, db: Session = Depends(get_db)) -> dict | JSONResponse:
    """캠페인 상세 — 기본 정보 + 수신자 샘플 20건 + breakdown."""
    try:
        campaign_id = int(cid)
    except (ValueError, TypeError):
        return JSONResponse(
            {"error": {"code": "not_found", "message": "캠페인을 찾을 수 없습니다"}},
            status_code=404,
        )

    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "캠페인을 찾을 수 없습니다"}},
            status_code=404,
        )

    # 수신자 샘플 20건 (상태 다양성 고려해 id 역순)
    messages = (
        db.execute(
            select(Message)
            .where(Message.campaign_id == campaign.id)
            .order_by(Message.id.desc())
            .limit(20)
        )
        .scalars()
        .all()
    )

    # breakdown — campaign counters 는 이미 services/report 에서 집계됨
    total = campaign.total_count or 0
    rcs_count = campaign.rcs_count or 0
    fallback_count = campaign.fallback_count or 0
    fail_count = campaign.fail_count or 0

    # 기본 응답 = 목록 shape + 추가 필드
    data = _campaign_to_dict(campaign)
    data["recipientsSample"] = [_message_to_recipient(m) for m in messages]
    data["breakdown"] = {
        "total": total,
        "rcsDelivered": rcs_count,
        "smsFallback": fallback_count,
        "failed": fail_count,
        "replies": 0,
    }
    return {"data": data}


# ── S2: POST /campaigns ─────────────────────────────────────────────────────


@router.post("/campaigns", dependencies=[Depends(verify_csrf)])
async def create_campaign(
    body: CampaignCreateBody,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """새 캠페인 생성 + msghub 발송.

    services.compose.dispatch_campaign() 를 호출해 실제 RCS/SMS/LMS/MMS 발송.
    sendAt 이 있으면 예약 발송 (KST 기준).
    """
    # 순환 import 방지: 함수 내부 import
    from app.main import get_msghub_client
    from app.services.compose import dispatch_campaign

    client = get_msghub_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "msghub_unavailable", "message": "msghub 클라이언트 미초기화"},
        )

    try:
        campaign = await dispatch_campaign(
            db=db,
            msghub_client=client,
            created_by=user.sub,
            caller_number=body.sender,
            content=body.message,
            recipients=list(body.recipients),
            message_type="SMS",  # dispatch 내부에서 content 로 재분류
            subject=None,
            reserve_time_local=body.sendAt or None,
            attachment_id=body.attachmentId,
        )
    except ValueError as exc:
        # ValueError 는 사용자 입력 검증 오류로 메시지를 그대로 노출해도 안전.
        raise HTTPException(
            status_code=422,
            detail={"code": "validation_failed", "message": str(exc)},
        )
    except Exception:
        # 내부 예외는 서버 로그에만 기록, 응답엔 일반화 메시지.
        import logging
        logging.getLogger(__name__).exception("dispatch_campaign failed")
        raise HTTPException(
            status_code=500,
            detail={"code": "dispatch_failed", "message": "발송 처리 중 오류가 발생했습니다"},
        )

    return JSONResponse(
        {
            "data": {
                "id": str(campaign.id),
                "status": _STATUS_MAP.get(campaign.state, "sending"),
                "estimate": {
                    "reach": campaign.total_count or 0,
                    "cost": campaign.total_cost or 0,
                    "channel": _campaign_channel(campaign),
                },
            }
        }
    )


# ── POST /campaigns/{id}/cancel — 예약 발송 취소 ─────────────────────────────


def _user_has_role(user: User, *roles: str) -> bool:
    """User.roles(JSON) 파싱 후 주어진 role 중 하나라도 보유하면 True."""
    try:
        parsed = set(json.loads(user.roles))
    except (json.JSONDecodeError, TypeError):
        parsed = set()
    return bool(parsed & set(roles))


@router.post(
    "/campaigns/{cid}/cancel",
    dependencies=[Depends(verify_csrf)],
    response_model=None,
)
async def cancel_campaign(
    cid: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    """예약(`RESERVED`) 상태 캠페인을 취소한다.

    권한: sender/admin/owner. viewer/operator 는 403.
    상태: RESERVED 만 허용. 이미 실행/완료/이미취소는 400.
    """
    try:
        campaign_id = int(cid)
    except (ValueError, TypeError):
        return JSONResponse(
            {"error": {"code": "not_found", "message": "캠페인을 찾을 수 없습니다"}},
            status_code=404,
        )
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "캠페인을 찾을 수 없습니다"}},
            status_code=404,
        )
    if not _user_has_role(user, "sender", "admin", "owner"):
        return JSONResponse(
            {"error": {"code": "forbidden", "message": "예약 취소 권한이 없습니다"}},
            status_code=403,
        )
    if campaign.state != "RESERVED":
        return JSONResponse(
            {"error": {
                "code": "not_reserved",
                "message": (
                    f"예약 상태가 아니므로 취소할 수 없습니다 (현재: {campaign.state})"
                ),
            }},
            status_code=400,
        )
    if not campaign.web_req_id:
        return JSONResponse(
            {"error": {"code": "no_reservation_id", "message": "예약 ID 가 없습니다"}},
            status_code=400,
        )

    # msghub client 는 app.main 의 싱글톤 — 순환 import 방지 위해 함수 내부 import.
    from app.main import get_msghub_client
    from app.msghub.schemas import MsghubBadRequest, MsghubError

    msghub_client = get_msghub_client()
    if msghub_client is None:
        return JSONResponse(
            {"error": {
                "code": "msghub_unavailable",
                "message": "msghub 설정이 완료되지 않았습니다",
            }},
            status_code=503,
        )

    try:
        await msghub_client.cancel_reservation(
            campaign.web_req_id, reason="사용자 취소"
        )
        campaign.state = "RESERVE_CANCELED"
        msg = "예약이 취소되었습니다"
    except MsghubBadRequest as exc:
        # 이미 실행됐거나 취소된 경우 — state 는 정리해두되 경고 메시지.
        campaign.state = "RESERVE_CANCELED"
        msg = f"예약이 이미 처리되었습니다: {exc}"
    except MsghubError as exc:
        db.rollback()
        return JSONResponse(
            {"error": {
                "code": "cancel_failed",
                "message": f"예약 취소 실패: {exc}",
            }},
            status_code=502,
        )

    audit.log(
        db,
        actor_sub=user.sub,
        action="CANCEL_RESERVE",
        target=f"campaign:{campaign.id}",
        detail={"web_req_id": campaign.web_req_id},
    )
    db.commit()
    return {
        "data": {
            "id": str(campaign.id),
            "status": _STATUS_MAP.get(campaign.state, "cancelled"),
            "message": msg,
        }
    }


# ── GET /campaigns/{id}/export.csv — 수신자 CSV 다운로드 ─────────────────────


@router.get("/campaigns/{cid}/export.csv")
def export_campaign_csv(
    cid: str,
    status: Optional[str] = None,  # fail 등 필터 (Message.status 또는 파생)
    db: Session = Depends(get_db),
) -> Response:
    """캠페인의 수신자별 결과를 CSV 로. UTF-8 BOM + formula-safe."""
    try:
        campaign_id = int(cid)
    except (ValueError, TypeError):
        return Response(
            content='{"error":{"code":"not_found","message":"캠페인을 찾을 수 없습니다"}}',
            status_code=404,
            media_type="application/json",
        )
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        return Response(
            content='{"error":{"code":"not_found","message":"캠페인을 찾을 수 없습니다"}}',
            status_code=404,
            media_type="application/json",
        )

    stmt = select(Message).where(Message.campaign_id == campaign_id)
    # 필터: fail = result_code != SUCCESS_CODE (DONE 상태) 또는 status=FAILED
    if status == "fail":
        stmt = stmt.where(
            or_(
                Message.status == "FAILED",
                and_(Message.status == "DONE", Message.result_code != SUCCESS_CODE),
            )
        )
    elif status == "ok":
        stmt = stmt.where(
            and_(Message.status == "DONE", Message.result_code == SUCCESS_CODE)
        )
    stmt = stmt.order_by(Message.id.asc())
    rows = db.execute(stmt).scalars().all()

    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow([
        "수신번호", "상태", "채널", "결과코드", "결과설명", "비용", "완료시각",
    ])
    for m in rows:
        writer.writerow([
            _safe_csv_cell(m.to_number_raw or m.to_number or ""),
            _safe_csv_cell(m.status or ""),
            _safe_csv_cell(m.channel or ""),
            _safe_csv_cell(m.result_code or ""),
            _safe_csv_cell(m.result_desc or ""),
            str(m.cost or 0),
            _safe_csv_cell(m.complete_time or m.report_dt or ""),
        ])

    subject_safe = (campaign.subject or f"campaign-{campaign.id}")[:40]
    # 파일명은 간단한 ascii 로 — RFC 5987 encoded 파일명 브라우저 호환 부담 회피.
    filename = f"kotify-campaign-{campaign.id}.csv"
    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Campaign-Subject": subject_safe.encode("ascii", "replace").decode(),
        },
    )


# ── MMS 첨부 업로드 + 서빙 ──────────────────────────────────────────────────


@router.post(
    "/campaigns/attachments",
    dependencies=[Depends(verify_csrf)],
    response_model=None,
)
async def upload_attachment(
    file: UploadFile = File(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    """MMS 첨부 이미지 업로드 — sender/admin 전용.

    파이프라인:
      1) 원본 읽기 (≤10 MiB)
      2) preprocess_mms_image() — JPEG 300KB/1920x1080 변환
      3) msghub upload_file(channel='mms') — fileId 발급
      4) attachments 테이블에 BLOB + 메타 저장
      5) 응답: {attachmentId, width, height, sizeBytes, originalFilename, url}
    """
    if not _user_has_role(user, "sender", "admin", "owner"):
        return JSONResponse(
            {"error": {"code": "forbidden", "message": "첨부 업로드 권한이 없습니다"}},
            status_code=403,
        )

    raw = await file.read()
    if not raw:
        return JSONResponse(
            {"error": {"code": "empty_file", "message": "빈 파일입니다"}},
            status_code=400,
        )
    if len(raw) > _MAX_RAW_UPLOAD_BYTES:
        limit_mb = _MAX_RAW_UPLOAD_BYTES // (1024 * 1024)
        return JSONResponse(
            {"error": {
                "code": "file_too_large",
                "message": f"원본이 너무 큽니다 (최대 {limit_mb}MB)",
            }},
            status_code=413,
        )

    try:
        processed, width, height = preprocess_mms_image(raw)
    except ImageProcessingError as exc:
        return JSONResponse(
            {"error": {"code": "image_error", "message": str(exc)}},
            status_code=400,
        )

    # msghub 싱글톤 — 순환 import 방지 위해 함수 내부 import.
    from app.main import get_msghub_client
    from app.msghub.schemas import MsghubError

    msghub_client = get_msghub_client()
    if msghub_client is None:
        return JSONResponse(
            {"error": {
                "code": "msghub_unavailable",
                "message": "msghub 설정이 완료되지 않았습니다",
            }},
            status_code=503,
        )

    file_id = uuid.uuid4().hex
    stored_filename = f"{file_id}.jpg"
    try:
        upload_resp = await msghub_client.upload_file(
            channel="mms",
            file_id=f"mms-{file_id}",
            file_bytes=processed,
            content_type="image/jpeg",
        )
    except MsghubError as exc:
        return JSONResponse(
            {"error": {"code": "upload_failed", "message": f"msghub 업로드 실패: {exc}"}},
            status_code=502,
        )

    from datetime import UTC as _UTC
    now_iso = datetime.now(_UTC).isoformat()
    attachment = Attachment(
        campaign_id=None,  # 발송 시점에 연결됨
        msghub_file_id=getattr(upload_resp, "file_id", None),
        original_filename=file.filename or stored_filename,
        stored_filename=stored_filename,
        content_blob=processed,
        file_size_bytes=len(processed),
        width=width,
        height=height,
        uploaded_by=user.sub,
        uploaded_at=now_iso,
        file_expires_at=getattr(upload_resp, "file_exp_dt", None),
        channel="mms",
    )
    db.add(attachment)
    db.flush()
    audit.log(
        db,
        actor_sub=user.sub,
        action="CAMPAIGN_ATTACHMENT_UPLOAD",
        target=f"attachment:{attachment.id}",
        detail={"size": len(processed), "width": width, "height": height},
    )
    db.commit()

    return {
        "data": {
            "attachmentId": attachment.id,
            "width": width,
            "height": height,
            "sizeBytes": len(processed),
            "originalFilename": attachment.original_filename,
            "url": f"/api/campaigns/attachments/{attachment.id}",
        }
    }


@router.get("/campaigns/attachments/{aid}")
def serve_attachment(aid: str, db: Session = Depends(get_db)) -> Response:
    """첨부 이미지 바이트 스트림 — 프리뷰 <img> 용.

    권한: 라우터 레벨 require_user 로 로그인된 사용자만. 공개 URL 아님.
    """
    try:
        att_id = int(aid)
    except (ValueError, TypeError):
        return Response(status_code=404)
    att = db.get(Attachment, att_id)
    if att is None:
        return Response(status_code=404)
    return Response(
        content=att.content_blob,
        media_type="image/jpeg",
        headers={
            # 이 URL 은 사용자별이 아니므로 public 이라고 봐도 무방하지만 세션
            # 쿠키 뒤라 사실상 인증된 사용자에게만 노출. 5분 캐시.
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": f'inline; filename="{att.original_filename}"',
        },
    )
