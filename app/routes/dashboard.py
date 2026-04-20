"""대시보드 라우트."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_complete, require_user
from app.db import get_db
from app.models import Caller, Campaign, Contact, User
from app.web import templates

router = APIRouter()

_KST = timezone(timedelta(hours=9))


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """대시보드 — DashForge dashboard-four (Helpdesk) 패턴 기반 SMS 모니터링."""
    now_kst = datetime.now(_KST)

    today_start_kst = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start_kst = today_start_kst + timedelta(days=1)
    today_start_utc = today_start_kst.astimezone(UTC).isoformat()
    tomorrow_start_utc = tomorrow_start_kst.astimezone(UTC).isoformat()

    month_start_kst = now_kst.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start_kst.month == 12:
        next_month_kst = month_start_kst.replace(year=month_start_kst.year + 1, month=1)
    else:
        next_month_kst = month_start_kst.replace(month=month_start_kst.month + 1)
    month_start_utc = month_start_kst.astimezone(UTC).isoformat()
    next_month_utc = next_month_kst.astimezone(UTC).isoformat()

    # 최근 캠페인 10건
    recent_campaigns = list(
        db.execute(
            select(Campaign).order_by(Campaign.created_at.desc()).limit(10)
        ).scalars().all()
    )

    # 오늘 / 이번 달 KPI
    today_count = db.execute(
        select(func.count(Campaign.id)).where(
            Campaign.created_at >= today_start_utc,
            Campaign.created_at < tomorrow_start_utc,
        )
    ).scalar_one() or 0
    month_count = db.execute(
        select(func.count(Campaign.id)).where(
            Campaign.created_at >= month_start_utc,
            Campaign.created_at < next_month_utc,
        )
    ).scalar_one() or 0
    month_recipients = db.execute(
        select(func.sum(Campaign.ok_count)).where(
            Campaign.created_at >= month_start_utc,
            Campaign.created_at < next_month_utc,
        )
    ).scalar_one() or 0
    month_fail = db.execute(
        select(func.sum(Campaign.fail_count)).where(
            Campaign.created_at >= month_start_utc,
            Campaign.created_at < next_month_utc,
        )
    ).scalar_one() or 0
    pending_count = db.execute(
        select(func.count(Campaign.id)).where(
            Campaign.state.in_(["DISPATCHING", "DISPATCHED"])
        )
    ).scalar_one() or 0

    # 시작 체크리스트
    has_callers = db.execute(
        select(func.count(Caller.id)).where(Caller.active == 1)
    ).scalar_one() or 0
    has_contacts = db.execute(
        select(func.count(Contact.id))
    ).scalar_one() or 0

    # RCS 도달률 (이번 달)
    month_rcs_count = db.execute(
        select(func.sum(Campaign.rcs_count)).where(
            Campaign.created_at >= month_start_utc,
            Campaign.created_at < next_month_utc,
        )
    ).scalar_one() or 0
    rcs_rate = round(month_rcs_count / month_recipients * 100) if month_recipients > 0 else 0

    # 24h 실패율
    one_day_ago_utc = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    recent_ok = db.execute(
        select(func.sum(Campaign.ok_count)).where(Campaign.created_at >= one_day_ago_utc)
    ).scalar_one() or 0
    recent_fail = db.execute(
        select(func.sum(Campaign.fail_count)).where(Campaign.created_at >= one_day_ago_utc)
    ).scalar_one() or 0
    total_recent = recent_ok + recent_fail
    fail_rate_24h = round(recent_fail / total_recent * 100, 1) if total_recent > 0 else 0
    success_rate_24h = round(recent_ok / total_recent * 100) if total_recent > 0 else 0

    # 7일 일별 추이 (KST 기준)
    daily_labels: list[str] = []
    daily_ok: list[int] = []
    daily_fail: list[int] = []
    daily_total: list[int] = []
    for offset in range(6, -1, -1):
        day_start_kst = (today_start_kst - timedelta(days=offset))
        day_end_kst = day_start_kst + timedelta(days=1)
        day_start_u = day_start_kst.astimezone(UTC).isoformat()
        day_end_u = day_end_kst.astimezone(UTC).isoformat()
        ok_sum = db.execute(
            select(func.sum(Campaign.ok_count)).where(
                Campaign.created_at >= day_start_u,
                Campaign.created_at < day_end_u,
            )
        ).scalar_one() or 0
        fail_sum = db.execute(
            select(func.sum(Campaign.fail_count)).where(
                Campaign.created_at >= day_start_u,
                Campaign.created_at < day_end_u,
            )
        ).scalar_one() or 0
        total_sum = ok_sum + fail_sum
        daily_labels.append(day_start_kst.strftime("%m/%d"))
        daily_ok.append(int(ok_sum))
        daily_fail.append(int(fail_sum))
        daily_total.append(int(total_sum))

    # 메시지 유형 분포 (이번 달)
    type_rows = db.execute(
        select(Campaign.message_type, func.count(Campaign.id), func.sum(Campaign.total_count)).where(
            Campaign.created_at >= month_start_utc,
            Campaign.created_at < next_month_utc,
        ).group_by(Campaign.message_type)
    ).all()
    type_counts = {"SMS": 0, "LMS": 0, "MMS": 0}
    type_recipients = {"SMS": 0, "LMS": 0, "MMS": 0}
    for mt, cnt, recipients in type_rows:
        if mt in type_counts:
            type_counts[mt] = int(cnt or 0)
            type_recipients[mt] = int(recipients or 0)

    # 상태 분포 (이번 달) — "Current Ticket Status" 섹션용
    state_rows = db.execute(
        select(Campaign.state, func.count(Campaign.id)).where(
            Campaign.created_at >= month_start_utc,
            Campaign.created_at < next_month_utc,
        ).group_by(Campaign.state)
    ).all()
    state_counts: dict[str, int] = {}
    for st, cnt in state_rows:
        state_counts[st] = int(cnt or 0)
    completed_count = state_counts.get("COMPLETED", 0)
    failed_count = state_counts.get("FAILED", 0) + state_counts.get("PARTIAL_FAILED", 0)
    dispatching_count = state_counts.get("DISPATCHING", 0) + state_counts.get("DISPATCHED", 0)
    reserved_count = state_counts.get("RESERVED", 0)

    # Top 5 발신자 (이번 달) — "Agent Performance" 섹션용
    top_sender_rows = db.execute(
        select(
            Campaign.created_by,
            func.count(Campaign.id).label("campaign_count"),
            func.sum(Campaign.ok_count).label("total_ok"),
        ).where(
            Campaign.created_at >= month_start_utc,
            Campaign.created_at < next_month_utc,
        ).group_by(Campaign.created_by).order_by(func.sum(Campaign.ok_count).desc()).limit(5)
    ).all()
    top_senders = []
    if top_sender_rows:
        sender_subs = [row[0] for row in top_sender_rows]
        sender_users = {
            u.sub: u
            for u in db.execute(select(User).where(User.sub.in_(sender_subs))).scalars().all()
        }
        max_ok = max((row[2] or 0) for row in top_sender_rows) or 1
        for sub, cnt, total_ok in top_sender_rows:
            u = sender_users.get(sub)
            total_ok = int(total_ok or 0)
            top_senders.append({
                "sub": sub,
                "name": (u.name if u and u.name else (u.email if u else sub[:10])),
                "email": u.email if u else "",
                "campaign_count": int(cnt or 0),
                "total_ok": total_ok,
                "percent": round(total_ok / max_ok * 100) if max_ok > 0 else 0,
            })

    # 상태 분포 (Customer Satisfaction 섹션 스타일로)
    _total_state = sum(state_counts.values()) or 1
    state_breakdown = [
        ("COMPLETED", "완료", "bd-primary", state_counts.get("COMPLETED", 0)),
        ("DISPATCHED", "발송됨", "bd-success", state_counts.get("DISPATCHED", 0)),
        ("DISPATCHING", "발송중", "bd-warning", state_counts.get("DISPATCHING", 0)),
        ("PARTIAL_FAILED", "부분실패", "bd-pink", state_counts.get("PARTIAL_FAILED", 0)),
        ("FAILED", "실패", "bd-teal", state_counts.get("FAILED", 0)),
        ("RESERVED", "예약", "bd-purple", state_counts.get("RESERVED", 0)),
    ]
    state_breakdown = [
        {"code": code, "label": label, "color": color, "count": cnt, "percent": round(cnt / _total_state * 100) if _total_state > 0 else 0}
        for code, label, color, cnt in state_breakdown
    ]

    # 최근 활동 — recent_campaigns[:5]를 activity 포맷으로
    recent_activities = []
    for c in recent_campaigns[:5]:
        if c.state == "COMPLETED":
            icon, icon_bg, icon_color = "check-circle", "bg-success-light", "tx-success"
            msg = f"캠페인 #{c.id} 완료 ({c.ok_count}/{c.total_count}명 성공)"
        elif c.state == "FAILED":
            icon, icon_bg, icon_color = "x-circle", "bg-pink-light", "tx-pink"
            msg = f"캠페인 #{c.id} 실패"
        elif c.state == "PARTIAL_FAILED":
            icon, icon_bg, icon_color = "alert-triangle", "bg-warning-light", "tx-orange"
            msg = f"캠페인 #{c.id} 부분 실패 ({c.fail_count}건 실패)"
        elif c.state in ("DISPATCHING", "DISPATCHED"):
            icon, icon_bg, icon_color = "send", "bg-primary-light", "tx-primary"
            msg = f"캠페인 #{c.id} 발송 중 ({c.total_count}명)"
        elif c.state == "RESERVED":
            icon, icon_bg, icon_color = "clock", "bg-indigo-light", "tx-indigo"
            msg = f"캠페인 #{c.id} 예약됨"
        else:
            icon, icon_bg, icon_color = "circle", "bg-gray-100", "tx-color-03"
            msg = f"캠페인 #{c.id} — {c.state}"
        recent_activities.append({
            "id": c.id,
            "icon": icon,
            "icon_bg": icon_bg,
            "icon_color": icon_color,
            "message": msg,
            "timestamp": c.created_at,
            "message_type": c.message_type,
        })

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
            "month_fail": month_fail,
            "pending_count": pending_count,
            "has_callers": has_callers,
            "has_contacts": has_contacts,
            "fail_rate_24h": fail_rate_24h,
            "success_rate_24h": success_rate_24h,
            "recent_fail": recent_fail,
            "rcs_rate": rcs_rate,
            # 차트용
            "daily_labels": daily_labels,
            "daily_ok": daily_ok,
            "daily_fail": daily_fail,
            "daily_total": daily_total,
            # 유형 분포
            "type_counts": type_counts,
            "type_recipients": type_recipients,
            # 상태
            "completed_count": completed_count,
            "failed_count": failed_count,
            "dispatching_count": dispatching_count,
            "reserved_count": reserved_count,
            "state_counts": state_counts,
            "state_breakdown": state_breakdown,
            # 활동/리더보드
            "recent_activities": recent_activities,
            "top_senders": top_senders,
        },
    )
