"""캠페인 이력 라우트."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_complete, require_user
from app.db import get_db
from app.models import Campaign, Message, User

router = APIRouter(prefix="/campaigns")
templates = Jinja2Templates(directory="app/templates")


def _is_admin(user: User) -> bool:
    try:
        return "admin" in json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        return False


def _can_access_campaign(user: User, campaign: Campaign) -> bool:
    return _is_admin(user) or campaign.created_by == user.sub


@router.get("", response_class=HTMLResponse)
async def campaigns_list(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
    status: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    page: int = Query(1, ge=1),
) -> HTMLResponse:
    """캠페인 목록. viewer는 본인 것만, admin은 전체."""
    stmt = select(Campaign).order_by(Campaign.created_at.desc())

    if not _is_admin(user):
        stmt = stmt.where(Campaign.created_by == user.sub)

    if status:
        stmt = stmt.where(Campaign.state == status)
    if date_from:
        stmt = stmt.where(Campaign.created_at >= date_from)
    if date_to:
        stmt = stmt.where(Campaign.created_at <= date_to + "Z")

    per_page = 20
    offset = (page - 1) * per_page
    total = db.execute(
        select(Campaign.id).where(*stmt.whereclause.clauses if stmt.whereclause is not None else [])
    )
    # 간단하게 전체 조회 후 count
    all_campaigns = list(db.execute(stmt).scalars().all())
    total_count = len(all_campaigns)
    paginated = all_campaigns[offset : offset + per_page]

    try:
        user_roles = json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        user_roles = []

    return templates.TemplateResponse(
        "campaigns/list.html",
        {
            "request": request,
            "user": user,
            "user_roles": user_roles,
            "campaigns": paginated,
            "total_count": total_count,
            "page": page,
            "per_page": per_page,
            "status_filter": status,
            "date_from": date_from,
            "date_to": date_to,
            "is_admin": _is_admin(user),
        },
    )


@router.get("/{campaign_id}", response_class=HTMLResponse)
async def campaign_detail(
    campaign_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """캠페인 상세."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="캠페인을 찾을 수 없습니다.")
    if not _can_access_campaign(user, campaign):
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    try:
        user_roles = json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        user_roles = []

    return templates.TemplateResponse(
        "campaigns/detail.html",
        {
            "request": request,
            "user": user,
            "user_roles": user_roles,
            "campaign": campaign,
            "is_admin": _is_admin(user),
        },
    )


@router.get("/{campaign_id}/recipients", response_class=HTMLResponse)
async def campaign_recipients(
    campaign_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    page: int = Query(1, ge=1),
) -> HTMLResponse:
    """HTMX fragment — 수신자 결과 테이블 (페이지네이션 50건)."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404)
    if not _can_access_campaign(user, campaign):
        raise HTTPException(status_code=403)

    per_page = 50
    offset = (page - 1) * per_page

    messages = list(
        db.execute(
            select(Message)
            .where(Message.campaign_id == campaign_id)
            .order_by(Message.id)
            .offset(offset)
            .limit(per_page)
        ).scalars().all()
    )

    total = db.execute(
        select(Message.id).where(Message.campaign_id == campaign_id)
    )
    # simpler count
    all_msgs = list(db.execute(
        select(Message).where(Message.campaign_id == campaign_id)
    ).scalars().all())
    total_count = len(all_msgs)

    return templates.TemplateResponse(
        "campaigns/_recipients.html",
        {
            "request": request,
            "messages": messages,
            "campaign": campaign,
            "page": page,
            "per_page": per_page,
            "total_count": total_count,
        },
    )


@router.post("/{campaign_id}/refresh", response_class=HTMLResponse)
async def campaign_refresh(
    campaign_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> HTMLResponse:
    """HTMX — 폴링 강제 트리거."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404)
    if not _can_access_campaign(user, campaign):
        raise HTTPException(status_code=403)

    # 폴러에 강제 새로고침 큐 추가
    from app.main import poller
    poller.add_force_refresh(campaign_id)

    return HTMLResponse(
        '<span class="ok">✓ 새로고침 요청됨 (5초 내 반영)</span>'
    )
