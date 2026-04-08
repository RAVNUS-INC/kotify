"""대시보드 라우트."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_complete, require_user
from app.db import get_db
from app.models import Campaign, Message, User
from app.web import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """대시보드 — 최근 캠페인 10건 + 통계."""
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    month_str = now.strftime("%Y-%m")

    # 최근 캠페인 10건
    recent_campaigns = list(
        db.execute(
            select(Campaign)
            .order_by(Campaign.created_at.desc())
            .limit(10)
        ).scalars().all()
    )

    # 오늘 발송 수
    today_count = db.execute(
        select(func.count(Campaign.id)).where(
            Campaign.created_at.like(f"{today_str}%")
        )
    ).scalar_one() or 0

    # 이번 달 누적
    month_count = db.execute(
        select(func.count(Campaign.id)).where(
            Campaign.created_at.like(f"{month_str}%")
        )
    ).scalar_one() or 0

    # 이번 달 총 수신자 수
    month_recipients = db.execute(
        select(func.sum(Campaign.total_count)).where(
            Campaign.created_at.like(f"{month_str}%")
        )
    ).scalar_one() or 0

    try:
        user_roles = json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        user_roles = []

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "user_roles": user_roles,
            "recent_campaigns": recent_campaigns,
            "today_count": today_count,
            "month_count": month_count,
            "month_recipients": month_recipients,
        },
    )
