"""캠페인 API 라우트 — S2 Compose 발송.

Phase 6b: mock 데이터. 검증 로직은 실제 유지, 저장은 skip.
Phase 10 이후 실제 msghub 호출 + DB 저장으로 교체.
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter()


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
