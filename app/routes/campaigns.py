"""캠페인 이력 라우트."""
from __future__ import annotations

import csv
import io
import json
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_complete, require_user
from app.db import get_db
from app.models import Campaign, Message, User
from app.security.csrf import verify_csrf
from app.web import templates

router = APIRouter(prefix="/campaigns")


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
    per_page: int = Query(20),
    sort: str = Query("created_at"),
    order: str = Query("desc"),
) -> HTMLResponse:
    """캠페인 목록. viewer는 본인 것만, admin은 전체. H7 per_page, M16 작성자 email."""
    # H7: per_page clamp
    per_page = max(1, min(per_page, 200))

    # H5: 정렬 컬럼 허용 목록
    _sort_cols = {
        "created_at": Campaign.created_at,
        "ok_count": Campaign.ok_count,
        "fail_count": Campaign.fail_count,
    }
    sort_col = _sort_cols.get(sort, Campaign.created_at)
    sort_expr = sort_col.desc() if order != "asc" else sort_col.asc()
    stmt = select(Campaign).order_by(sort_expr)

    if not _is_admin(user):
        stmt = stmt.where(Campaign.created_by == user.sub)

    if status:
        stmt = stmt.where(Campaign.state == status)
    if date_from:
        stmt = stmt.where(Campaign.created_at >= date_from)
    if date_to:
        # 다음 날 00:00:00 미만으로 비교하여 date_to 당일 전체를 포함 (I6)
        from datetime import datetime, timedelta
        try:
            date_to_dt = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=UTC)
            next_day_dt = date_to_dt + timedelta(days=1)
            stmt = stmt.where(Campaign.created_at < next_day_dt.isoformat())
        except ValueError:
            stmt = stmt.where(Campaign.created_at <= date_to + "T23:59:59.999999+00:00")

    offset = (page - 1) * per_page

    # #14: COUNT 쿼리로 OOM 방지
    total_count = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()

    paginated = list(
        db.execute(stmt.offset(offset).limit(per_page)).scalars().all()
    )

    # M16: 작성자 sub → email 매핑 (admin 전용)
    creator_emails: dict[str, str] = {}
    if _is_admin(user) and paginated:
        subs = list({c.created_by for c in paginated if c.created_by})
        if subs:
            rows = db.execute(
                select(User.sub, User.email).where(User.sub.in_(subs))
            ).all()
            creator_emails = {row[0]: row[1] for row in rows if row[1]}

    try:
        user_roles = json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        user_roles = []

    return templates.TemplateResponse(
        request,
        "campaigns/list.html",
        {
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
            "sort": sort,
            "order": order,
            "creator_emails": creator_emails,
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
    """캠페인 상세. H14: 첫 페이지 수신자를 미리 fetch하여 더블 깜박임 제거."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="캠페인을 찾을 수 없습니다.")
    if not _can_access_campaign(user, campaign):
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    try:
        user_roles = json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        user_roles = []

    # H14: 첫 페이지 수신자 미리 로드 (HTMX는 폴링에만 갱신)
    per_page = 50
    first_page_messages = list(
        db.execute(
            select(Message)
            .where(Message.campaign_id == campaign_id)
            .order_by(Message.id)
            .limit(per_page)
        ).scalars().all()
    )
    total_recipients = db.execute(
        select(func.count()).select_from(
            select(Message).where(Message.campaign_id == campaign_id).subquery()
        )
    ).scalar_one()

    return templates.TemplateResponse(
        request,
        "campaigns/detail.html",
        {
            "user": user,
            "user_roles": user_roles,
            "campaign": campaign,
            "is_admin": _is_admin(user),
            "first_page_messages": first_page_messages,
            "total_recipients": total_recipients,
            "per_page": per_page,
        },
    )


@router.get("/{campaign_id}/progress", response_class=HTMLResponse)
async def campaign_progress(
    campaign_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """진행 카드 fragment (HTMX 폴링용)."""
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404)
    if not _can_access_campaign(user, campaign):
        raise HTTPException(403)
    return templates.TemplateResponse(
        request,
        "campaigns/_progress.html",
        {"campaign": campaign},
    )


@router.get("/{campaign_id}/recipients", response_class=HTMLResponse)
async def campaign_recipients(
    campaign_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
    page: int = Query(1, ge=1),
    status: str | None = Query(None),
) -> HTMLResponse:
    """HTMX fragment — 수신자 결과 테이블 (페이지네이션 50건)."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404)
    if not _can_access_campaign(user, campaign):
        raise HTTPException(status_code=403)

    per_page = 50
    offset = (page - 1) * per_page

    # C2: status 필터 적용
    # fail 필터는 NCP가 명시적으로 fail을 돌려준 경우 + 70분 cutoff로 포기한 경우 모두 포함
    # (사용자 관점에서 둘 다 "성공하지 않은 결과")
    base_stmt = select(Message).where(Message.campaign_id == campaign_id)
    if status == "success":
        base_stmt = base_stmt.where(Message.result_status == "success")
    elif status == "fail":
        base_stmt = base_stmt.where(
            (Message.result_status == "fail")
            | (Message.status == "UNKNOWN")
            | (Message.status == "DELIVERY_UNCONFIRMED")
        )
    elif status == "pending":
        base_stmt = base_stmt.where(Message.status.in_(["PENDING", "READY", "PROCESSING"]))

    total_count = db.execute(
        select(func.count()).select_from(base_stmt.subquery())
    ).scalar_one()

    messages = list(
        db.execute(
            base_stmt.order_by(Message.id).offset(offset).limit(per_page)
        ).scalars().all()
    )

    try:
        user_roles = json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        user_roles = []

    return templates.TemplateResponse(
        request,
        "campaigns/_recipients.html",
        {
            "messages": messages,
            "campaign": campaign,
            "page": page,
            "per_page": per_page,
            "total_count": total_count,
            "status_filter": status,
            "user_roles": user_roles,
        },
    )


@router.get("/{campaign_id}/export")
async def campaign_export(
    campaign_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
    status: str | None = Query(None),
) -> StreamingResponse:
    """C2: 수신자 CSV 다운로드 (status=fail 등 필터 지원)."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404)
    if not _can_access_campaign(user, campaign):
        raise HTTPException(status_code=403)

    base_stmt = select(Message).where(Message.campaign_id == campaign_id)
    if status == "success":
        base_stmt = base_stmt.where(Message.result_status == "success")
    elif status == "fail":
        base_stmt = base_stmt.where(
            (Message.result_status == "fail")
            | (Message.status == "UNKNOWN")
            | (Message.status == "DELIVERY_UNCONFIRMED")
        )
    elif status == "pending":
        base_stmt = base_stmt.where(Message.status.in_(["PENDING", "READY", "PROCESSING"]))

    messages = list(db.execute(base_stmt.order_by(Message.id)).scalars().all())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["번호(정규화)", "원본입력", "상태", "결과코드", "결과메시지", "완료시각"])
    for msg in messages:
        writer.writerow([
            msg.to_number,
            msg.to_number_raw,
            msg.result_status or msg.status,
            msg.result_code or "",
            msg.result_message or "",
            msg.complete_time or "",
        ])

    fname_suffix = f"_{status}" if status else ""
    filename = f"campaign_{campaign_id}{fname_suffix}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/{campaign_id}/refresh", response_class=HTMLResponse)
async def campaign_refresh(
    campaign_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
    _csrf: None = Depends(verify_csrf),
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
