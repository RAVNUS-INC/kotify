"""대시보드 API 라우트 — S1 홈 화면 데이터.

api-contract.md 의 GET /api/dashboard 계약:
    {
      data: {
        timeline: { events: [{id, time, label, state}], now: "HH:MM" },
        inbox:    { unread: int, threads: [{id, name, preview, time, unread?}] },
        kpis:     { rcsRate, todaySent, scheduled, todayCost, monthCost? }
      }
    }

실데이터 소스:
    - timeline:   `campaigns` 오늘 것 (created_at KST 기준)
    - inbox:      `list_threads()` (MT+MO 머지, app/services/chat.py)
    - kpis:       `messages` / `campaigns` 집계
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_complete, require_user
from app.db import get_db
from app.models import Campaign, Message
from app.msghub.codes import SUCCESS_CODE
from app.services.chat import list_threads

router = APIRouter(
    dependencies=[Depends(require_user), Depends(require_setup_complete)],
)

KST = ZoneInfo("Asia/Seoul")


# ── 상태 매핑: Campaign.state → timeline event state ─────────────────────────
_STATE_MAP = {
    "DISPATCHED": "done",
    "COMPLETED": "done",
    "DISPATCHING": "done",
    "PARTIAL_FAILED": "failed",
    "FAILED": "failed",
    "RESERVE_FAILED": "failed",
    "RESERVED": "scheduled",
    "RESERVE_CANCELED": "scheduled",
}


def _kst_day_range(now_utc: datetime) -> tuple[str, str]:
    """오늘 00:00 KST ~ 내일 00:00 KST 를 UTC ISO 문자열로 반환."""
    now_kst = now_utc.astimezone(KST)
    start_kst = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    end_kst = start_kst + timedelta(days=1)
    return start_kst.astimezone(UTC).isoformat(), end_kst.astimezone(UTC).isoformat()


def _kst_month_range(now_utc: datetime) -> tuple[str, str]:
    """이번 달 1일 00:00 KST ~ 다음 달 1일 00:00 KST (UTC ISO)."""
    now_kst = now_utc.astimezone(KST)
    start_kst = now_kst.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start_kst.month == 12:
        end_kst = start_kst.replace(year=start_kst.year + 1, month=1)
    else:
        end_kst = start_kst.replace(month=start_kst.month + 1)
    return start_kst.astimezone(UTC).isoformat(), end_kst.astimezone(UTC).isoformat()


def _hhmm_kst(iso_utc: str | None) -> str:
    """UTC ISO 문자열을 KST HH:MM 으로 변환. 실패 시 빈 문자열."""
    if not iso_utc:
        return ""
    try:
        dt = datetime.fromisoformat(iso_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(KST).strftime("%H:%M")
    except (ValueError, TypeError):
        return ""


def _campaign_label(c: Campaign) -> str:
    """타임라인 이벤트 표시 라벨. subject 우선, 없으면 content 앞 24자."""
    if c.subject:
        return c.subject
    if c.content:
        s = c.content.strip().split("\n", 1)[0]
        return s[:24] + ("…" if len(s) > 24 else "")
    return f"캠페인 #{c.id}"


@router.get("/dashboard")
def get_dashboard(db: Session = Depends(get_db)) -> dict:
    """대시보드 데이터 반환 — 실 DB 집계.

    Returns:
        envelope `{ data: { timeline, inbox, kpis } }`.
    """
    now_utc = datetime.now(UTC)
    now_kst = now_utc.astimezone(KST)
    day_start, day_end = _kst_day_range(now_utc)
    month_start, month_end = _kst_month_range(now_utc)

    # ── Timeline ─────────────────────────────────────────────────────────────
    # 오늘 생성된 캠페인 최근 순 최대 8개.
    campaigns_today = (
        db.execute(
            select(Campaign)
            .where(
                and_(
                    Campaign.created_at >= day_start,
                    Campaign.created_at < day_end,
                )
            )
            .order_by(Campaign.created_at.asc())
            .limit(8)
        )
        .scalars()
        .all()
    )
    events = [
        {
            "id": f"c{c.id}",
            "time": _hhmm_kst(c.reserve_time or c.created_at),
            "label": _campaign_label(c),
            "state": _STATE_MAP.get(c.state, "done"),
        }
        for c in campaigns_today
    ]

    # ── Inbox ────────────────────────────────────────────────────────────────
    # list_threads() 는 MT+MO 를 머지해 최근 활동순 반환. 상위 5개 + 미답 count.
    threads_all, _ = list_threads(db, limit=200, offset=0)
    unread_count = sum(1 for t in threads_all if t.unanswered)

    inbox_threads = [
        {
            "id": f"{t.caller}:{t.phone}",
            "name": t.phone,  # 연락처 이름이 DB 에 없으니 번호로 표시
            "preview": (t.last_body or "")[:48],
            "time": _hhmm_kst(t.last_timestamp),
            "unread": t.unanswered,
        }
        for t in threads_all[:5]
    ]

    # ── KPIs ─────────────────────────────────────────────────────────────────
    # 오늘 발송한 메시지 집계 — 캠페인이 오늘 생성된 것만.
    today_msg_query = (
        select(
            func.count(Message.id).label("total"),
            func.sum(
                case(
                    (
                        and_(
                            Message.channel == "RCS",
                            Message.result_code == SUCCESS_CODE,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("rcs_success"),
            func.sum(
                case(
                    (Message.result_code == SUCCESS_CODE, 1),
                    else_=0,
                )
            ).label("ok"),
            func.coalesce(func.sum(Message.cost), 0).label("cost_sum"),
        )
        .join(Campaign, Campaign.id == Message.campaign_id)
        .where(
            and_(
                Campaign.created_at >= day_start,
                Campaign.created_at < day_end,
            )
        )
    )
    today_row = db.execute(today_msg_query).one()
    today_sent = int(today_row.total or 0)
    today_ok = int(today_row.ok or 0)
    rcs_success = int(today_row.rcs_success or 0)
    rcs_rate = round((rcs_success / today_ok * 100), 1) if today_ok > 0 else 0.0

    # 이번 달 비용 — messages 기반 (campaigns.total_cost 는 뒤늦게 update 될 수 있음).
    month_cost = int(
        db.execute(
            select(func.coalesce(func.sum(Message.cost), 0))
            .join(Campaign, Campaign.id == Message.campaign_id)
            .where(
                and_(
                    Campaign.created_at >= month_start,
                    Campaign.created_at < month_end,
                )
            )
        ).scalar()
        or 0
    )

    # 예약 대기 건수 — 전체 기간 RESERVED 상태 캠페인.
    scheduled_count = int(
        db.execute(
            select(func.count(Campaign.id)).where(Campaign.state == "RESERVED")
        ).scalar()
        or 0
    )

    return {
        "data": {
            "timeline": {
                "events": events,
                "now": now_kst.strftime("%H:%M"),
            },
            "inbox": {
                "unread": unread_count,
                "threads": inbox_threads,
            },
            "kpis": {
                "rcsRate": rcs_rate,
                "todaySent": today_sent,
                "scheduled": scheduled_count,
                "todayCost": int(today_row.cost_sum or 0),
                "monthCost": month_cost,
            },
        }
    }
