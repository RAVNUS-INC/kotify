"""대시보드 라우트."""
from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_complete, require_user
from app.db import get_db
from app.models import Campaign, Message, User
from app.web import templates

router = APIRouter()

# 한국 표준시 (KST = UTC+9)
_KST = timezone(timedelta(hours=9))


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """대시보드 — 최근 캠페인 10건 + 통계."""
    # KST 기준 오늘/이번 달 UTC 범위 계산 (I5)
    now_kst = datetime.now(_KST)

    today_start_kst = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start_kst = today_start_kst + timedelta(days=1)
    today_start_utc = today_start_kst.astimezone(timezone.utc).isoformat()
    tomorrow_start_utc = tomorrow_start_kst.astimezone(timezone.utc).isoformat()

    month_start_kst = now_kst.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # 다음 달 1일
    if month_start_kst.month == 12:
        next_month_kst = month_start_kst.replace(year=month_start_kst.year + 1, month=1)
    else:
        next_month_kst = month_start_kst.replace(month=month_start_kst.month + 1)
    month_start_utc = month_start_kst.astimezone(timezone.utc).isoformat()
    next_month_utc = next_month_kst.astimezone(timezone.utc).isoformat()

    # 최근 캠페인 10건
    recent_campaigns = list(
        db.execute(
            select(Campaign)
            .order_by(Campaign.created_at.desc())
            .limit(10)
        ).scalars().all()
    )

    # 오늘 발송 수 (KST 기준)
    today_count = db.execute(
        select(func.count(Campaign.id)).where(
            Campaign.created_at >= today_start_utc,
            Campaign.created_at < tomorrow_start_utc,
        )
    ).scalar_one() or 0

    # 이번 달 누적 (KST 기준)
    month_count = db.execute(
        select(func.count(Campaign.id)).where(
            Campaign.created_at >= month_start_utc,
            Campaign.created_at < next_month_utc,
        )
    ).scalar_one() or 0

    # 이번 달 총 수신자 수 (KST 기준)
    month_recipients = db.execute(
        select(func.sum(Campaign.total_count)).where(
            Campaign.created_at >= month_start_utc,
            Campaign.created_at < next_month_utc,
        )
    ).scalar_one() or 0

    try:
        user_roles = json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        user_roles = []

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "user_roles": user_roles,
            "recent_campaigns": recent_campaigns,
            "today_count": today_count,
            "month_count": month_count,
            "month_recipients": month_recipients,
        },
    )
