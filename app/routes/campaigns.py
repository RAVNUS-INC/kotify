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

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_complete, require_user
from app.db import get_db
from app.models import Campaign, Message, User
from app.msghub.codes import SUCCESS_CODE
from app.security.csrf import verify_csrf

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
