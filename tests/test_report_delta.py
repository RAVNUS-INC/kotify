"""리포트 KPI 증감 문자열(_delta) — 지난 기간이 0 일 때 지어낸 상한을 내리지 않는다."""

from app.routes.reports import _delta


def test_same_value_is_flat():
    assert _delta(5, 5) == ("0.0%", "flat")
    assert _delta(72.0, 72.0, is_percent=True) == ("0.0p", "flat")


def test_previous_zero_ratio_is_dash_not_capped_percent():
    assert _delta(32, 0) == ("—", "flat")


def test_previous_zero_percent_point_is_plain_difference():
    assert _delta(72.0, 0.0, is_percent=True) == ("+72.0p", "up")


def test_ratio_change():
    assert _delta(150, 100) == ("+50.0%", "up")
    assert _delta(50, 100) == ("-50.0%", "down")


def test_percent_point_change():
    assert _delta(95.5, 97.0, is_percent=True) == ("-1.5p", "down")
