"""캠페인 API 라우트 — S2 Compose 발송 / S3 이력 / S4 상세.

실 DB (campaigns + messages) 기반. POST /campaigns 는 services.compose.
dispatch_campaign() 호출로 실 msghub 발송.

api-contract.md §S3/S4 계약 준수 — web/types/campaign.ts 의 Campaign /
CampaignDetail shape 반환.
"""
from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import (
    SEND_ROLES,
    require_sender,
    require_setup_complete,
    require_user,
    user_has_role,
)
from app.db import get_db
from app.models import Attachment, Campaign, Message, MsghubRequest, User
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import MsghubBadRequest, MsghubError
from app.security.csrf import verify_csrf
from app.services import audit
from app.services.image import ImageProcessingError, preprocess_mms_image
from app.services.report import _refresh_campaign_counters
from app.util.csv_safe import safe_csv_cell as _safe_csv_cell

if TYPE_CHECKING:
    from sqlalchemy.sql import ColumnElement

    from app.msghub.client import MsghubClient

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
#   | 'cancelled'
_RECIPIENT_STATUS = {
    "REG": "queued",
    "ING": "queued",
    "PENDING": "queued",
    "FB_PENDING": "fallback_sms",
    "DONE": "delivered",  # SUCCESS_CODE 인지는 별도 분기
    "FAILED": "failed",
    "CANCELED": "cancelled",  # 예약 취소 — 발송되지 않음 (cancel_campaign)
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
    recipients: list[str] = Field(..., min_length=1, max_length=1000)
    message: str = Field(..., min_length=1)
    sendAt: str | None = None
    # 전송 방식 선택: "rcs"(RCS 우선+fallback) | "sms"(일반 SMS/LMS/MMS 직접).
    # 기본값 없음 — 클라이언트가 명시해야 한다(침묵의 기본값 방지). 하위 유형
    # (단문/장문/이미지)은 서버가 content·첨부로 자동 분류한다.
    sendChannel: str
    # MMS 첨부 — POST /campaigns/attachments 업로드 후 돌려받은 attachmentId.
    attachmentId: int | None = Field(default=None, ge=1)

    @field_validator("sender", "message")
    @classmethod
    def _strip_non_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("비어 있을 수 없습니다")
        return stripped

    @field_validator("sendChannel")
    @classmethod
    def _valid_channel(cls, v: str) -> str:
        if v not in ("rcs", "sms"):
            raise ValueError("sendChannel 은 'rcs' 또는 'sms' 여야 합니다")
        return v


# ── S3: GET /campaigns ───────────────────────────────────────────────────────


@router.get("/campaigns")
def list_campaigns(
    q: str | None = None,
    status: str | None = None,
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
    data["canCancelReservation"] = _has_reservation_rows(db, campaign)
    if campaign.reserve_time:
        uncertain = db.scalar(select(func.count()).select_from(Message).where(
            Message.campaign_id == campaign.id,
            _uncertain_failure_condition(),
        )) or 0
        if uncertain:
            data["failureReason"] = (
                f"{uncertain}명은 예약 접수 여부를 확인하지 못했습니다. "
                "예약이 남아 발송될 수 있으니 msghub 웹 콘솔에서 확인하고 취소해 주세요."
            )
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


def _campaign_create_response(campaign: Campaign) -> JSONResponse:
    """캠페인 생성/멱등 재요청의 공통 응답 형태."""
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


@router.post(
    "/campaigns",
    dependencies=[Depends(require_sender), Depends(verify_csrf)],
)
async def create_campaign(
    body: CampaignCreateBody,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> JSONResponse:
    """새 캠페인 생성 + msghub 발송.

    services.compose.dispatch_campaign() 를 호출해 실제 RCS/SMS/LMS/MMS 발송.
    sendAt 이 있으면 예약 발송 (KST 기준).

    멱등성(C1): Idempotency-Key 헤더로 중복 발송을 차단한다. 같은 (created_by, key)
    캠페인이 이미 있으면 재발송 없이 기존 결과를 반환하고, 동시 요청은
    Campaign.idempotency_key UNIQUE 제약이 INSERT(발송 전) 시점에 차단한다.
    """
    # 순환 import 방지: 함수 내부 import
    from app.main import get_msghub_client
    from app.services.compose import dispatch_campaign

    idem_key = request.headers.get("Idempotency-Key") or None

    # 빠른 경로: 같은 키로 이미 생성된 캠페인이 있으면 재발송 없이 반환.
    if idem_key:
        existing = db.execute(
            select(Campaign).where(
                Campaign.created_by == user.sub,
                Campaign.idempotency_key == idem_key,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return _campaign_create_response(existing)

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
            idempotency_key=idem_key,
            send_channel=body.sendChannel,
        )
    except IntegrityError:
        # 동시 요청 race: 다른 요청이 같은 키로 먼저 INSERT(발송 전 차단됨).
        # 기존 캠페인을 조회해 멱등 응답으로 반환한다.
        db.rollback()
        if idem_key:
            existing = db.execute(
                select(Campaign).where(
                    Campaign.created_by == user.sub,
                    Campaign.idempotency_key == idem_key,
                )
            ).scalar_one_or_none()
            if existing is not None:
                return _campaign_create_response(existing)
        raise HTTPException(
            status_code=409,
            detail={"code": "duplicate_request", "message": "중복 요청으로 처리되었습니다"},
        ) from None
    except ValueError as exc:
        # ValueError 는 사용자 입력 검증 오류로 메시지를 그대로 노출해도 안전.
        raise HTTPException(
            status_code=422,
            detail={"code": "validation_failed", "message": str(exc)},
        ) from exc
    except Exception as exc:
        # 내부 예외는 서버 로그에만 기록, 응답엔 일반화 메시지.
        import logging
        logging.getLogger(__name__).exception("dispatch_campaign failed")
        raise HTTPException(
            status_code=500,
            detail={"code": "dispatch_failed", "message": "발송 처리 중 오류가 발생했습니다"},
        ) from exc

    return _campaign_create_response(campaign)


# ── POST /campaigns/{id}/cancel — 예약 발송 취소 ─────────────────────────────

def _uncertain_failure_condition() -> ColumnElement[bool]:
    """조회 불가 표시는 요청 거부 증거가 아니다. 코드 없는 기존 실패도 접수 여부가 불확실하다."""
    return and_(
        Message.status == "FAILED",
        or_(Message.result_code.is_(None), Message.result_code.in_(("INVALID_KEY", "OVER_DATE"))),
    )


def _has_reservation_rows(
    db: Session, campaign: Campaign, statuses: tuple[str, ...] = ("PENDING",)
) -> bool:
    """캠페인 결과와 별개로 예약 접수된 수신자가 남았는지 확인한다.

    일부 요청 실패는 PARTIAL_FAILED 지만 정상 접수된 청크는 여전히 예약이다. 예약 메타데이터와
    요청 ID 를 함께 확인해 즉시 발송 실패를 예약으로 취급하지 않는다. RESERVED 는 이전 데이터와
    접수 도중의 표현을 유지하며, 레거시 캠페인 ID 는 기존 콘솔 취소 안내로 연결한다.
    """
    if campaign.state == "RESERVE_CANCELED":
        return False
    if not campaign.reserve_time and campaign.state != "RESERVED":
        return False
    return db.execute(
        select(Message.id)
        .join(MsghubRequest, Message.msghub_request_id == MsghubRequest.id)
        .where(
            Message.campaign_id == campaign.id,
            Message.status.in_(statuses),
            or_(MsghubRequest.web_req_id.is_not(None), bool(campaign.web_req_id)),
        )
        .limit(1)
    ).first() is not None

# 예약 취소를 처리하고 있는 캠페인 id — 단일 uvicorn 워커 전제(compose._dispatching 과 같음).
_cancelling: set[int] = set()


def _partial_cancel_message(
    total: int, canceled: int, live: int, *, rejected: bool, failed: bool
) -> str:
    """일부 청크만 취소됐을 때의 안내 — 취소되지 않은 수신자는 예정대로 발송될 수 있다."""
    if rejected and failed:
        reason = "취소가 거부됐거나(이미 발송이 시작됐을 수 있음) 오류로 취소하지 못해"
    elif rejected:
        reason = "취소가 거부되어(이미 발송이 시작됐을 수 있음)"
    elif failed:
        reason = "오류로 취소하지 못해"
    else:
        reason = "취소할 수 없는 상태라"
    message = (
        f"{total}명 중 {canceled}명의 예약을 취소했습니다. "
        f"{live}명은 {reason} 예정대로 발송될 수 있습니다."
    )
    if failed:
        message += " 다시 시도하면 남은 예약만 취소합니다."
    return message


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
    """예약 접수된 청크를 취소한다. 일부 요청 실패 캠페인도 남은 예약을 취소한다.

    권한: sender/admin/owner. viewer/operator 는 403.
    상태: RESERVED 또는 예약 메타데이터·청크 ID 가 있는 대기/취소 행을 허용한다.
      취소 행은 앞선 시도가 메시지만 커밋하고 종료된 경우 최종 상태를 복구하기 위한 것이다.
    청크: msghub 는 예약 요청(수신자 10명 청크)마다 webReqId 를 따로 주고 취소도 그 단위라,
      대기(PENDING) 행이 남은 청크마다 취소를 요청한다. 받아들여진 청크의 PENDING 행만
      CANCELED 로 바꾸고, 거부·실패한 청크는 PENDING 그대로 둔다(발송 여부는 리포트가 확정, H6).
    결과: 발송될 수 있는 행이 남지 않으면 RESERVE_CANCELED. 일부만 취소되면 200 으로
      요약을 알린다 — 다시 누르면 남은 청크만 요청한다. 응답을 잃은 실패 행은 접수 여부를
      알 수 없으므로 전체 취소로 단정하지 않고 콘솔 확인을 안내한다. 하나도 취소하지 못하면
      거부 409 / 오류 502.
    레거시: 청크별 webReqId(alembic 0018) 이전의 여러 청크 예약은 마지막 청크 ID 만 남아
      전체를 취소할 수 없어 409 로 msghub 콘솔 취소를 안내한다.
    동시성: 예약 접수(청크 발송)나 다른 취소가 진행 중인 캠페인은 409 로 기다리게 한다.
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
    if not user_has_role(user, *SEND_ROLES):
        return JSONResponse(
            {"error": {"code": "forbidden", "message": "예약 취소 권한이 없습니다"}},
            status_code=403,
        )
    if campaign.state != "RESERVED" and not _has_reservation_rows(
        db, campaign, ("PENDING", "CANCELED")
    ):
        return JSONResponse(
            {"error": {
                "code": "not_reserved",
                "message": (
                    f"예약 상태가 아니므로 취소할 수 없습니다 (현재: {campaign.state})"
                ),
            }},
            status_code=400,
        )

    from app.services.compose import is_dispatching

    if is_dispatching(campaign.id):
        # 캠페인은 첫 청크 전에 RESERVED 로 보인다. 접수 도중에 취소하면 이미 접수된 청크만 보고
        # 전체 취소로 마무리해, 뒤이어 접수되는 청크가 예약 시각에 발송된다.
        return JSONResponse(
            {"error": {
                "code": "dispatch_in_progress",
                "message": "예약 접수가 아직 진행 중입니다. 잠시 후 다시 취소해 주세요.",
            }},
            status_code=409,
        )

    has_chunk_ids = db.execute(
        select(MsghubRequest.id)
        .where(
            MsghubRequest.campaign_id == campaign.id,
            MsghubRequest.web_req_id.is_not(None),
        )
        .limit(1)
    ).first() is not None
    if not has_chunk_ids:
        if campaign.web_req_id:
            # 0018 이전 발송 — 청크마다 캠페인 값을 덮어써 마지막 청크 ID 만 남았다(10명 이하
            # 단일 청크는 0018 이 청크로 옮겨 여기 오지 않는다). 그 청크만 취소하고 캠페인을
            # 취소로 보이게 하면 앞 청크가 예약 시각에 발송되므로 앱에서는 취소하지 않는다.
            return JSONResponse(
                {"error": {
                    "code": "legacy_reservation",
                    "message": (
                        "이전 버전에서 예약한 11명 이상 캠페인은 앱에서 전체 취소할 수 "
                        "없습니다. msghub 웹 콘솔에서 취소해 주세요."
                    ),
                }},
                status_code=409,
            )
        return JSONResponse(
            {"error": {"code": "no_reservation_id", "message": "예약 ID 가 없습니다"}},
            status_code=400,
        )

    # msghub client 는 app.main 의 싱글톤 — 순환 import 방지 위해 함수 내부 import.
    from app.main import get_msghub_client

    msghub_client = get_msghub_client()
    if msghub_client is None:
        return JSONResponse(
            {"error": {
                "code": "msghub_unavailable",
                "message": "msghub 설정이 완료되지 않았습니다",
            }},
            status_code=503,
        )

    if campaign.id in _cancelling:
        # 청크가 많으면 오래 걸려 프록시 시간 제한을 넘기면 브라우저엔 오류로 보이고 다시 누르게
        # 된다. 두 취소가 같은 청크를 번갈아 요청하면 상대가 취소한 청크를 거부로 받아 "발송될 수
        # 있습니다" 로 잘못 안내하므로 먼저 시작한 취소에 맡긴다.
        return JSONResponse(
            {"error": {
                "code": "cancel_in_progress",
                "message": "예약 취소를 처리하고 있습니다. 잠시 후 새로고침해 확인해 주세요.",
            }},
            status_code=409,
        )
    _cancelling.add(campaign.id)
    try:
        return await _cancel_reservation_chunks(db, msghub_client, campaign, user)
    finally:
        _cancelling.discard(campaign.id)


async def _cancel_reservation_chunks(
    db: Session, msghub_client: MsghubClient, campaign: Campaign, user: User
) -> dict | JSONResponse:
    """대기 행이 남은 청크마다 예약을 취소하고 결과를 캠페인 상태·응답으로 정리한다."""
    # 대기 행이 남은 청크만 — 앞선 시도에서 취소됐거나 발송이 시작된 청크는 다시 요청하지 않는다.
    targets = db.execute(
        select(MsghubRequest.id, MsghubRequest.web_req_id)
        .join(Message, Message.msghub_request_id == MsghubRequest.id)
        .where(
            MsghubRequest.campaign_id == campaign.id,
            MsghubRequest.web_req_id.is_not(None),
            Message.status == "PENDING",
        )
        .group_by(MsghubRequest.id, MsghubRequest.web_req_id, MsghubRequest.chunk_index)
        .order_by(MsghubRequest.chunk_index)
    ).all()

    cancelled: list[str] = []
    rejected: list[str] = []
    error: Exception | None = None
    for request_id, web_req_id in targets:
        try:
            await msghub_client.cancel_reservation(web_req_id, reason="사용자 취소")
        except MsghubBadRequest:
            # 이 청크만 거부 — 이미 발송이 시작됐거나 취소된 상태일 수 있어 단정할 수 없다.
            rejected.append(web_req_id)
            continue
        except Exception as exc:
            # 인증·CPS·서버·네트워크 오류는 뒤 청크에서도 되풀이되기 쉬워 멈춘다. 남은 청크는
            # 다시 시도할 때 요청한다.
            import logging
            logging.getLogger(__name__).warning(
                "예약 취소 요청 실패: campaign=%s webReqId=%s", campaign.id, web_req_id,
                exc_info=True,
            )
            error = exc
            break
        # 받아들여진 청크의 대기 행만 취소로. 곧바로 커밋해 뒤에서 멈추거나 죽어도 msghub 가
        # 이미 취소한 청크가 대기로 남아 다시 요청되지 않게 한다.
        db.execute(
            update(Message)
            .where(Message.msghub_request_id == request_id, Message.status == "PENDING")
            .values(status="CANCELED")
        )
        db.commit()
        cancelled.append(web_req_id)

    # FAILED 여도 응답 코드가 없으면 공급자가 접수한 뒤 응답만 유실됐을 수 있다. 명시적인
    # 거부 코드가 있는 실패만 발송 불가능으로 센다. 기존 코드 없는 실패도 보수적으로 남긴다.
    uncertain_failure = _uncertain_failure_condition()
    definitively_not_sent = or_(
        Message.status == "CANCELED",
        and_(Message.status == "FAILED", ~uncertain_failure),
    )
    canceled_rows, live_rows, uncertain_rows = db.execute(
        select(
            func.coalesce(func.sum(case((Message.status == "CANCELED", 1), else_=0)), 0),
            func.coalesce(
                func.sum(case((~definitively_not_sent, 1), else_=0)), 0
            ),
            func.coalesce(func.sum(case((uncertain_failure, 1), else_=0)), 0),
        ).where(Message.campaign_id == campaign.id)
    ).one()

    if canceled_rows and not live_rows:
        # 발송될 수 있는 행이 없다. 앞선 시도가 마지막 청크까지 커밋하고 상태를 바꾸기 전에
        # 멈췄던 캠페인도 여기서 마무리된다.
        campaign.state = "RESERVE_CANCELED"
        msg = "예약이 취소되었습니다"
    elif not cancelled:
        # 이번 요청에서 바뀐 것이 없다.
        if error is not None:
            reason = str(error) if isinstance(error, MsghubError) else "msghub 통신 오류"
            return JSONResponse(
                {"error": {"code": "cancel_failed", "message": f"예약 취소 실패: {reason}"}},
                status_code=502,
            )
        if rejected:
            # 로컬을 RESERVE_CANCELED 로 바꾸면 발송된 캠페인을 "취소됨"으로 오표기하므로
            # (H6) 상태를 유지하고 거부를 알린다. 발송 여부는 이후 리포트로 확정한다.
            return JSONResponse(
                {"error": {
                    "code": "cancel_rejected",
                    "message": (
                        "예약 취소가 거부되었습니다. 이미 발송되었거나 취소된 상태일 수 "
                        "있으니 발송 결과를 확인해 주세요."
                    ),
                }},
                status_code=409,
            )
        if uncertain_rows:
            return JSONResponse(
                {"error": {
                    "code": "unconfirmed_reservation",
                    "message": (
                        f"{uncertain_rows}명은 예약 접수 여부를 확인하지 못했습니다. "
                        "예약이 남아 발송될 수 있으니 msghub 웹 콘솔에서 확인하고 취소해 주세요."
                    ),
                }},
                status_code=409,
            )
        return JSONResponse(
            {"error": {
                "code": "nothing_to_cancel",
                "message": (
                    "취소할 수 있는 예약이 남아 있지 않습니다. 이미 발송이 시작됐을 수 "
                    "있으니 발송 결과를 확인해 주세요."
                ),
            }},
            status_code=409,
        )
    else:
        # 일부만 취소 — 명시적으로 취소된 청크와 남은 수신자 수를 안내한다.
        msg = _partial_cancel_message(
            campaign.total_count, canceled_rows, live_rows,
            rejected=bool(rejected), failed=error is not None,
        )
        if uncertain_rows:
            msg += (
                f" 이 중 {uncertain_rows}명은 예약 접수 여부를 확인하지 못했습니다. "
                "msghub 웹 콘솔에서 확인하고 취소해 주세요."
            )

    completed_at = campaign.completed_at
    _refresh_campaign_counters(db, campaign.id)
    if uncertain_rows:
        # FAILED 는 요청 응답을 못 받은 로컬 기록이다. 예약 취소로 접수 여부까지 확정할 수
        # 없으므로 전체 실패/취소로 마무리하지 않는다. 상세에는 콘솔 확인 안내가 계속 남는다.
        campaign.state = "RESERVED"
        campaign.completed_at = completed_at
    audit.log(
        db,
        actor_sub=user.sub,
        action="CANCEL_RESERVE",
        target=f"campaign:{campaign.id}",
        detail={
            "cancelled": cancelled,
            "rejected": rejected,
            "error": str(error) if error is not None else None,
        },
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
    status: str | None = None,  # fail 등 필터 (Message.status 또는 파생)
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
    if not user_has_role(user, *SEND_ROLES):
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
