"""대화방 서비스 — MT(발송) + MO(수신)을 스레드 단위로 머지.

스레드 키: (caller_number, phone) = (mo_callback, mo_number)
답장: 기존 dispatch_campaign 재사용 (단건 캠페인 생성).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Campaign, Message, MoMessage, User
from app.msghub.codes import (
    CHAT_SESSION_CAP_KRW,
    CHAT_SESSION_MAX_UNITS,
    CHAT_SESSION_WINDOW_HOURS,
    chat_session_cost,
)
from app.services.compose import dispatch_campaign, validate_message

if TYPE_CHECKING:
    from app.msghub.client import MsghubClient


@dataclass
class ChatMessage:
    """대화방 한 개의 메시지(발신 또는 수신)."""

    direction: str                    # "OUT" (우리→고객) 또는 "IN" (고객→우리)
    body: str
    timestamp: str                    # ISO 문자열 (정렬 및 표시용)
    status: str | None = None         # OUT 전용
    channel: str | None = None        # OUT 전용: RCS/SMS/LMS/MMS
    cost: int | None = None           # OUT 전용: 원
    telco: str | None = None          # IN 전용
    product_code: str | None = None   # IN 전용 (MORCS/SMSMO 등)
    mo_id: int | None = None
    campaign_id: int | None = None
    msg_id: int | None = None


@dataclass
class ChatThread:
    """대화방 목록 한 건."""

    caller: str
    phone: str
    last_timestamp: str
    last_body: str
    last_direction: str
    unanswered: bool
    mo_count: int
    mt_count: int


def _coalesce_ts(*values: str | None) -> str:
    """None이 아닌 첫 번째 문자열 반환. 전부 None이면 빈 문자열."""
    for v in values:
        if v:
            return v
    return ""


def list_threads(
    db: Session, limit: int = 50, offset: int = 0
) -> tuple[list[ChatThread], int]:
    """대화방 목록을 최근 활동순으로 반환한다."""
    # MT 측 — campaigns.caller_number + messages.to_number로 그룹
    mt_rows = db.execute(
        select(
            Campaign.caller_number.label("caller"),
            Message.to_number.label("phone"),
            func.max(
                func.coalesce(Message.complete_time, Message.report_dt)
            ).label("last_t"),
            func.count().label("cnt"),
        )
        .join(Campaign, Campaign.id == Message.campaign_id)
        .group_by(Campaign.caller_number, Message.to_number)
    ).all()

    # MO 측 — mo_callback + mo_number로 그룹
    mo_rows = db.execute(
        select(
            MoMessage.mo_callback.label("caller"),
            MoMessage.mo_number.label("phone"),
            func.max(
                func.coalesce(MoMessage.mo_recv_dt, MoMessage.received_at)
            ).label("last_t"),
            func.count().label("cnt"),
        )
        .where(MoMessage.mo_callback.is_not(None))
        .group_by(MoMessage.mo_callback, MoMessage.mo_number)
    ).all()

    # Python에서 (caller, phone) 키로 머지
    threads: dict[tuple[str, str], dict] = {}
    for r in mt_rows:
        if not r.caller or not r.phone:
            continue
        key = (r.caller, r.phone)
        threads[key] = {
            "caller": r.caller,
            "phone": r.phone,
            "mt_last_t": r.last_t or "",
            "mt_count": r.cnt,
            "mo_last_t": "",
            "mo_count": 0,
        }
    for r in mo_rows:
        if not r.caller or not r.phone:
            continue
        key = (r.caller, r.phone)
        t = threads.setdefault(
            key,
            {
                "caller": r.caller,
                "phone": r.phone,
                "mt_last_t": "",
                "mt_count": 0,
                "mo_last_t": "",
                "mo_count": 0,
            },
        )
        t["mo_last_t"] = r.last_t or ""
        t["mo_count"] = r.cnt

    # 마지막 메시지 상세를 가져와 ChatThread로 빌드
    built: list[ChatThread] = []
    for (caller, phone), t in threads.items():
        last_mt_t = t["mt_last_t"]
        last_mo_t = t["mo_last_t"]
        if last_mo_t > last_mt_t:
            last_t = last_mo_t
            last_dir = "IN"
            mo = db.execute(
                select(MoMessage.mo_msg)
                .where(
                    MoMessage.mo_callback == caller,
                    MoMessage.mo_number == phone,
                )
                .order_by(
                    func.coalesce(MoMessage.mo_recv_dt, MoMessage.received_at).desc()
                )
                .limit(1)
            ).scalar_one_or_none()
            last_body = mo or ""
        else:
            last_t = last_mt_t
            last_dir = "OUT"
            last_body_row = db.execute(
                select(Campaign.content)
                .join(Message, Message.campaign_id == Campaign.id)
                .where(
                    Campaign.caller_number == caller,
                    Message.to_number == phone,
                )
                .order_by(
                    func.coalesce(Message.complete_time, Message.report_dt).desc()
                )
                .limit(1)
            ).scalar_one_or_none()
            last_body = last_body_row or ""

        # 미답 = 마지막 메시지가 IN(고객 답장)인 경우
        unanswered = last_dir == "IN" and bool(last_mo_t)

        built.append(
            ChatThread(
                caller=caller,
                phone=phone,
                last_timestamp=last_t,
                last_body=last_body,
                last_direction=last_dir,
                unanswered=unanswered,
                mo_count=t["mo_count"],
                mt_count=t["mt_count"],
            )
        )

    built.sort(key=lambda t: t.last_timestamp, reverse=True)
    total = len(built)
    return built[offset : offset + limit], total


def get_thread(db: Session, caller: str, phone: str) -> list[ChatMessage]:
    """특정 (caller, phone) 스레드의 모든 메시지를 시간 오름차순으로 반환한다."""
    out: list[ChatMessage] = []

    # MT
    mt_rows = db.execute(
        select(Message, Campaign)
        .join(Campaign, Campaign.id == Message.campaign_id)
        .where(
            Campaign.caller_number == caller,
            Message.to_number == phone,
        )
    ).all()
    for msg, campaign in mt_rows:
        ts = _coalesce_ts(msg.complete_time, msg.report_dt, campaign.created_at)
        out.append(
            ChatMessage(
                direction="OUT",
                body=campaign.content or "",
                timestamp=ts,
                status=msg.status,
                channel=msg.channel,
                cost=msg.cost,
                campaign_id=campaign.id,
                msg_id=msg.id,
            )
        )

    # MO
    mo_rows = db.execute(
        select(MoMessage).where(
            MoMessage.mo_callback == caller,
            MoMessage.mo_number == phone,
        )
    ).scalars().all()
    for mo in mo_rows:
        ts = _coalesce_ts(mo.mo_recv_dt, mo.received_at)
        out.append(
            ChatMessage(
                direction="IN",
                body=mo.mo_msg or "",
                timestamp=ts,
                telco=mo.telco,
                product_code=mo.product_code,
                mo_id=mo.id,
            )
        )

    out.sort(key=lambda m: m.timestamp)
    return out


def chat_session_summary(messages: list[ChatMessage]) -> dict:
    """대화방의 최근 24h 세션 과금 요약.

    RCS 양방향(CHAT)은 (챗봇, 고객) 쌍의 24시간 세션당 최대 80원(10건) 상한.
    Message.cost는 건당 8원으로 저장되지만 실 청구는 세션 단위로 capped된다.

    Returns:
        {
          "recent_out_count": 최근 24h 내 OUT 건수,
          "session_billed": 세션 상한 적용한 실 청구액(원),
          "session_raw": 상한 미적용 시 원래 합계(원),
          "capped": True면 상한에 도달해 축소됨,
          "cap_krw": 80,
          "max_units": 10,
        }
    """
    now = datetime.now(UTC)
    window_start = now - timedelta(hours=CHAT_SESSION_WINDOW_HOURS)

    out_count = 0
    raw_total = 0
    for m in messages:
        if m.direction != "OUT":
            continue
        try:
            ts = datetime.fromisoformat(m.timestamp)
        except (ValueError, TypeError):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ts >= window_start:
            out_count += 1
            raw_total += m.cost or 0

    billed = chat_session_cost(out_count)
    return {
        "recent_out_count": out_count,
        "session_billed": billed,
        "session_raw": raw_total,
        "capped": out_count >= CHAT_SESSION_MAX_UNITS,
        "cap_krw": CHAT_SESSION_CAP_KRW,
        "max_units": CHAT_SESSION_MAX_UNITS,
        "window_hours": CHAT_SESSION_WINDOW_HOURS,
    }


def validate_reply_content(content: str) -> dict:
    """답장 본문 검증 — 정책: 엄격(90byte 양방향 CHAT만).

    양방향 CHAT은 90byte 제한이므로 이를 넘기면 LMS(단방향)로 강등되어
    고객이 더 이상 답장할 수 없다. 대화 연속성을 위해 엄격 모드로 차단.

    완화하려면 아래 `SMS` 체크를 제거하여 validate_message 결과를 그대로 사용.
    """
    result = validate_message(content)
    if not result["ok"]:
        return result
    if result["message_type"] != "SMS":
        return {
            "ok": False,
            "error": (
                f"답장은 90바이트 이내 단문만 가능합니다 "
                f"(현재 {result['byte_len']}바이트 · 양방향 CHAT 제약)."
            ),
            "byte_len": result["byte_len"],
            "message_type": result["message_type"],
        }
    return result


async def send_reply(
    db: Session,
    msghub_client: MsghubClient,
    user: User,
    caller: str,
    phone: str,
    content: str,
) -> Campaign:
    """답장을 발송한다 — 단건 Campaign 생성 후 기존 dispatch_campaign 호출.

    RCS 양방향 CHAT(8원) 우선, 실패 시 webhook이 SMS fallback(9원) 자동 처리.
    """
    campaign = await dispatch_campaign(
        db=db,
        msghub_client=msghub_client,
        created_by=user.sub,
        caller_number=caller,
        content=content,
        recipients=[phone],
        message_type="SMS",
        subject=None,
    )
    return campaign
