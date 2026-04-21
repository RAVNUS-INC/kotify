"""발신번호 API — S11.

Phase 8a: mock 데이터. Phase 후속에서 msghub 번호 등록 API 연동.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.auth.deps import require_role, require_setup_complete

# 발신번호 관리는 admin 전용
router = APIRouter(
    dependencies=[Depends(require_role("admin")), Depends(require_setup_complete)],
)


_MOCK_NUMBERS: List[dict] = [
    {
        "id": "n-001",
        "number": "1588-1234",
        "kind": "rep",
        "supports": ["rcs", "sms"],
        "brand": "RAVNUS 대표",
        "status": "approved",
        "dailyUsage": 1284,
        "dailyLimit": 5000,
        "registeredAt": "2024-03-15",
    },
    {
        "id": "n-002",
        "number": "02-3456-7890",
        "kind": "rep",
        "supports": ["sms"],
        "brand": "RAVNUS 인사팀",
        "status": "approved",
        "dailyUsage": 89,
        "dailyLimit": 1000,
        "registeredAt": "2024-05-20",
    },
    {
        "id": "n-003",
        "number": "070-1234-5678",
        "kind": "rep",
        "supports": ["sms", "lms"],
        "brand": "RAVNUS 마케팅",
        "status": "pending",
        "dailyUsage": 0,
        "dailyLimit": None,
        "registeredAt": "2026-04-18",
    },
    {
        "id": "n-004",
        "number": "010-1234-5678",
        "kind": "mobile",
        "supports": ["sms"],
        "brand": "김운영 개인",
        "status": "rejected",
        "dailyUsage": 0,
        "dailyLimit": None,
        "registeredAt": "2026-04-10",
        "failureReason": "소유확인 실패 — 통신사 본인인증 필요",
    },
    {
        "id": "n-005",
        "number": "080-123-4567",
        "kind": "rep",
        "supports": ["sms"],
        "brand": "RAVNUS 수신거부",
        "status": "approved",
        "dailyUsage": 4,
        "dailyLimit": 100,
        "registeredAt": "2025-01-08",
    },
    {
        "id": "n-006",
        "number": "050-1111-2222",
        "kind": "rep",
        "supports": ["sms"],
        "brand": "RAVNUS 안심번호",
        "status": "expired",
        "dailyUsage": 0,
        "dailyLimit": None,
        "registeredAt": "2023-11-30",
    },
]


@router.get("/numbers")
async def list_numbers(status: Optional[str] = None) -> dict:
    rows = _MOCK_NUMBERS
    if status and status != "all":
        rows = [n for n in rows if n.get("status") == status]
    return {"data": rows, "meta": {"total": len(rows)}}


@router.get("/numbers/{nid}")
async def get_number(nid: str):
    for n in _MOCK_NUMBERS:
        if n["id"] == nid:
            return {"data": n}
    return JSONResponse(
        {"error": {"code": "not_found", "message": "발신번호를 찾을 수 없습니다"}},
        status_code=404,
    )
