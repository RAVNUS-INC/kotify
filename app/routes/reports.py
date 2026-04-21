"""리포트 API — S16.

Phase 9b: mock 고정 데이터 (기간·캠페인 필터는 받지만 결과 동일).
Phase 후속에서 실제 집계 쿼리 + 기간 윈도우 반영.
"""
from __future__ import annotations

import csv
import io
from typing import List, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.auth.deps import require_setup_complete, require_user

router = APIRouter(
    dependencies=[Depends(require_user), Depends(require_setup_complete)],
)


from app.util.csv_safe import safe_csv_cell as _safe


_MOCK_REPORT: dict = {
    "kpis": {
        "totalSent": {
            "value": 13420,
            "delta": "+2.1%",
            "deltaDir": "up",
            "spark": [1800, 1920, 1700, 2100, 2300, 2050, 1850],
        },
        "avgDeliveryRate": {
            "value": 94.5,
            "delta": "+0.8p",
            "deltaDir": "up",
            "spark": [93.2, 93.8, 94.1, 94.3, 94.0, 94.5, 94.8],
        },
        "replies": {
            "value": 312,
            "delta": "-3.4%",
            "deltaDir": "down",
            "spark": [50, 42, 48, 55, 38, 40, 45],
        },
        "cost": {
            "value": 890000,
            "delta": "+5.2%",
            "deltaDir": "up",
            "spark": [110000, 125000, 118000, 130000, 135000, 128000, 125000],
        },
    },
    "daily": {
        "labels": ["월", "화", "수", "목", "금", "토", "일"],
        "sent": [1800, 1920, 1700, 2100, 2300, 2050, 1850],
        "reply": [50, 42, 48, 55, 38, 40, 45],
    },
    "channels": {
        "rcs": {"count": 8052, "rate": 60.0},
        "sms": {"count": 4026, "rate": 30.0},
        "lms": {"count": 1074, "rate": 8.0},
        "kakao": {"count": 268, "rate": 2.0},
    },
    "topCampaigns": [
        {"id": "c-011", "name": "카톡 이벤트 안내", "sent": 456, "replyRate": 3.3},
        {"id": "c-001", "name": "4월 공지사항", "sent": 342, "replyRate": 3.5},
        {"id": "c-002", "name": "마케팅 뉴스레터 #12", "sent": 500, "replyRate": 0.6},
        {"id": "c-012", "name": "단체 회식 공지", "sent": 142, "replyRate": 7.7},
        {"id": "c-004", "name": "인사팀 공지", "sent": 124, "replyRate": 6.4},
    ],
}


@router.get("/reports")
async def get_reports(
    from_: Optional[str] = None,
    to: Optional[str] = None,
    campaignId: Optional[str] = None,
) -> dict:
    """리포트 데이터. 현재는 파라미터 무시하고 mock 고정값 반환."""
    return {"data": _MOCK_REPORT}


@router.get("/reports/export.csv")
async def export_reports_csv(
    from_: Optional[str] = None,
    to: Optional[str] = None,
):
    """일별 발송·회신·회신률 CSV. formula-safe."""
    daily = _MOCK_REPORT["daily"]
    labels: List[str] = daily["labels"]
    sent_arr: List[int] = daily["sent"]
    reply_arr: List[int] = daily["reply"]

    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(["날짜", "발송", "회신", "회신률"])
    for i, label in enumerate(labels):
        sent = sent_arr[i] if i < len(sent_arr) else 0
        reply = reply_arr[i] if i < len(reply_arr) else 0
        rate = f"{(reply / sent * 100):.2f}%" if sent > 0 else "0.00%"
        writer.writerow([_safe(label), str(sent), str(reply), _safe(rate)])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="kotify-reports.csv"',
        },
    )
