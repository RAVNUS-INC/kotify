"""캠페인 API 라우트 — S2 Compose 발송 / S3 이력.

Phase 6b: POST /campaigns (mock).
Phase 7a: GET /campaigns 목록 + 필터.
Phase 10 이후 실제 msghub 호출 + DB 저장으로 교체.
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from app.auth.deps import require_setup_complete, require_user
from app.security.csrf import verify_csrf

router = APIRouter(
    dependencies=[Depends(require_user), Depends(require_setup_complete)],
)


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
    recipients: List[str] = Field(..., min_length=1, max_length=1000)
    message: str = Field(..., min_length=1)
    sendAt: Optional[str] = None
    channel: Optional[str] = None

    @field_validator("sender", "message")
    @classmethod
    def _strip_non_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("비어 있을 수 없습니다")
        return stripped


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


def _mock_recipients(campaign: dict) -> list[dict]:
    """캠페인 상태에 따라 20명 샘플 수신자 생성."""
    status = campaign.get("status")
    if status in ("draft", "cancelled", "scheduled"):
        return []

    sample_names = [
        ("박지훈", "010-1234-5678"),
        ("이수진", "010-9876-5432"),
        ("김민재", "010-3333-4444"),
        ("정태영", "010-5555-6666"),
        ("최서연", "010-7777-8888"),
        ("김영호", "010-9999-0000"),
        ("문지우", "010-2222-3333"),
        ("강민지", "010-4444-5555"),
        ("양현수", "010-6666-7777"),
        ("한예린", "010-8888-9999"),
        ("백지훈", "010-0000-1111"),
        ("조승현", "010-1111-2222"),
        ("권나연", "010-3333-5555"),
        ("윤태호", "010-4444-6666"),
        ("신아영", "010-5555-7777"),
        ("배성우", "010-6666-8888"),
        ("안지민", "010-7777-9999"),
        ("홍은정", "010-8888-0000"),
        ("류재원", "010-9999-1111"),
        ("임소영", "010-0000-2222"),
    ]

    # 상태 분포 (대략적 mock)
    if status == "sent":
        distribution = (
            ["replied"] * 2
            + ["read"] * 6
            + ["delivered"] * 8
            + ["fallback_sms"] * 2
            + ["failed"] * 2
        )
    elif status == "sending":
        distribution = (
            ["delivered"] * 8
            + ["queued"] * 8
            + ["failed"] * 2
            + ["fallback_sms"] * 2
        )
    elif status == "failed":
        distribution = ["failed"] * 18 + ["fallback_sms"] * 2
    else:
        distribution = ["delivered"] * 20

    result = []
    for (name, phone), rstatus in zip(sample_names, distribution, strict=False):
        row: dict = {
            "id": f"r-{campaign['id']}-{phone[-4:]}",
            "name": name,
            "phone": phone,
            "status": rstatus,
        }
        sent_at = campaign.get("createdAt", "").split(" ")[-1] or "00:00"
        row["sentAt"] = sent_at if rstatus != "queued" else None
        if rstatus in ("read", "replied"):
            row["readAt"] = sent_at
        if rstatus == "replied":
            row["repliedAt"] = sent_at
        if rstatus == "failed":
            row["failureReason"] = "수신 거부"
        result.append(row)

    return result


@router.get("/campaigns/{cid}")
async def get_campaign(cid: str):
    """캠페인 상세 (수신자 샘플 포함)."""
    for c in _MOCK_CAMPAIGNS:
        if c["id"] == cid:
            recipients = _mock_recipients(c)
            total = c.get("recipients") or 0
            reach = c.get("reach") or 0
            replies = c.get("replies") or 0
            failed = total - reach if c.get("status") in ("sent", "failed") else 0
            fallback_count = max(1, int(total * 0.027)) if c.get("status") == "sent" else 0

            return {
                "data": {
                    **c,
                    "recipientsSample": recipients,
                    "breakdown": {
                        "total": total,
                        "rcsDelivered": max(0, reach - fallback_count),
                        "smsFallback": fallback_count,
                        "failed": failed - fallback_count if failed > fallback_count else 0,
                        "replies": replies,
                    },
                }
            }
    return JSONResponse(
        {"error": {"code": "not_found", "message": "캠페인을 찾을 수 없습니다"}},
        status_code=404,
    )


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


@router.post("/campaigns", dependencies=[Depends(verify_csrf)])
async def create_campaign(body: CampaignCreateBody) -> JSONResponse:
    """새 캠페인 생성 (mock).

    필드 검증은 Pydantic + field_validator가 전담.
    전역 validation_error_handler(app/main.py)가 envelope 422로 변환.

    Returns:
        envelope `{ data: { id, status, estimate: { reach, cost, channel } } }`.
    """
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
