"""그룹 API — S9 목록, S10 상세.

Phase 7d: mock. contacts.py의 _MOCK_CONTACTS를 역참조해 멤버 구성.
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.auth.deps import require_setup_complete, require_user
from app.routes.contacts import _MOCK_CONTACTS

router = APIRouter(
    dependencies=[Depends(require_user), Depends(require_setup_complete)],
)


_MOCK_GROUPS: List[dict] = [
    {
        "id": "g-sales",
        "name": "영업팀",
        "description": "영업 조직 전체",
        "source": "ad",
        "memberCount": 3,
        "validCount": 3,
        "lastSyncAt": "2026-04-21 06:00",
        "lastCampaignAt": "2026-04-21 14:02",
        "reachRate": 96.5,
    },
    {
        "id": "g-marketing",
        "name": "마케팅팀",
        "description": "뉴스레터 · 캠페인 운영",
        "source": "ad",
        "memberCount": 3,
        "validCount": 3,
        "lastSyncAt": "2026-04-21 06:00",
        "lastCampaignAt": "2026-04-21 13:40",
        "reachRate": 98.1,
    },
    {
        "id": "g-dev",
        "name": "개발팀",
        "description": "엔지니어링 전체",
        "source": "ad",
        "memberCount": 3,
        "validCount": 3,
        "lastSyncAt": "2026-04-21 06:00",
        "lastCampaignAt": "2026-04-21 13:42",
        "reachRate": 94.2,
    },
    {
        "id": "g-hr",
        "name": "인사팀",
        "description": "HR 공지 대상자",
        "source": "ad",
        "memberCount": 2,
        "validCount": 2,
        "lastSyncAt": "2026-04-21 06:00",
        "lastCampaignAt": "2026-04-21 09:20",
        "reachRate": 100.0,
    },
    {
        "id": "g-design",
        "name": "디자인팀",
        "description": "디자인 그룹",
        "source": "ad",
        "memberCount": 3,
        "validCount": 3,
        "lastSyncAt": "2026-04-21 06:00",
        "lastCampaignAt": "2026-04-20 16:00",
        "reachRate": 92.8,
    },
    {
        "id": "g-admin",
        "name": "관리자",
        "description": "시스템 권한 보유자 (수동 관리)",
        "source": "manual",
        "memberCount": 2,
        "validCount": 2,
        "lastSyncAt": None,
        "lastCampaignAt": None,
        "reachRate": None,
    },
    {
        "id": "g-vip",
        "name": "VIP 고객",
        "description": "CSV 업로드로 관리",
        "source": "csv",
        "memberCount": 128,
        "validCount": 124,
        "lastSyncAt": "2026-04-18 10:30",
        "lastCampaignAt": "2026-04-20 16:00",
        "reachRate": 89.5,
    },
    {
        "id": "g-partners",
        "name": "파트너사",
        "description": "API 연동 · 일 1회 동기화",
        "source": "api",
        "memberCount": 48,
        "validCount": 46,
        "lastSyncAt": "2026-04-21 03:00",
        "lastCampaignAt": "2026-04-19 14:00",
        "reachRate": 91.3,
    },
]


def _members_of(gid: str) -> list[dict]:
    """_MOCK_CONTACTS에서 groupIds 역참조."""
    return [c for c in _MOCK_CONTACTS if gid in (c.get("groupIds") or [])]


@router.get("/groups")
async def list_groups(q: Optional[str] = None) -> dict:
    rows = _MOCK_GROUPS
    if q:
        ql = q.lower()
        rows = [
            g
            for g in rows
            if ql in g["name"].lower() or ql in (g.get("description") or "").lower()
        ]
    return {"data": rows, "meta": {"total": len(rows)}}


@router.get("/groups/{gid}")
async def get_group(gid: str):
    for g in _MOCK_GROUPS:
        if g["id"] == gid:
            members = _members_of(gid)
            return {
                "data": {
                    **g,
                    # memberCount를 실제 역참조 결과로 override (정확도)
                    "memberCount": len(members) if members else g["memberCount"],
                    "members": members,
                }
            }
    return JSONResponse(
        {"error": {"code": "not_found", "message": "그룹을 찾을 수 없습니다"}},
        status_code=404,
    )
