"""스레드(대화방) API 라우트 — S5 인박스, S6 스레드 상세.

Phase 6c: mock 데이터 + SSE 주소 확보.
Phase 6d: 메시지 발송 POST + 읽음 표시. SSE 실제 이벤트 발행은 Phase 7+.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.auth.deps import require_setup_complete, require_user
from app.security.csrf import verify_csrf

router = APIRouter(
    dependencies=[Depends(require_user), Depends(require_setup_complete)],
)

# in-memory mock 데이터 동시성 보호 (Phase 10 실제 DB 도입 시 제거)
_mock_lock = asyncio.Lock()


_MOCK_THREADS: List[dict] = [
    {
        "id": "t1",
        "name": "박지훈",
        "phone": "010-1234-5678",
        "preview": "언제 배송되나요?",
        "time": "14:02",
        "unread": True,
        "channel": "sms",
        "lastCampaign": "4월 공지",
        "messages": [
            {"id": "m1-1", "side": "us", "kind": "sms", "text": "4월 공지사항입니다. 회사 창립 기념으로 월말 휴무 안내.", "time": "12:00"},
            {"id": "m1-2", "side": "them", "kind": "sms", "text": "언제 배송되나요?", "time": "14:02"},
        ],
    },
    {
        "id": "t2",
        "name": "이수진",
        "phone": "010-9876-5432",
        "preview": "네 확인했습니다 감사합니다",
        "time": "13:58",
        "unread": True,
        "channel": "rcs",
        "lastCampaign": "마케팅 뉴스레터",
        "messages": [
            {"id": "m2-1", "side": "us", "kind": "rcs", "text": "구독해주셔서 감사합니다.", "time": "13:50"},
            {"id": "m2-2", "side": "them", "kind": "rcs", "text": "네 확인했습니다 감사합니다", "time": "13:58"},
        ],
    },
    {
        "id": "t3",
        "name": "김민재",
        "phone": "010-3333-4444",
        "preview": "회의 10분 뒤로 미뤄도 될까요?",
        "time": "13:42",
        "unread": True,
        "channel": "sms",
        "lastCampaign": "회의 리마인더",
        "messages": [
            {"id": "m3-1", "side": "us", "kind": "sms", "text": "오후 회의 14시 시작 예정입니다.", "time": "13:30"},
            {"id": "m3-2", "side": "them", "kind": "sms", "text": "회의 10분 뒤로 미뤄도 될까요?", "time": "13:42"},
        ],
    },
    {
        "id": "t4",
        "name": "정태영",
        "phone": "010-5555-6666",
        "preview": "네 알겠습니다",
        "time": "11:30",
        "unread": False,
        "channel": "sms",
        "lastCampaign": "인사팀 공지",
        "messages": [
            {"id": "m4-1", "side": "us", "kind": "sms", "text": "금요일 단체 회식 장소 안내드립니다.", "time": "11:20"},
            {"id": "m4-2", "side": "them", "kind": "sms", "text": "네 알겠습니다", "time": "11:30"},
        ],
    },
    {
        "id": "t5",
        "name": "최서연",
        "phone": "010-7777-8888",
        "preview": "확인 부탁드려요",
        "time": "10:15",
        "unread": False,
        "channel": "kakao",
        "lastCampaign": "카톡 공지",
        "messages": [
            {"id": "m5-1", "side": "them", "kind": "kakao", "text": "확인 부탁드려요", "time": "10:15"},
        ],
    },
    {
        "id": "t6",
        "name": "김영호",
        "phone": "010-9999-0000",
        "preview": "감사합니다 수고하세요",
        "time": "09:48",
        "unread": False,
        "channel": "sms",
        "lastCampaign": "아침 공지",
        "messages": [
            {"id": "m6-1", "side": "us", "kind": "sms", "text": "아침 조회 시작합니다.", "time": "09:45"},
            {"id": "m6-2", "side": "them", "kind": "sms", "text": "감사합니다 수고하세요", "time": "09:48"},
        ],
    },
]


def _summary(t: dict) -> dict:
    return {k: v for k, v in t.items() if k != "messages"}


@router.get("/threads")
async def list_threads(
    q: Optional[str] = None,
    unread: Optional[bool] = None,
) -> dict:
    """스레드 목록. q(검색), unread(안읽음만) 필터."""
    threads = _MOCK_THREADS
    if q:
        ql = q.lower()
        threads = [
            t
            for t in threads
            if ql in t["name"].lower() or ql in t["preview"].lower()
        ]
    if unread:
        threads = [t for t in threads if t.get("unread")]
    return {"data": [_summary(t) for t in threads]}


@router.get("/threads/{tid}")
async def get_thread(tid: str):
    """특정 스레드 상세 (메시지 포함)."""
    for t in _MOCK_THREADS:
        if t["id"] == tid:
            return {"data": t}
    return JSONResponse(
        {"error": {"code": "not_found", "message": "스레드를 찾을 수 없습니다"}},
        status_code=404,
    )


class MessageCreateBody(BaseModel):
    text: str = Field(..., min_length=1)

    @field_validator("text")
    @classmethod
    def _strip_non_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("비어 있을 수 없습니다")
        return stripped


def _find_thread(tid: str) -> Optional[dict]:
    for t in _MOCK_THREADS:
        if t["id"] == tid:
            return t
    return None


@router.post("/threads/{tid}/messages", dependencies=[Depends(verify_csrf)])
async def post_message(tid: str, body: MessageCreateBody):
    """새 메시지 전송 (mock).

    _mock_lock로 동시 append 방지. 실제 DB 도입 시 row-level lock으로 대체.
    """
    async with _mock_lock:
        thread = _find_thread(tid)
        if thread is None:
            return JSONResponse(
                {"error": {"code": "not_found", "message": "스레드를 찾을 수 없습니다"}},
                status_code=404,
            )

        now_hhmm = datetime.now().strftime("%H:%M")
        message = {
            "id": f"m-{uuid.uuid4().hex[:8]}",
            "side": "us",
            "kind": thread["channel"],
            "text": body.text,
            "time": now_hhmm,
        }
        thread.setdefault("messages", []).append(message)
        thread["preview"] = body.text[:60]
        thread["time"] = now_hhmm
        thread["unread"] = False

    return {"data": {"message": message}}


@router.post("/threads/{tid}/read", dependencies=[Depends(verify_csrf)])
async def mark_read(tid: str):
    """스레드 읽음 표시."""
    async with _mock_lock:
        thread = _find_thread(tid)
        if thread is None:
            return JSONResponse(
                {"error": {"code": "not_found", "message": "스레드를 찾을 수 없습니다"}},
                status_code=404,
            )
        thread["unread"] = False
    return {"data": {"id": tid, "unread": False}}


@router.get("/chat/stream")
async def chat_stream() -> StreamingResponse:
    """SSE 스트림. Phase 6c에선 30초 keep-alive ping만 전송.

    Phase 6d에서 message.new / thread.updated / session.expired 이벤트 발행 예정.
    """

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
