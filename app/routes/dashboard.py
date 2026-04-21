"""대시보드 API 라우트 — S1 홈 화면 데이터.

Phase 5a: mock 데이터 반환. Phase 5b에서 실제 DB 쿼리로 교체.
api-contract.md의 GET /api/dashboard 계약을 따른다.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


_MOCK_DASHBOARD = {
    "data": {
        "timeline": {
            "events": [
                {"id": "e1", "time": "08:00", "label": "아침 공지", "state": "done"},
                {"id": "e2", "time": "09:20", "label": "인사팀 공지", "state": "done"},
                {"id": "e3", "time": "10:30", "label": "마케팅 뉴스레터", "state": "done"},
                {"id": "e4", "time": "12:10", "label": "점심 알림", "state": "done"},
                {"id": "e5", "time": "13:40", "label": "회의 리마인더", "state": "done"},
                {"id": "e6", "time": "14:00", "label": "오후 캠페인", "state": "done"},
                {"id": "e7", "time": "16:30", "label": "출퇴근 공지", "state": "scheduled"},
                {"id": "e8", "time": "18:00", "label": "주간 리포트", "state": "scheduled"},
            ],
            "now": "14:02",
        },
        "inbox": {
            "unread": 3,
            "threads": [
                {
                    "id": "t1",
                    "name": "박지훈",
                    "preview": "언제 배송되나요?",
                    "time": "14:02",
                    "unread": True,
                },
                {
                    "id": "t2",
                    "name": "이수진",
                    "preview": "네 확인했습니다 감사합니다",
                    "time": "13:58",
                    "unread": True,
                },
                {
                    "id": "t3",
                    "name": "김민재",
                    "preview": "회의 10분 뒤로 미뤄도 될까요?",
                    "time": "13:42",
                    "unread": True,
                },
                {
                    "id": "t4",
                    "name": "정태영",
                    "preview": "네 알겠습니다",
                    "time": "11:30",
                    "unread": False,
                },
                {
                    "id": "t5",
                    "name": "최서연",
                    "preview": "확인 부탁드려요",
                    "time": "10:15",
                    "unread": False,
                },
            ],
        },
        "kpis": {
            "rcsRate": 72.4,
            "todaySent": 1248,
            "scheduled": 42,
            "todayCost": 83500,
            "monthCost": 2150000,
        },
    }
}


@router.get("/dashboard")
async def get_dashboard() -> dict:
    """대시보드 데이터 반환. Phase 5a는 mock 고정 데이터.

    Returns:
        envelope 형식 `{ data: { timeline, inbox, kpis } }`.
    """
    return _MOCK_DASHBOARD
