"""리포트 API — S16.

실 DB (campaigns + messages + mo_messages) 기간 집계.

api-contract.md §S16 — web/types/report.ts ReportData shape.

기간 규약:
    from/to 없으면 "지난 7일 (KST 자정 기준)".
    from/to 있으면 'YYYY-MM-DD' (KST) 로 해석. to 는 inclusive (내일 0시까지).
델타 비교: 동일 길이의 직전 구간과 비교 (예: 7일 → 직전 7일).

channel 매핑 (TS 계약과의 간극):
    msghub Message.channel = RCS | SMS | LMS | MMS (kakao 미지원)
    TS = rcs | sms | lms | kakao
    → MMS 는 lms 버킷에 합산 (둘 다 multimedia/장문 계열). kakao=0 유지.
"""
from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import and_, case, func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_complete, require_user
from app.db import get_db
from app.models import Campaign, Message, MoMessage
from app.msghub.codes import SUCCESS_CODE
from app.util.csv_safe import safe_csv_cell as _safe

router = APIRouter(
    dependencies=[Depends(require_user), Depends(require_setup_complete)],
)

KST = ZoneInfo("Asia/Seoul")


# ── 기간 파싱 ────────────────────────────────────────────────────────────────


def _parse_yyyymmdd_kst(s: str) -> datetime | None:
    """'YYYY-MM-DD' (KST) → KST 자정 aware datetime. 실패 시 None."""
    try:
        d = datetime.strptime(s, "%Y-%m-%d")
        return d.replace(tzinfo=KST)
    except (ValueError, TypeError):
        return None


def _period_window(
    from_: Optional[str], to: Optional[str]
) -> tuple[datetime, datetime, int]:
    """조회 윈도우 (KST) → (start_kst, end_kst, days).

    기본값: 오늘 자정 - 7일 ~ 오늘 자정 (미래 미포함).
    to 는 inclusive 로 취급 → 내부적으로 to+1 을 exclusive upper bound 로.
    """
    now_kst = datetime.now(UTC).astimezone(KST)
    today_mid = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)

    start: datetime | None = _parse_yyyymmdd_kst(from_) if from_ else None
    end: datetime | None = _parse_yyyymmdd_kst(to) if to else None
    if end is not None:
        end = end + timedelta(days=1)  # inclusive → exclusive

    if start is None and end is None:
        end = today_mid + timedelta(days=1)  # 오늘 끝까지 포함
        start = end - timedelta(days=7)
    elif start is None:
        start = end - timedelta(days=7)
    elif end is None:
        end = start + timedelta(days=7)

    if end <= start:
        # 잘못된 입력 → 기본 7일로 대체.
        end = today_mid + timedelta(days=1)
        start = end - timedelta(days=7)

    days = max(1, (end - start).days)
    return start, end, days


def _kst_to_utc_iso(dt: datetime) -> str:
    """KST aware datetime → UTC ISO (DB 비교용)."""
    return dt.astimezone(UTC).isoformat()


# ── 집계 쿼리 ────────────────────────────────────────────────────────────────


def _kpis_totals(db: Session, start: datetime, end: datetime) -> dict:
    """기간 내 SUM(total_count), SUM(ok_count), SUM(cost) 등."""
    s = _kst_to_utc_iso(start)
    e = _kst_to_utc_iso(end)
    row = db.execute(
        select(
            func.coalesce(func.sum(Campaign.total_count), 0).label("total_sent"),
            func.coalesce(func.sum(Campaign.ok_count), 0).label("ok"),
            func.coalesce(func.sum(Campaign.total_cost), 0).label("cost"),
        ).where(and_(Campaign.created_at >= s, Campaign.created_at < e))
    ).one()
    return {
        "total_sent": int(row.total_sent or 0),
        "ok": int(row.ok or 0),
        "cost": int(row.cost or 0),
    }


def _replies_count(db: Session, start: datetime, end: datetime) -> int:
    """기간 내 MO 수신 건수 — MoMessage.received_at 기준.

    received_at 은 우리 서버가 webhook 수신 시 _now_iso() (UTC, '+00:00') 로
    기록해 ISO 문자열 비교가 안전. mo_recv_dt 는 msghub 원본이라 naive 거나
    타임존 포맷이 섞여 lexicographic 비교가 불안전.
    """
    s = _kst_to_utc_iso(start)
    e = _kst_to_utc_iso(end)
    val = db.execute(
        select(func.count(MoMessage.id)).where(
            and_(MoMessage.received_at >= s, MoMessage.received_at < e)
        )
    ).scalar_one()
    return int(val or 0)


def _daily_sent(db: Session, start: datetime, end: datetime) -> dict[str, int]:
    """일자별 sent(발송 시도 = SUM(total_count)). key='YYYY-MM-DD' (KST)."""
    s = _kst_to_utc_iso(start)
    e = _kst_to_utc_iso(end)
    # SQLite/Postgres 호환 위해 python 레벨 집계 — row 수가 적을 전제 (기간당 수백).
    rows = db.execute(
        select(Campaign.created_at, Campaign.total_count)
        .where(and_(Campaign.created_at >= s, Campaign.created_at < e))
    ).all()
    out: dict[str, int] = {}
    for created_at, total in rows:
        if not created_at:
            continue
        try:
            dt = datetime.fromisoformat(created_at)
        except (ValueError, TypeError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        key = dt.astimezone(KST).strftime("%Y-%m-%d")
        out[key] = out.get(key, 0) + int(total or 0)
    return out


def _daily_replies(db: Session, start: datetime, end: datetime) -> dict[str, int]:
    """일자별 reply(MO) count. MoMessage.received_at 기준 (UTC-aware)."""
    s = _kst_to_utc_iso(start)
    e = _kst_to_utc_iso(end)
    rows = db.execute(
        select(MoMessage.received_at)
        .where(and_(MoMessage.received_at >= s, MoMessage.received_at < e))
    ).all()
    out: dict[str, int] = {}
    for (recv,) in rows:
        if not recv:
            continue
        try:
            dt = datetime.fromisoformat(recv)
        except (ValueError, TypeError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        key = dt.astimezone(KST).strftime("%Y-%m-%d")
        out[key] = out.get(key, 0) + 1
    return out


def _channels_breakdown(
    db: Session, start: datetime, end: datetime
) -> dict[str, dict]:
    """Message.channel 별 DONE+SUCCESS 카운트. MMS 는 lms 버킷으로 합산."""
    s = _kst_to_utc_iso(start)
    e = _kst_to_utc_iso(end)
    rows = db.execute(
        select(Message.channel, func.count(Message.id).label("c"))
        .join(Campaign, Campaign.id == Message.campaign_id)
        .where(
            and_(
                Campaign.created_at >= s,
                Campaign.created_at < e,
                Message.status == "DONE",
                Message.result_code == SUCCESS_CODE,
            )
        )
        .group_by(Message.channel)
    ).all()

    buckets = {"rcs": 0, "sms": 0, "lms": 0, "kakao": 0}
    for ch, c in rows:
        chu = (ch or "").upper()
        if chu == "RCS":
            buckets["rcs"] += int(c or 0)
        elif chu == "SMS":
            buckets["sms"] += int(c or 0)
        elif chu in ("LMS", "MMS"):  # MMS → lms 버킷 병합
            buckets["lms"] += int(c or 0)
        elif chu == "KAKAO":
            buckets["kakao"] += int(c or 0)

    total = sum(buckets.values())
    out: dict[str, dict] = {}
    for k, v in buckets.items():
        rate = round((v / total * 100), 1) if total > 0 else 0.0
        out[k] = {"count": v, "rate": rate}
    return out


def _top_campaigns(
    db: Session, start: datetime, end: datetime, limit: int = 5
) -> list[dict]:
    """기간 내 total_count DESC top N. 회신률은 ok_count 기반 추정 제한."""
    s = _kst_to_utc_iso(start)
    e = _kst_to_utc_iso(end)
    # 회신(MO) 을 campaign 에 직결할 수 없어 reply 는 같은 caller 기간 MO 의
    # 비율을 추정. 여기서는 일단 reply_rate = 0 (MVP). 프론트는 0 이면
    # "—" 등으로 표현할 수 있다.
    rows = db.execute(
        select(
            Campaign.id,
            Campaign.subject,
            Campaign.content,
            Campaign.total_count,
        )
        .where(and_(Campaign.created_at >= s, Campaign.created_at < e))
        # Campaign.total_count 은 NOT NULL (default 0) 이라 NULLS LAST 불요.
        # 동일 total_count 는 id DESC 로 tiebreak.
        .order_by(Campaign.total_count.desc(), Campaign.id.desc())
        .limit(limit)
    ).all()
    out: list[dict] = []
    for r in rows:
        if r.subject:
            name = r.subject
        elif r.content:
            first = r.content.strip().split("\n", 1)[0]
            name = first[:24] + ("…" if len(first) > 24 else "")
        else:
            name = f"캠페인 #{r.id}"
        out.append({
            "id": str(r.id),
            "name": name,
            "sent": int(r.total_count or 0),
            "replyRate": 0.0,  # Phase 후속에서 정확 연결 예정
        })
    return out


# ── 포맷 헬퍼 ────────────────────────────────────────────────────────────────


def _delta(
    current: float, previous: float, *, is_percent: bool = False
) -> tuple[str, str]:
    """(delta_str, direction) 생성.

    - is_percent=False → '+N.N%' (비율 변화)
    - is_percent=True  → '+N.Np' (퍼센트 포인트 변화)

    previous==0 이면 비율 정의가 불가능 — 유한한 상한(+999.9%)으로 표기해
    프론트 배지가 항상 렌더 가능하도록 한다 ('∞' 같은 특수문자 폰트 호환
    문제 회피).
    """
    if current == previous:
        return ("0.0p" if is_percent else "0.0%", "flat")
    if previous == 0:
        # '이전 기간 0, 현재 증가' 는 신규 유입으로 간주 — 상한 표시.
        return (
            "+100.0p" if is_percent else "+999.9%",
            "up" if current > 0 else "down",
        )
    if is_percent:
        diff = current - previous
        return (f"{diff:+.1f}p", "up" if diff > 0 else "down")
    pct = (current - previous) / previous * 100
    return (f"{pct:+.1f}%", "up" if pct > 0 else "down")


def _build_spark(
    daily_sent_now: dict[str, int],
    start: datetime,
    days: int,
) -> list[int]:
    """최근 days 일의 일별 sent 값을 순서대로 리턴 (작은→큰 날짜)."""
    out: list[int] = []
    for i in range(days):
        d = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        out.append(int(daily_sent_now.get(d, 0)))
    return out


def _spark_rate(
    sent_by_day: dict[str, int],
    ok_by_day: dict[str, int],
    start: datetime,
    days: int,
) -> list[float]:
    """일별 delivery rate spark."""
    out: list[float] = []
    for i in range(days):
        d = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        sent = sent_by_day.get(d, 0)
        ok = ok_by_day.get(d, 0)
        out.append(round(ok / sent * 100, 1) if sent > 0 else 0.0)
    return out


def _daily_ok(db: Session, start: datetime, end: datetime) -> dict[str, int]:
    """일별 ok_count (성공 발송)."""
    s = _kst_to_utc_iso(start)
    e = _kst_to_utc_iso(end)
    rows = db.execute(
        select(Campaign.created_at, Campaign.ok_count)
        .where(and_(Campaign.created_at >= s, Campaign.created_at < e))
    ).all()
    out: dict[str, int] = {}
    for created_at, ok in rows:
        if not created_at:
            continue
        try:
            dt = datetime.fromisoformat(created_at)
        except (ValueError, TypeError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        key = dt.astimezone(KST).strftime("%Y-%m-%d")
        out[key] = out.get(key, 0) + int(ok or 0)
    return out


# ── 라우트 ───────────────────────────────────────────────────────────────────


@router.get("/reports")
def get_reports(
    from_: Optional[str] = None,
    to: Optional[str] = None,
    campaignId: Optional[str] = None,
    db: Session = Depends(get_db),
) -> dict:
    """리포트 데이터. from/to 는 KST 'YYYY-MM-DD'. 기본 최근 7일."""
    del campaignId  # 캠페인 단일 필터는 S16 범위 밖 — 필요 시 후속.

    start, end, days = _period_window(from_, to)
    prev_end = start
    prev_start = prev_end - timedelta(days=days)

    # 현재 구간 집계
    tot = _kpis_totals(db, start, end)
    replies = _replies_count(db, start, end)
    daily_sent_map = _daily_sent(db, start, end)
    daily_ok_map = _daily_ok(db, start, end)
    daily_reply_map = _daily_replies(db, start, end)

    # 직전 구간 집계 (델타 계산용)
    prev_tot = _kpis_totals(db, prev_start, prev_end)
    prev_replies = _replies_count(db, prev_start, prev_end)

    # KPIs
    rate_now = (tot["ok"] / tot["total_sent"] * 100) if tot["total_sent"] > 0 else 0.0
    rate_prev = (
        (prev_tot["ok"] / prev_tot["total_sent"] * 100)
        if prev_tot["total_sent"] > 0
        else 0.0
    )

    d_sent, dir_sent = _delta(tot["total_sent"], prev_tot["total_sent"])
    d_rate, dir_rate = _delta(rate_now, rate_prev, is_percent=True)
    d_rep, dir_rep = _delta(replies, prev_replies)
    d_cost, dir_cost = _delta(tot["cost"], prev_tot["cost"])

    kpis = {
        "totalSent": {
            "value": tot["total_sent"],
            "delta": d_sent,
            "deltaDir": dir_sent,
            "spark": _build_spark(daily_sent_map, start, days),
        },
        "avgDeliveryRate": {
            "value": round(rate_now, 1),
            "delta": d_rate,
            "deltaDir": dir_rate,
            "spark": _spark_rate(daily_sent_map, daily_ok_map, start, days),
        },
        "replies": {
            "value": replies,
            "delta": d_rep,
            "deltaDir": dir_rep,
            "spark": _build_spark(daily_reply_map, start, days),
        },
        "cost": {
            "value": tot["cost"],
            "delta": d_cost,
            "deltaDir": dir_cost,
            # cost 의 spark 는 일별 cost 합계 — Campaign.total_cost 기반.
            "spark": _daily_cost_spark(db, start, end, days),
        },
    }

    # daily labels (요일 or 날짜 — 기간에 따라 분기)
    labels = _daily_labels(start, days)
    daily = {
        "labels": labels,
        "sent": _build_spark(daily_sent_map, start, days),
        "reply": _build_spark(daily_reply_map, start, days),
    }

    channels = _channels_breakdown(db, start, end)
    top = _top_campaigns(db, start, end, limit=5)

    return {
        "data": {
            "kpis": kpis,
            "daily": daily,
            "channels": channels,
            "topCampaigns": top,
        }
    }


def _daily_cost_spark(
    db: Session, start: datetime, end: datetime, days: int
) -> list[int]:
    """일별 total_cost 합계 spark."""
    s = _kst_to_utc_iso(start)
    e = _kst_to_utc_iso(end)
    rows = db.execute(
        select(Campaign.created_at, Campaign.total_cost)
        .where(and_(Campaign.created_at >= s, Campaign.created_at < e))
    ).all()
    daily: dict[str, int] = {}
    for created_at, cost in rows:
        if not created_at:
            continue
        try:
            dt = datetime.fromisoformat(created_at)
        except (ValueError, TypeError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        key = dt.astimezone(KST).strftime("%Y-%m-%d")
        daily[key] = daily.get(key, 0) + int(cost or 0)
    out: list[int] = []
    for i in range(days):
        d = (start + timedelta(days=i)).strftime("%Y-%m-%d")
        out.append(int(daily.get(d, 0)))
    return out


def _daily_labels(start: datetime, days: int) -> list[str]:
    """label: 7일 이하면 요일, 초과면 'MM-DD'."""
    dow = ["월", "화", "수", "목", "금", "토", "일"]
    out: list[str] = []
    for i in range(days):
        d = start + timedelta(days=i)
        if days <= 7:
            out.append(dow[d.weekday()])
        else:
            out.append(d.strftime("%m-%d"))
    return out


@router.get("/reports/export.csv")
def export_reports_csv(
    from_: Optional[str] = None,
    to: Optional[str] = None,
    db: Session = Depends(get_db),
) -> Response:
    """일별 발송·회신·회신률 CSV. formula-safe."""
    start, end, days = _period_window(from_, to)
    labels = _daily_labels(start, days)
    sent_arr = _build_spark(_daily_sent(db, start, end), start, days)
    reply_arr = _build_spark(_daily_replies(db, start, end), start, days)

    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(["날짜", "발송", "회신", "회신률"])
    for i, label in enumerate(labels):
        sent = sent_arr[i]
        reply = reply_arr[i]
        rate = f"{(reply / sent * 100):.2f}%" if sent > 0 else "0.00%"
        writer.writerow([_safe(label), str(sent), str(reply), _safe(rate)])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="kotify-reports.csv"'},
    )
