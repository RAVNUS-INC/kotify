"""주소록 API — S7~S10.

Phase 7c: GET /contacts 목록 + GET /contacts/{id} 상세 (mock).
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


_MOCK_CONTACTS: List[dict] = [
    {
        "id": "u-001",
        "name": "박지훈",
        "phone": "010-1234-5678",
        "email": "jihoon@ravnus.kr",
        "team": "영업",
        "tags": ["VIP", "오프라인"],
        "groupIds": ["g-sales"],
        "lastCampaign": "4월 공지사항",
        "createdAt": "2025-11-12",
    },
    {
        "id": "u-002",
        "name": "이수진",
        "phone": "010-9876-5432",
        "email": "sujin.lee@ravnus.kr",
        "team": "마케팅",
        "tags": ["뉴스레터"],
        "groupIds": ["g-marketing"],
        "lastCampaign": "마케팅 뉴스레터 #12",
        "createdAt": "2025-09-02",
    },
    {
        "id": "u-003",
        "name": "김민재",
        "phone": "010-3333-4444",
        "email": "minjae.kim@ravnus.kr",
        "team": "개발",
        "tags": ["관리자"],
        "groupIds": ["g-dev", "g-admin"],
        "lastCampaign": "회의 리마인더",
        "createdAt": "2024-06-20",
    },
    {
        "id": "u-004",
        "name": "정태영",
        "phone": "010-5555-6666",
        "email": "taeyoung@ravnus.kr",
        "team": "인사",
        "tags": [],
        "groupIds": ["g-hr"],
        "lastCampaign": "인사팀 공지",
        "createdAt": "2025-03-15",
    },
    {
        "id": "u-005",
        "name": "최서연",
        "phone": "010-7777-8888",
        "email": "seoyeon@ravnus.kr",
        "team": "디자인",
        "tags": ["파트너"],
        "groupIds": ["g-design"],
        "lastCampaign": "카톡 이벤트 안내",
        "createdAt": "2024-11-30",
    },
    {
        "id": "u-006",
        "name": "김영호",
        "phone": "010-9999-0000",
        "email": "youngho@ravnus.kr",
        "team": "영업",
        "tags": [],
        "groupIds": ["g-sales"],
        "lastCampaign": "아침 공지",
        "createdAt": "2024-08-04",
    },
    {
        "id": "u-007",
        "name": "문지우",
        "phone": "010-2222-3333",
        "email": "jiwoo@ravnus.kr",
        "team": "개발",
        "tags": ["신규"],
        "groupIds": ["g-dev"],
        "lastCampaign": None,
        "createdAt": "2026-02-11",
    },
    {
        "id": "u-008",
        "name": "강민지",
        "phone": "010-4444-5555",
        "email": "minji@ravnus.kr",
        "team": "마케팅",
        "tags": ["VIP", "뉴스레터"],
        "groupIds": ["g-marketing"],
        "lastCampaign": "마케팅 뉴스레터 #12",
        "createdAt": "2025-05-22",
    },
    {
        "id": "u-009",
        "name": "양현수",
        "phone": "010-6666-7777",
        "email": "hyunsoo@ravnus.kr",
        "team": "영업",
        "tags": ["오프라인"],
        "groupIds": ["g-sales"],
        "lastCampaign": "4월 공지사항",
        "createdAt": "2024-12-01",
    },
    {
        "id": "u-010",
        "name": "한예린",
        "phone": "010-8888-9999",
        "email": "yerin@ravnus.kr",
        "team": "디자인",
        "tags": ["파트너", "VIP"],
        "groupIds": ["g-design"],
        "lastCampaign": "카톡 이벤트 안내",
        "createdAt": "2025-07-14",
    },
    {
        "id": "u-011",
        "name": "백지훈",
        "phone": "010-0000-1111",
        "email": "jeehoon@ravnus.kr",
        "team": "개발",
        "tags": [],
        "groupIds": ["g-dev"],
        "lastCampaign": "회의 리마인더",
        "createdAt": "2025-10-05",
    },
    {
        "id": "u-012",
        "name": "조승현",
        "phone": "010-1111-2222",
        "email": "seunghyun@ravnus.kr",
        "team": "인사",
        "tags": ["관리자"],
        "groupIds": ["g-hr", "g-admin"],
        "lastCampaign": "인사팀 공지",
        "createdAt": "2024-04-18",
    },
    {
        "id": "u-013",
        "name": "권나연",
        "phone": "010-3333-5555",
        "email": "nayeon@ravnus.kr",
        "team": "마케팅",
        "tags": ["뉴스레터"],
        "groupIds": ["g-marketing"],
        "lastCampaign": "마케팅 뉴스레터 #12",
        "createdAt": "2026-01-20",
    },
    {
        "id": "u-014",
        "name": "윤태호",
        "phone": "010-4444-6666",
        "email": "taeho@ravnus.kr",
        "team": "영업",
        "tags": [],
        "groupIds": ["g-sales"],
        "lastCampaign": "4월 공지사항",
        "createdAt": "2024-07-09",
    },
    {
        "id": "u-015",
        "name": "신아영",
        "phone": "010-5555-7777",
        "email": "ayoung@ravnus.kr",
        "team": "디자인",
        "tags": ["신규"],
        "groupIds": ["g-design"],
        "lastCampaign": None,
        "createdAt": "2026-03-02",
    },
]


_MOCK_REPLY_HISTORY: dict[str, list[dict]] = {
    "u-001": [
        {"id": "rh-1", "campaignName": "4월 공지사항", "text": "언제 배송되나요?", "at": "2026-04-21 14:02"},
        {"id": "rh-2", "campaignName": "3월 뉴스레터", "text": "감사합니다", "at": "2026-03-15 10:30"},
    ],
    "u-002": [
        {"id": "rh-3", "campaignName": "마케팅 뉴스레터 #12", "text": "네 확인했습니다 감사합니다", "at": "2026-04-21 13:58"},
    ],
    "u-003": [
        {"id": "rh-4", "campaignName": "회의 리마인더", "text": "회의 10분 뒤로 미뤄도 될까요?", "at": "2026-04-21 13:42"},
    ],
}

_MOCK_RECENT_CAMPAIGNS: dict[str, list[dict]] = {
    "u-001": [
        {"id": "c-001", "name": "4월 공지사항", "status": "sent", "sentAt": "2026-04-21 14:02"},
        {"id": "c-007", "name": "아침 조회 안내", "status": "sent", "sentAt": "2026-04-21 08:00"},
    ],
    "u-002": [
        {"id": "c-002", "name": "마케팅 뉴스레터 #12", "status": "sending", "sentAt": "2026-04-21 13:40"},
    ],
}


def _summary(c: dict) -> dict:
    return c


@router.get("/contacts")
async def list_contacts(
    q: Optional[str] = None,
    groupId: Optional[str] = None,
    tag: Optional[str] = None,
) -> dict:
    """주소록 목록. q는 이름·번호·이메일 부분 매치, groupId/tag는 엄격."""
    rows = _MOCK_CONTACTS

    if q:
        ql = q.lower()
        rows = [
            c
            for c in rows
            if ql in c["name"].lower()
            or ql in c.get("phone", "")
            or ql in (c.get("email") or "").lower()
        ]
    if groupId:
        rows = [c for c in rows if groupId in (c.get("groupIds") or [])]
    if tag:
        rows = [c for c in rows if tag in (c.get("tags") or [])]

    rows = sorted(rows, key=lambda c: c["name"])
    return {
        "data": [_summary(c) for c in rows],
        "meta": {"total": len(rows)},
    }


@router.get("/contacts/{cid}")
async def get_contact(cid: str):
    """연락처 상세 — 최근 캠페인 + 회신 이력 포함."""
    for c in _MOCK_CONTACTS:
        if c["id"] == cid:
            return {
                "data": {
                    **c,
                    "recentCampaigns": _MOCK_RECENT_CAMPAIGNS.get(cid, []),
                    "replyHistory": _MOCK_REPLY_HISTORY.get(cid, []),
                }
            }
    return JSONResponse(
        {"error": {"code": "not_found", "message": "연락처를 찾을 수 없습니다"}},
        status_code=404,
    )
