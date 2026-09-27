"""대시보드 KST 경계 케이스 테스트."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from app.models import Campaign
from app.routes import dashboard

_KST = timezone(timedelta(hours=9))


def _kst_range_for_today(now_kst: datetime):
    """KST 기준 오늘의 UTC 시작/끝 범위를 반환한다."""
    today_start_kst = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start_kst = today_start_kst + timedelta(days=1)
    return (
        today_start_kst.astimezone(UTC),
        tomorrow_start_kst.astimezone(UTC),
    )


def _kst_range_for_month(now_kst: datetime):
    """KST 기준 이번 달의 UTC 시작/끝 범위를 반환한다."""
    month_start_kst = now_kst.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start_kst.month == 12:
        next_month_kst = month_start_kst.replace(year=month_start_kst.year + 1, month=1)
    else:
        next_month_kst = month_start_kst.replace(month=month_start_kst.month + 1)
    return (
        month_start_kst.astimezone(UTC),
        next_month_kst.astimezone(UTC),
    )


def test_kst_today_range_midnight_boundary():
    """KST 자정(00:00 KST = 15:00 UTC 전날)이 올바른 UTC 범위를 산출한다."""
    # KST 2026-04-08 00:00:00
    now_kst = datetime(2026, 4, 8, 0, 0, 0, tzinfo=_KST)
    start_utc, end_utc = _kst_range_for_today(now_kst)

    # KST 00:00 = UTC 전날 15:00
    assert start_utc == datetime(2026, 4, 7, 15, 0, 0, tzinfo=UTC)
    assert end_utc == datetime(2026, 4, 8, 15, 0, 0, tzinfo=UTC)


def test_kst_today_range_afternoon():
    """KST 오후(14:00 KST = 05:00 UTC)의 UTC 범위."""
    now_kst = datetime(2026, 4, 8, 14, 0, 0, tzinfo=_KST)
    start_utc, end_utc = _kst_range_for_today(now_kst)

    assert start_utc == datetime(2026, 4, 7, 15, 0, 0, tzinfo=UTC)
    assert end_utc == datetime(2026, 4, 8, 15, 0, 0, tzinfo=UTC)


def test_kst_month_range_december():
    """12월의 다음 달 계산이 올바른지 확인 (연도 넘김)."""
    now_kst = datetime(2026, 12, 15, 12, 0, 0, tzinfo=_KST)
    start_utc, end_utc = _kst_range_for_month(now_kst)

    # 12월 1일 00:00 KST = 11월 30일 15:00 UTC
    assert start_utc == datetime(2026, 11, 30, 15, 0, 0, tzinfo=UTC)
    # 2027년 1월 1일 00:00 KST = 2026년 12월 31일 15:00 UTC
    assert end_utc == datetime(2026, 12, 31, 15, 0, 0, tzinfo=UTC)


def test_kst_month_range_regular():
    """일반 월 범위 계산이 올바른지 확인."""
    now_kst = datetime(2026, 4, 8, 12, 0, 0, tzinfo=_KST)
    start_utc, end_utc = _kst_range_for_month(now_kst)

    # 4월 1일 00:00 KST = 3월 31일 15:00 UTC
    assert start_utc == datetime(2026, 3, 31, 15, 0, 0, tzinfo=UTC)
    # 5월 1일 00:00 KST = 4월 30일 15:00 UTC
    assert end_utc == datetime(2026, 4, 30, 15, 0, 0, tzinfo=UTC)


def test_timestamp_in_range():
    """KST 2026-04-08 10:00에 생성된 캠페인이 오늘 범위에 포함되는지 확인."""
    now_kst = datetime(2026, 4, 8, 20, 0, 0, tzinfo=_KST)
    start_utc, end_utc = _kst_range_for_today(now_kst)

    # KST 10:00 = UTC 01:00
    campaign_created_at_utc = datetime(2026, 4, 8, 1, 0, 0, tzinfo=UTC)
    assert start_utc <= campaign_created_at_utc < end_utc


def test_timestamp_before_range():
    """KST 전날 23:00에 생성된 캠페인은 오늘 범위에 포함되지 않아야 한다."""
    now_kst = datetime(2026, 4, 8, 12, 0, 0, tzinfo=_KST)
    start_utc, end_utc = _kst_range_for_today(now_kst)

    # KST 2026-04-07 23:00 = UTC 2026-04-07 14:00 (전날이고 start보다 작음)
    campaign_created_at_utc = datetime(2026, 4, 7, 14, 0, 0, tzinfo=UTC)
    assert not (start_utc <= campaign_created_at_utc < end_utc)


# ── get_dashboard() 타임라인 시각 ─────────────────────────────────────────────

# 고정한 "지금" = KST 2030-03-14 10:30. 실제 날짜와 멀어서 시계 고정이 빠지면 아래 캠페인이
# 오늘 범위를 벗어나 실패한다 — KST 자정 무렵에 돌려도 오늘이 흔들리지 않는다.
_NOW_UTC = datetime(2030, 3, 14, 1, 30, tzinfo=UTC)


class _FixedDatetime(datetime):
    """dashboard 모듈이 읽는 현재 시각만 _NOW_UTC 로 고정한다."""

    @classmethod
    def now(cls, tz=None):
        return _NOW_UTC.astimezone(tz)


def _add_campaign(db, user, *, created_at, reserve_time=None, state="DISPATCHED"):
    c = Campaign(
        created_by=user.sub, caller_number="0212345678", message_type="short",
        content="공지", total_count=1, state=state,
        created_at=created_at, reserve_time=reserve_time,
    )
    db.add(c)
    db.flush()
    return c


def test_timeline_reads_reserve_time_as_kst(db_session, sample_user, monkeypatch):
    """예약 시각은 오프셋 없는 KST 'YYYY-MM-DD HH:mm' 그대로, created_at 은 UTC → KST 로 찍는다."""
    monkeypatch.setattr(dashboard, "datetime", _FixedDatetime)
    today_kst = _NOW_UTC.astimezone(_KST).strftime("%Y-%m-%d")
    # 즉시 발송: UTC 로는 전날 23:30, KST 로는 오늘 08:30.
    sent = _add_campaign(db_session, sample_user, created_at="2030-03-13T23:30:00+00:00")
    # 오늘 만든 15:00 예약 — UTC 로 읽으면 00:00(다음 날)이 되어 리본 07~19시 밖으로 사라진다.
    reserved = _add_campaign(
        db_session, sample_user, created_at=_NOW_UTC.isoformat(),
        reserve_time=f"{today_kst} 15:00", state="RESERVED",
    )

    timeline = dashboard.get_dashboard(db=db_session)["data"]["timeline"]

    assert timeline["now"] == "10:30"
    assert [(e["id"], e["time"], e["state"]) for e in timeline["events"]] == [
        (f"c{sent.id}", "08:30", "done"),
        (f"c{reserved.id}", "15:00", "scheduled"),
    ]
