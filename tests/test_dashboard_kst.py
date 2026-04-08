"""대시보드 KST 경계 케이스 테스트."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta


_KST = timezone(timedelta(hours=9))


def _kst_range_for_today(now_kst: datetime):
    """KST 기준 오늘의 UTC 시작/끝 범위를 반환한다."""
    today_start_kst = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start_kst = today_start_kst + timedelta(days=1)
    return (
        today_start_kst.astimezone(timezone.utc),
        tomorrow_start_kst.astimezone(timezone.utc),
    )


def _kst_range_for_month(now_kst: datetime):
    """KST 기준 이번 달의 UTC 시작/끝 범위를 반환한다."""
    month_start_kst = now_kst.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if month_start_kst.month == 12:
        next_month_kst = month_start_kst.replace(year=month_start_kst.year + 1, month=1)
    else:
        next_month_kst = month_start_kst.replace(month=month_start_kst.month + 1)
    return (
        month_start_kst.astimezone(timezone.utc),
        next_month_kst.astimezone(timezone.utc),
    )


def test_kst_today_range_midnight_boundary():
    """KST 자정(00:00 KST = 15:00 UTC 전날)이 올바른 UTC 범위를 산출한다."""
    # KST 2026-04-08 00:00:00
    now_kst = datetime(2026, 4, 8, 0, 0, 0, tzinfo=_KST)
    start_utc, end_utc = _kst_range_for_today(now_kst)

    # KST 00:00 = UTC 전날 15:00
    assert start_utc == datetime(2026, 4, 7, 15, 0, 0, tzinfo=timezone.utc)
    assert end_utc == datetime(2026, 4, 8, 15, 0, 0, tzinfo=timezone.utc)


def test_kst_today_range_afternoon():
    """KST 오후(14:00 KST = 05:00 UTC)의 UTC 범위."""
    now_kst = datetime(2026, 4, 8, 14, 0, 0, tzinfo=_KST)
    start_utc, end_utc = _kst_range_for_today(now_kst)

    assert start_utc == datetime(2026, 4, 7, 15, 0, 0, tzinfo=timezone.utc)
    assert end_utc == datetime(2026, 4, 8, 15, 0, 0, tzinfo=timezone.utc)


def test_kst_month_range_december():
    """12월의 다음 달 계산이 올바른지 확인 (연도 넘김)."""
    now_kst = datetime(2026, 12, 15, 12, 0, 0, tzinfo=_KST)
    start_utc, end_utc = _kst_range_for_month(now_kst)

    # 12월 1일 00:00 KST = 11월 30일 15:00 UTC
    assert start_utc == datetime(2026, 11, 30, 15, 0, 0, tzinfo=timezone.utc)
    # 2027년 1월 1일 00:00 KST = 2026년 12월 31일 15:00 UTC
    assert end_utc == datetime(2026, 12, 31, 15, 0, 0, tzinfo=timezone.utc)


def test_kst_month_range_regular():
    """일반 월 범위 계산이 올바른지 확인."""
    now_kst = datetime(2026, 4, 8, 12, 0, 0, tzinfo=_KST)
    start_utc, end_utc = _kst_range_for_month(now_kst)

    # 4월 1일 00:00 KST = 3월 31일 15:00 UTC
    assert start_utc == datetime(2026, 3, 31, 15, 0, 0, tzinfo=timezone.utc)
    # 5월 1일 00:00 KST = 4월 30일 15:00 UTC
    assert end_utc == datetime(2026, 4, 30, 15, 0, 0, tzinfo=timezone.utc)


def test_timestamp_in_range():
    """KST 2026-04-08 10:00에 생성된 캠페인이 오늘 범위에 포함되는지 확인."""
    now_kst = datetime(2026, 4, 8, 20, 0, 0, tzinfo=_KST)
    start_utc, end_utc = _kst_range_for_today(now_kst)

    # KST 10:00 = UTC 01:00
    campaign_created_at_utc = datetime(2026, 4, 8, 1, 0, 0, tzinfo=timezone.utc)
    assert start_utc <= campaign_created_at_utc < end_utc


def test_timestamp_before_range():
    """KST 전날 23:00에 생성된 캠페인은 오늘 범위에 포함되지 않아야 한다."""
    now_kst = datetime(2026, 4, 8, 12, 0, 0, tzinfo=_KST)
    start_utc, end_utc = _kst_range_for_today(now_kst)

    # KST 2026-04-07 23:00 = UTC 2026-04-07 14:00 (전날이고 start보다 작음)
    campaign_created_at_utc = datetime(2026, 4, 7, 14, 0, 0, tzinfo=timezone.utc)
    assert not (start_utc <= campaign_created_at_utc < end_utc)
