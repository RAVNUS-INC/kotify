"""설정 API — S12.

Phase 8b: /org, /members, /api-keys, /webhooks mock.
org는 PATCH로 부분 수정 지원. 나머지는 read-only list (CRUD는 Phase 후속).
"""
from __future__ import annotations

import asyncio
from typing import List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter()

# 동시성 보호
_settings_lock = asyncio.Lock()


_MOCK_ORG: dict = {
    "name": "RAVNUS",
    "service": "사내 공지 시스템",
    "contact": "ops@ravnus.kr",
    "timezone": "Asia/Seoul",
    "limits": {
        "recipientsPerCampaign": 1000,
        "campaignsPerMinute": 10,
    },
}


_MOCK_MEMBERS: List[dict] = [
    {"id": "m-001", "email": "hello@ravnus.kr", "name": "김운영", "role": "owner", "active": True, "invitedAt": "2024-01-10"},
    {"id": "m-002", "email": "ops@ravnus.kr", "name": "박지훈", "role": "admin", "active": True, "invitedAt": "2024-03-15"},
    {"id": "m-003", "email": "dev@ravnus.kr", "name": "김민재", "role": "admin", "active": True, "invitedAt": "2024-06-20"},
    {"id": "m-004", "email": "marketing@ravnus.kr", "name": "이수진", "role": "operator", "active": True, "invitedAt": "2025-09-02"},
    {"id": "m-005", "email": "reader@ravnus.kr", "name": "최서연", "role": "viewer", "active": True, "invitedAt": "2025-11-30"},
    {"id": "m-006", "email": "former@ravnus.kr", "name": "이전직원", "role": "viewer", "active": False, "invitedAt": "2024-02-01"},
]


_MOCK_API_KEYS: List[dict] = [
    {"id": "k-001", "name": "배포 서버", "prefix": "kpi_1a2b3c4d", "scopes": ["send", "read"], "createdAt": "2024-08-04", "lastUsedAt": "2026-04-21 13:55"},
    {"id": "k-002", "name": "분석 파이프라인", "prefix": "kpi_9f8e7d6c", "scopes": ["read"], "createdAt": "2025-01-20", "lastUsedAt": "2026-04-21 06:00"},
    {"id": "k-003", "name": "(만료 예정)", "prefix": "kpi_5b4a3c2d", "scopes": ["read"], "createdAt": "2024-03-01", "lastUsedAt": "2026-01-15"},
]


_MOCK_WEBHOOKS: List[dict] = [
    {"id": "w-001", "url": "https://ravnus.slack.com/hooks/kotify/send-result", "events": ["send.completed", "send.failed"], "active": True, "createdAt": "2025-03-10"},
    {"id": "w-002", "url": "https://internal.ravnus.kr/kotify/audit", "events": ["audit.*"], "active": True, "createdAt": "2025-06-22"},
    {"id": "w-003", "url": "https://staging.ravnus.kr/debug", "events": ["send.*"], "active": False, "createdAt": "2026-02-08"},
]


class OrgPatchBody(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    service: Optional[str] = Field(default=None, max_length=120)
    contact: Optional[str] = Field(default=None, max_length=120)
    timezone: Optional[str] = None


@router.get("/org")
async def get_org() -> dict:
    return {"data": _MOCK_ORG}


@router.patch("/org")
async def patch_org(body: OrgPatchBody) -> dict:
    async with _settings_lock:
        updates = body.model_dump(exclude_none=True)
        for k, v in updates.items():
            if isinstance(v, str):
                v = v.strip()
                if not v and k in ("name",):
                    return JSONResponse(
                        {
                            "error": {
                                "code": "validation_failed",
                                "message": "조직명은 비어 있을 수 없습니다",
                                "fields": {k: "필수"},
                            }
                        },
                        status_code=422,
                    )
            _MOCK_ORG[k] = v
    return {"data": _MOCK_ORG}


@router.get("/members")
async def list_members() -> dict:
    return {"data": _MOCK_MEMBERS, "meta": {"total": len(_MOCK_MEMBERS)}}


@router.get("/api-keys")
async def list_api_keys() -> dict:
    return {"data": _MOCK_API_KEYS, "meta": {"total": len(_MOCK_API_KEYS)}}


@router.get("/webhooks")
async def list_webhooks() -> dict:
    return {"data": _MOCK_WEBHOOKS, "meta": {"total": len(_MOCK_WEBHOOKS)}}
