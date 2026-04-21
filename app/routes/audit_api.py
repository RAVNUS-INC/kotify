"""감사 로그 API — S13.

Phase 8c: mock. 실제 app.services.audit 로그는 DB에 있지만 현재 리플레이
테이블 연결은 Phase 10+. 지금은 화면 개발용 mock 고정 데이터.
"""
from __future__ import annotations

import csv
import io
from typing import List, Optional

from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter()


_MOCK_AUDIT: List[dict] = [
    {"id": "a-001", "time": "2026-04-21 14:02:11", "actor": "김운영", "actorEmail": "hello@ravnus.kr", "action": "CREATE_CAMPAIGN", "target": "c-001 (4월 공지사항)", "ip": "203.0.113.42"},
    {"id": "a-002", "time": "2026-04-21 13:40:02", "actor": "이수진", "actorEmail": "marketing@ravnus.kr", "action": "CREATE_CAMPAIGN", "target": "c-002 (마케팅 뉴스레터 #12)", "ip": "203.0.113.17"},
    {"id": "a-003", "time": "2026-04-21 13:30:00", "actor": "박지훈", "actorEmail": "ops@ravnus.kr", "action": "LOGIN", "target": "-", "ip": "203.0.113.42"},
    {"id": "a-004", "time": "2026-04-21 11:22:45", "actor": "김민재", "actorEmail": "dev@ravnus.kr", "action": "CREATE_API_KEY", "target": "k-001 (배포 서버)", "ip": "198.51.100.8"},
    {"id": "a-005", "time": "2026-04-21 10:15:30", "actor": "김운영", "actorEmail": "hello@ravnus.kr", "action": "PATCH_ORG", "target": "org (name)", "ip": "203.0.113.42"},
    {"id": "a-006", "time": "2026-04-21 09:20:00", "actor": "박지훈", "actorEmail": "ops@ravnus.kr", "action": "CREATE_CAMPAIGN", "target": "c-004 (인사팀 공지)", "ip": "203.0.113.42"},
    {"id": "a-007", "time": "2026-04-21 08:02:18", "actor": "이수진", "actorEmail": "marketing@ravnus.kr", "action": "LOGIN", "target": "-", "ip": "203.0.113.17"},
    {"id": "a-008", "time": "2026-04-20 18:30:22", "actor": "김운영", "actorEmail": "hello@ravnus.kr", "action": "CAMPAIGN_FAILED", "target": "c-005 (월간 리포트 발송)", "ip": "203.0.113.42"},
    {"id": "a-009", "time": "2026-04-20 17:15:08", "actor": "박지훈", "actorEmail": "ops@ravnus.kr", "action": "CANCEL_CAMPAIGN", "target": "c-006 (긴급 시스템 점검)", "ip": "203.0.113.42"},
    {"id": "a-010", "time": "2026-04-20 16:00:00", "actor": "이수진", "actorEmail": "marketing@ravnus.kr", "action": "CREATE_CAMPAIGN", "target": "c-011 (카톡 이벤트 안내)", "ip": "203.0.113.17"},
    {"id": "a-011", "time": "2026-04-20 14:30:55", "actor": "김민재", "actorEmail": "dev@ravnus.kr", "action": "CREATE_WEBHOOK", "target": "w-002 (internal audit)", "ip": "198.51.100.8"},
    {"id": "a-012", "time": "2026-04-20 10:00:00", "actor": "김운영", "actorEmail": "hello@ravnus.kr", "action": "INVITE_MEMBER", "target": "m-005 (reader@ravnus.kr)", "ip": "203.0.113.42"},
    {"id": "a-013", "time": "2026-04-19 14:00:00", "actor": "박지훈", "actorEmail": "ops@ravnus.kr", "action": "CREATE_CAMPAIGN", "target": "c-012 (단체 회식 공지)", "ip": "203.0.113.42"},
    {"id": "a-014", "time": "2026-04-19 09:00:12", "actor": "김운영", "actorEmail": "hello@ravnus.kr", "action": "LOGIN", "target": "-", "ip": "203.0.113.42"},
    {"id": "a-015", "time": "2026-04-18 15:22:01", "actor": "김민재", "actorEmail": "dev@ravnus.kr", "action": "REGISTER_NUMBER", "target": "n-003 (070-1234-5678)", "ip": "198.51.100.8"},
    {"id": "a-016", "time": "2026-04-18 10:30:00", "actor": "김운영", "actorEmail": "hello@ravnus.kr", "action": "UPLOAD_CSV", "target": "g-vip (128명)", "ip": "203.0.113.42"},
    {"id": "a-017", "time": "2026-04-17 16:45:30", "actor": "이전직원", "actorEmail": "former@ravnus.kr", "action": "LOGIN_FAILED", "target": "-", "ip": "198.51.100.55"},
    {"id": "a-018", "time": "2026-04-17 11:10:08", "actor": "김운영", "actorEmail": "hello@ravnus.kr", "action": "DEACTIVATE_MEMBER", "target": "m-006 (former@ravnus.kr)", "ip": "203.0.113.42"},
    {"id": "a-019", "time": "2026-04-16 17:00:42", "actor": "박지훈", "actorEmail": "ops@ravnus.kr", "action": "EXPORT_CSV", "target": "audit (last 30 days)", "ip": "203.0.113.42"},
    {"id": "a-020", "time": "2026-04-16 09:02:15", "actor": "박지훈", "actorEmail": "ops@ravnus.kr", "action": "LOGIN", "target": "-", "ip": "203.0.113.42"},
]


def _filter(rows: List[dict], q: Optional[str], action: Optional[str]) -> List[dict]:
    if action and action != "all":
        rows = [r for r in rows if r.get("action") == action]
    if q:
        ql = q.lower()
        rows = [
            r
            for r in rows
            if ql in r["actor"].lower()
            or ql in r["actorEmail"].lower()
            or ql in r["target"].lower()
        ]
    return rows


@router.get("/audit")
async def list_audit(
    q: Optional[str] = None,
    action: Optional[str] = None,
) -> dict:
    rows = _filter(_MOCK_AUDIT, q, action)
    return {"data": rows, "meta": {"total": len(rows)}}


@router.get("/audit/export.csv")
async def export_audit_csv(
    q: Optional[str] = None,
    action: Optional[str] = None,
):
    rows = _filter(_MOCK_AUDIT, q, action)

    buf = io.StringIO()
    # UTF-8 BOM으로 Excel 한글 호환
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(["시간", "주체", "이메일", "액션", "대상", "IP"])
    for r in rows:
        writer.writerow(
            [r["time"], r["actor"], r["actorEmail"], r["action"], r["target"], r["ip"]]
        )

    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="kotify-audit.csv"',
        },
    )
