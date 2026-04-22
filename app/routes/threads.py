"""스레드(대화방) API 라우트 — S5 인박스, S6 스레드 상세.

실 DB (campaigns + messages + mo_messages) 기반. services.chat.list_threads
/ get_thread 를 재사용해 대화방 UI 와 동일한 머지 로직 유지.

api-contract.md §S5/S6 계약 — web/types/chat.ts 의 ChatThread /
ChatThreadDetail / ChatMessage shape 반환.

thread id 규약: "{caller}:{phone}" (콜론 구분, URL safe).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, tuple_
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_complete, require_user
from app.db import get_db
from app.models import Campaign, Message, User
from app.security.csrf import verify_csrf
from app.services.chat import (
    ChatMessage as ServiceChatMessage,
    ChatThread as ServiceChatThread,
    get_thread,
    list_threads,
)

router = APIRouter(
    dependencies=[Depends(require_user), Depends(require_setup_complete)],
)

KST = ZoneInfo("Asia/Seoul")


# ── 공통 변환 헬퍼 ───────────────────────────────────────────────────────────


def _hhmm(iso_ts: str | None) -> str:
    """UTC ISO → 'HH:MM' KST. 실패 시 빈 문자열."""
    if not iso_ts:
        return ""
    try:
        dt = datetime.fromisoformat(iso_ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(KST).strftime("%H:%M")
    except (ValueError, TypeError):
        return ""


def _channel_from_mt(msg_channel: str | None) -> str:
    """Message.channel('RCS'/'SMS'/'LMS'/'MMS') → ChatChannel('rcs'/'sms'/'kakao')."""
    if not msg_channel:
        return "sms"
    low = msg_channel.lower()
    if low == "rcs":
        return "rcs"
    if low == "kakao":
        return "kakao"
    return "sms"  # SMS/LMS/MMS 모두 sms 버블로 통일


def _thread_id(caller: str, phone: str) -> str:
    """thread id 규약: 콜론으로 caller:phone. 역parse 는 split(':',1)."""
    return f"{caller}:{phone}"


def _parse_thread_id(tid: str) -> tuple[str, str] | None:
    if ":" not in tid:
        return None
    caller, phone = tid.split(":", 1)
    if not caller or not phone:
        return None
    return caller, phone


def _service_thread_to_ts(t: ServiceChatThread, last_channel: str) -> dict:
    """services.chat.ChatThread → web/types/chat.ts ChatThread shape."""
    row: dict = {
        "id": _thread_id(t.caller, t.phone),
        "name": t.phone,  # 연락처 이름 미연결 — 번호로 표시
        "phone": t.phone,
        "preview": (t.last_body or "")[:60],
        "time": _hhmm(t.last_timestamp),
        "channel": last_channel,
    }
    if t.unanswered:
        row["unread"] = True
    return row


def _batch_last_mt_channels(
    db: Session, pairs: set[tuple[str, str]]
) -> dict[tuple[str, str], str]:
    """여러 (caller, phone) 의 최근 MT 채널을 2쿼리로 집계 (N+1 회피).

    1) GROUP BY 로 (caller, phone) 별 max(message.id) 확보
    2) 해당 id 들로 Message.channel 조회 후 dict 반환

    NOTE: `tuple_((col1, col2)).in_(pairs)` 로 정확 매칭. 분해한 `caller IN (...)
    AND phone IN (...)` 는 cross-product 라 유령 쌍 (A,2)(B,1) 까지 스캔/반환
    하므로 금지.
    """
    if not pairs:
        return {}
    pair_list = list(pairs)

    subq = (
        select(
            Campaign.caller_number.label("c"),
            Message.to_number.label("p"),
            func.max(Message.id).label("last_id"),
        )
        .join(Campaign, Campaign.id == Message.campaign_id)
        .where(
            tuple_(Campaign.caller_number, Message.to_number).in_(pair_list)
        )
        .group_by(Campaign.caller_number, Message.to_number)
    ).subquery()

    rows = db.execute(
        select(subq.c.c, subq.c.p, Message.channel).join(
            Message, Message.id == subq.c.last_id
        )
    ).all()
    return {(r.c, r.p): _channel_from_mt(r.channel) for r in rows if r.c and r.p}


def _service_message_to_ts(m: ServiceChatMessage) -> dict:
    """services.chat.ChatMessage → ChatMessage TS shape."""
    side = "us" if m.direction == "OUT" else "them"
    kind = _channel_from_mt(m.channel) if m.direction == "OUT" else "rcs"
    # 수신(IN) 메시지는 RCS 양방향 MO 인 경우가 많아 기본 'rcs'. 향후 product_code
    # 기준 세밀 분기 가능 (예: SMSMO → sms).
    if m.direction == "IN" and m.product_code:
        pc = m.product_code.upper()
        if pc.startswith("SMS") or pc == "SMSMO":
            kind = "sms"
        elif pc.startswith("KAKAO"):
            kind = "kakao"

    id_suffix = f"{m.direction.lower()}-{m.mo_id or m.msg_id or 'x'}"
    return {
        "id": f"m-{id_suffix}",
        "side": side,
        "kind": kind,
        "text": m.body or "",
        "time": _hhmm(m.timestamp),
    }


def _campaign_label(subject: str | None, content: str | None, cid: int) -> str:
    """(subject, content, id) → 표시 라벨. list/detail 공용."""
    if subject:
        return subject
    if content:
        first = content.strip().split("\n", 1)[0]
        return first[:24] + ("…" if len(first) > 24 else "")
    return f"캠페인 #{cid}"


def _batch_last_campaign_labels(
    db: Session, pairs: set[tuple[str, str]]
) -> dict[tuple[str, str], str]:
    """(caller, phone) → 최근 캠페인 라벨 배치 집계 (2쿼리).

    채널과 라벨이 *같은* 최근 메시지에서 파생되도록 `max(Message.id)` 로 앵커.
    max(Campaign.id) 를 쓰면 "가장 최근 캠페인" 과 "가장 최근 전송 이벤트" 가
    불일치할 수 있어 UX 상 채널/라벨이 다른 캠페인을 가리키는 bug 가 발생 가능.
    """
    if not pairs:
        return {}
    pair_list = list(pairs)

    subq = (
        select(
            Campaign.caller_number.label("c"),
            Message.to_number.label("p"),
            func.max(Message.id).label("last_mid"),
        )
        .join(Campaign, Campaign.id == Message.campaign_id)
        .where(
            tuple_(Campaign.caller_number, Message.to_number).in_(pair_list)
        )
        .group_by(Campaign.caller_number, Message.to_number)
    ).subquery()

    # 최근 메시지 → 해당 메시지의 campaign 를 JOIN 으로 따라간다.
    rows = db.execute(
        select(subq.c.c, subq.c.p, Campaign.id, Campaign.subject, Campaign.content)
        .join(Message, Message.id == subq.c.last_mid)
        .join(Campaign, Campaign.id == Message.campaign_id)
    ).all()
    return {
        (r.c, r.p): _campaign_label(r.subject, r.content, r.id)
        for r in rows
        if r.c and r.p
    }


# ── S5: GET /threads ─────────────────────────────────────────────────────────


@router.get("/threads")
def api_list_threads(
    q: Optional[str] = None,
    unread: Optional[bool] = None,
    db: Session = Depends(get_db),
) -> dict:
    """스레드 목록. q(번호/본문 부분 매치), unread(미답만) 필터."""
    threads, _total = list_threads(db, limit=200, offset=0)

    if q:
        ql = q.lower()
        threads = [
            t
            for t in threads
            if ql in (t.phone or "").lower()
            or ql in (t.last_body or "").lower()
        ]

    if unread:
        threads = [t for t in threads if t.unanswered]

    # N+1 회피: 필터링 후 남은 쌍을 한 번에 수집 → 2쿼리 × 2종 = 4쿼리로 고정.
    pairs: set[tuple[str, str]] = {(t.caller, t.phone) for t in threads}
    channels = _batch_last_mt_channels(db, pairs)
    labels = _batch_last_campaign_labels(db, pairs)

    rows: list[dict] = []
    for t in threads:
        key = (t.caller, t.phone)
        last_channel = channels.get(key, "sms")
        row = _service_thread_to_ts(t, last_channel)
        label = labels.get(key)
        if label:
            row["lastCampaign"] = label
        rows.append(row)

    return {"data": rows}


# ── S6: GET /threads/{id} ────────────────────────────────────────────────────


@router.get("/threads/{tid}", response_model=None)
def api_get_thread(tid: str, db: Session = Depends(get_db)) -> dict | JSONResponse:
    """스레드 상세 — 메시지 포함."""
    parsed = _parse_thread_id(tid)
    if parsed is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "스레드를 찾을 수 없습니다"}},
            status_code=404,
        )
    caller, phone = parsed

    messages = get_thread(db, caller, phone)
    if not messages:
        # 메시지 없는 thread id 는 존재하지 않음으로 처리.
        return JSONResponse(
            {"error": {"code": "not_found", "message": "스레드를 찾을 수 없습니다"}},
            status_code=404,
        )

    # 최근 timestamp / body / unanswered 도출 — thread 요약.
    last = messages[-1]
    unanswered = last.direction == "IN"
    # 단건 조회도 batch 헬퍼 재사용 — pair 1개면 2쿼리로 동일, 코드 경로 통일.
    pair = {(caller, phone)}
    last_channel = _batch_last_mt_channels(db, pair).get((caller, phone), "sms")
    label = _batch_last_campaign_labels(db, pair).get((caller, phone))

    detail: dict = {
        "id": tid,
        "name": phone,
        "phone": phone,
        "preview": (last.body or "")[:60],
        "time": _hhmm(last.timestamp),
        "channel": last_channel,
        "messages": [_service_message_to_ts(m) for m in messages],
    }
    if unanswered:
        detail["unread"] = True
    if label:
        detail["lastCampaign"] = label
    return {"data": detail}


# ── POST /threads/{id}/messages — 답장 발송 ──────────────────────────────────


class MessageCreateBody(BaseModel):
    text: str = Field(..., min_length=1)

    @field_validator("text")
    @classmethod
    def _strip_non_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("비어 있을 수 없습니다")
        return stripped


@router.post(
    "/threads/{tid}/messages",
    dependencies=[Depends(verify_csrf)],
    response_model=None,
)
async def api_post_message(
    tid: str,
    body: MessageCreateBody,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    """답장 발송 — 단건 캠페인 생성 후 msghub 로 전송.

    NOTE: 현재 구현은 단방향 RCS(RPSSAXX001) 로 발송. 양방향 CHAT(RPCSAXX001)
    은 고객의 MO 와 연결된 replyId 가 필요해 별도 플로우 (추후 구현).
    """
    parsed = _parse_thread_id(tid)
    if parsed is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "스레드를 찾을 수 없습니다"}},
            status_code=404,
        )
    caller, phone = parsed

    from app.main import get_msghub_client
    from app.services.chat import send_reply

    client = get_msghub_client()
    if client is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "msghub_unavailable", "message": "msghub 클라이언트 미초기화"},
        )

    try:
        campaign = await send_reply(
            db=db,
            msghub_client=client,
            user=user,
            caller=caller,
            phone=phone,
            content=body.text,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "validation_failed", "message": str(exc)},
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("send_reply failed")
        raise HTTPException(
            status_code=500,
            detail={"code": "send_failed", "message": "답장 전송 중 오류가 발생했습니다"},
        )

    now_kst = datetime.now(UTC).astimezone(KST)
    return {
        "data": {
            "message": {
                "id": f"m-out-{campaign.id}",
                "side": "us",
                "kind": "sms",  # 단방향 RCS 일 수도 있지만 preview 는 sms 안전값
                "text": body.text,
                "time": now_kst.strftime("%H:%M"),
            }
        }
    }


@router.post(
    "/threads/{tid}/read",
    dependencies=[Depends(verify_csrf)],
    response_model=None,
)
def api_mark_read(tid: str) -> dict | JSONResponse:
    """스레드 읽음 표시 — 현재 스키마엔 read flag 없음. no-op 으로 200 반환.

    (UI 에서 로컬 상태 갱신을 위한 확인 응답 역할. 향후 thread_reads 테이블
    추가 시 실 DB write 로 교체.)
    """
    parsed = _parse_thread_id(tid)
    if parsed is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "스레드를 찾을 수 없습니다"}},
            status_code=404,
        )
    return {"data": {"id": tid, "unread": False}}


# ── SSE stream (Phase 후속) ───────────────────────────────────────────────────


@router.get("/chat/stream")
async def chat_stream() -> StreamingResponse:
    """SSE — 현재는 30초 keep-alive ping 만. 실제 이벤트(message.new,
    thread.updated, session.expired) 는 DB trigger / PubSub 도입 후 발행."""

    async def gen():
        try:
            while True:
                yield "event: ping\ndata: .\n\n"
                await asyncio.sleep(30)
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
