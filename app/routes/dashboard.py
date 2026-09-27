"""대시보드 API 라우트 — S1 홈 화면 데이터.

api-contract.md 의 GET /api/dashboard 계약:
    {
      data: {
        timeline: { events: [{id, time, label, state}], now: "HH:MM" },
        inbox:    { unread: int, threads: [{id, name, preview, time, date, unread?}],
                    today: "YYYY-MM-DD" },
        kpis:     { rcsRate, todaySent, scheduled, todayCost, monthCost? }
      }
    }

실데이터 소스:
    - timeline:   `campaigns` 오늘 것 (created_at KST 기준)
    - inbox:      `list_thread_page()` (MT+MO 머지, app/services/chat.py)
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
from app.services.chat import list_thread_page
from app.util.time import fmt_kst_date, fmt_kst_hhmm

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
            # reserve_time 은 오프셋 없는 KST 'YYYY-MM-DD HH:mm'(compose.parse_reserve_time),
            # created_at 은 UTC ISO — 오프셋 없는 값을 KST 로 읽는 공용 파서로 둘 다 읽는다.
            "time": fmt_kst_hhmm(c.reserve_time or c.created_at),
            "label": _campaign_label(c),
            "state": _STATE_MAP.get(c.state, "done"),
        }
        for c in campaigns_today
    ]

    # ── Inbox ────────────────────────────────────────────────────────────────
    # 표시할 5개와 전체 미읽음 건수를 같은 집계에서 가져온다.
    thread_page = list_thread_page(db, limit=5)
    unread_count = thread_page.unread_total
    # threads[].date 와 비교할 기준일(KST) — 대화방 목록 meta.today 처럼 목록을 읽은 뒤에 잰다.
    # 요청 시작 시각(now_kst)으로 잡으면 읽는 사이 자정을 넘겨 기록된 대화가 내일 날짜로 보인다.
    inbox_today = datetime.now(UTC).astimezone(KST).strftime("%Y-%m-%d")

    inbox_threads = [
        {
            "id": f"{t.caller}:{t.phone}",
            "name": t.phone,  # 연락처 이름이 DB 에 없으니 번호로 표시
            "phone": t.phone,
            "preview": (t.last_body or "")[:48],
            # 대화 시각은 msghub 원본(오프셋 없는 KST)이 섞여 대화방 목록과 같은 혼합 포맷 파서로
            # 읽는다 — 예전 로컬 헬퍼(_hhmm_kst, 삭제)는 오프셋 없는 값을 UTC 로 읽어 9시간 늦게 보였다.
            "time": fmt_kst_hhmm(t.last_timestamp),
            "date": fmt_kst_date(t.last_timestamp),
            "unread": t.unread,
        }
        for t in thread_page.threads
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
                "today": inbox_today,
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
