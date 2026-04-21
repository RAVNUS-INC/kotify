"""통합 검색 API — S17.

Phase 9c: 기존 mock 데이터(_MOCK_CONTACTS / _MOCK_CAMPAIGNS /
_MOCK_THREADS / _MOCK_AUDIT)를 cross-cutting 검색.
"""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.routes.audit_api import _MOCK_AUDIT
from app.routes.campaigns import _MOCK_CAMPAIGNS
from app.routes.contacts import _MOCK_CONTACTS
from app.routes.threads import _MOCK_THREADS

router = APIRouter()


_SECTION_LIMIT = 10


@router.get("/search")
async def search(q: str = Query(default="", description="검색어")) -> dict:
    query = q.strip().lower()
    if not query:
        return {
            "data": {
                "contacts": [],
                "threads": [],
                "campaigns": [],
                "auditLogs": [],
                "counts": {
                    "total": 0,
                    "contacts": 0,
                    "threads": 0,
                    "campaigns": 0,
                    "auditLogs": 0,
                },
            }
        }

    # Contacts: 이름·번호·이메일
    contacts = [
        c
        for c in _MOCK_CONTACTS
        if query in c["name"].lower()
        or query in (c.get("phone") or "")
        or query in (c.get("email") or "").lower()
    ]

    # Campaigns: 이름
    campaigns = [
        {
            "id": c["id"],
            "name": c["name"],
            "status": c["status"],
            "createdAt": c.get("createdAt", ""),
        }
        for c in _MOCK_CAMPAIGNS
        if query in c["name"].lower()
    ]

    # Threads: 메시지 본문에서 매칭되는 첫 메시지를 snippet으로
    threads = []
    for t in _MOCK_THREADS:
        for m in t.get("messages", []) or []:
            if query in m["text"].lower():
                threads.append(
                    {
                        "id": t["id"],
                        "name": t["name"],
                        "phone": t["phone"],
                        "snippet": m["text"],
                        "time": m["time"],
                        "campaignName": t.get("lastCampaign"),
                    }
                )
                break

    # Audit: actor / email / action / target
    audit_logs = [
        {
            "id": a["id"],
            "time": a["time"],
            "actor": a["actor"],
            "action": a["action"],
            "target": a["target"],
        }
        for a in _MOCK_AUDIT
        if query in a["actor"].lower()
        or query in a["actorEmail"].lower()
        or query in a["action"].lower()
        or query in a["target"].lower()
    ]

    counts = {
        "total": len(contacts) + len(threads) + len(campaigns) + len(audit_logs),
        "contacts": len(contacts),
        "threads": len(threads),
        "campaigns": len(campaigns),
        "auditLogs": len(audit_logs),
    }

    return {
        "data": {
            "contacts": contacts[:_SECTION_LIMIT],
            "threads": threads[:_SECTION_LIMIT],
            "campaigns": campaigns[:_SECTION_LIMIT],
            "auditLogs": audit_logs[:_SECTION_LIMIT],
            "counts": counts,
        }
    }
