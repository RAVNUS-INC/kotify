"""캠페인 API 라우트 — S2 Compose 발송 / S3 이력.

Phase 6b: POST /campaigns (mock).
Phase 7a: GET /campaigns 목록 + 필터.
Phase 10 이후 실제 msghub 호출 + DB 저장으로 교체.
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter()


_MOCK_CAMPAIGNS: List[dict] = [
    {
        "id": "c-001",
        "name": "4월 공지사항",
        "status": "sent",
        "sender": "1588-1234",
        "channel": "rcs",
        "createdAt": "2026-04-21 14:02",
        "recipients": 342,
        "reach": 334,
        "replies": 12,
        "cost": 2736,
    },
    {
        "id": "c-002",
        "name": "마케팅 뉴스레터 #12",
        "status": "sending",
        "sender": "1588-1234",
        "channel": "rcs",
        "createdAt": "2026-04-21 13:40",
        "recipients": 500,
        "reach": 187,
        "replies": 3,
        "cost": 1496,
    },
    {
        "id": "c-003",
        "name": "금요 회식 공지",
        "status": "scheduled",
        "sender": "02-3456-7890",
        "channel": "sms",
        "createdAt": "2026-04-21 10:12",
        "scheduledAt": "2026-04-22 18:00",
        "recipients": 28,
        "reach": None,
        "replies": None,
        "cost": 224,
    },
    {
        "id": "c-004",
        "name": "인사팀 공지",
        "status": "sent",
        "sender": "02-3456-7890",
        "channel": "sms",
        "createdAt": "2026-04-21 09:20",
        "recipients": 124,
        "reach": 121,
        "replies": 8,
        "cost": 992,
    },
    {
        "id": "c-005",
        "name": "월간 리포트 발송",
        "status": "failed",
        "sender": "1588-1234",
        "channel": "rcs",
        "createdAt": "2026-04-20 18:30",
        "recipients": 892,
        "reach": 0,
        "replies": 0,
        "cost": 0,
        "failureReason": "msghub 인증 오류",
    },
    {
        "id": "c-006",
        "name": "긴급 시스템 점검",
        "status": "cancelled",
        "sender": "1588-1234",
        "channel": "rcs",
        "createdAt": "2026-04-20 15:00",
        "recipients": 1000,
        "reach": None,
        "replies": None,
        "cost": 0,
    },
    {
        "id": "c-007",
        "name": "아침 조회 안내",
        "status": "sent",
        "sender": "02-3456-7890",
        "channel": "sms",
        "createdAt": "2026-04-21 08:00",
        "recipients": 48,
        "reach": 47,
        "replies": 2,
        "cost": 384,
    },
    {
        "id": "c-008",
        "name": "점심 메뉴 투표",
        "status": "sent",
        "sender": "1588-1234",
        "channel": "rcs",
        "createdAt": "2026-04-21 11:00",
        "recipients": 62,
        "reach": 61,
        "replies": 34,
        "cost": 496,
    },
    {
        "id": "c-009",
        "name": "회의 리마인더",
        "status": "sent",
        "sender": "02-3456-7890",
        "channel": "sms",
        "createdAt": "2026-04-21 13:30",
        "recipients": 8,
        "reach": 8,
        "replies": 1,
        "cost": 64,
    },
    {
        "id": "c-010",
        "name": "주간 리포트 초안",
        "status": "draft",
        "sender": "1588-1234",
        "channel": "rcs",
        "createdAt": "2026-04-21 12:00",
        "recipients": 0,
        "reach": None,
        "replies": None,
        "cost": 0,
    },
    {
        "id": "c-011",
        "name": "카톡 이벤트 안내",
        "status": "sent",
        "sender": "1588-1234",
        "channel": "kakao",
        "createdAt": "2026-04-20 16:00",
        "recipients": 456,
        "reach": 430,
        "replies": 15,
        "cost": 3648,
    },
    {
        "id": "c-012",
        "name": "단체 회식 공지",
        "status": "sent",
        "sender": "02-3456-7890",
        "channel": "sms",
        "createdAt": "2026-04-19 14:00",
        "recipients": 142,
        "reach": 140,
        "replies": 11,
        "cost": 1136,
    },
]


class CampaignCreateBody(BaseModel):
    """POST /campaigns 요청 body."""

    sender: str = Field(..., min_length=1)
    recipients: List[str] = Field(default_factory=list)
    message: str = Field(..., min_length=1)
    sendAt: Optional[str] = None
    channel: Optional[str] = None


def _validation_error(message: str, field: str) -> JSONResponse:
    return JSONResponse(
        {
            "error": {
                "code": "validation_failed",
                "message": message,
                "fields": {field: message},
            }
        },
        status_code=422,
    )


def _estimate_cost(message: str, count: int) -> tuple[int, int, str]:
    """메시지 바이트·수신자 수로 per-unit 비용과 채널을 계산한다."""
    bytes_ = len(message.encode("utf-8"))
    if bytes_ <= 90:
        per = 8
        channel = "SMS"
    elif bytes_ <= 2000:
        per = 32
        channel = "LMS"
    else:
        per = 100
        channel = "MMS"
    return bytes_, per * count, channel


@router.get("/campaigns")
async def list_campaigns(
    q: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    """캠페인 목록 (mock). q는 이름 부분 매치, status는 엄격 일치.

    `status=all` 또는 None은 전체 반환.
    """
    rows = _MOCK_CAMPAIGNS
    if status and status != "all":
        rows = [r for r in rows if r.get("status") == status]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["name"].lower()]
    # 최신순
    rows = sorted(rows, key=lambda r: r.get("createdAt", ""), reverse=True)
    return {
        "data": rows,
        "meta": {"total": len(rows)},
    }


@router.post("/campaigns")
async def create_campaign(body: CampaignCreateBody) -> JSONResponse:
    """새 캠페인 생성 (mock).

    Returns:
        envelope `{ data: { id, status, estimate: { reach, cost, channel } } }`.
    """
    if not body.sender.strip():
        return _validation_error("발신번호가 필요합니다", "sender")
    if not body.recipients:
        return _validation_error("수신자가 한 명 이상 필요합니다", "recipients")
    if not body.message.strip():
        return _validation_error("메시지 본문이 필요합니다", "message")
    if len(body.recipients) > 1000:
        return _validation_error("캠페인당 수신자는 최대 1,000명입니다", "recipients")

    cid = uuid.uuid4().hex[:12]
    count = len(body.recipients)
    _bytes, cost, channel = _estimate_cost(body.message, count)

    return JSONResponse(
        {
            "data": {
                "id": cid,
                "status": "scheduled" if body.sendAt else "sending",
                "estimate": {
                    "reach": count,
                    "cost": cost,
                    "channel": channel,
                },
            }
        }
    )
