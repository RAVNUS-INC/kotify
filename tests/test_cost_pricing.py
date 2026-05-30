"""msghub 단가/견적 회귀 테스트 (C4).

단방향 RCS 단문이 (RCS,SMS)=17원으로 과금되는 것은 U+ 공식 단가(18.7원 VAT 포함
= 17원 VAT 별도)와 일치하는 **정상 동작**이다. "RCS인데 SMS(9원)보다 비싸다"고
17→9 로 되돌리면 U+ 실청구보다 과소 집계되는 버그가 되므로, 이 단가를 고정한다.

또한 단방향 RCS 단문은 SMS fallback(9원)보다 비싸므로(비용 역전) 견적은 min/max 를
정렬해 9~17 범위로 표시해야 한다.
"""
from __future__ import annotations

from app.msghub.codes import calculate_cost, estimate_cost

# ── calculate_cost: 실청구 단가 (리포트 기반) ────────────────────────────────


def test_rcs_short_oneway_costs_17():
    """단방향 RCS 단문 성공 = (RCS,SMS) = 17원 (U+ 공식 18.7원 VAT포함)."""
    assert calculate_cost("RCS", "SMS", True) == 17


def test_sms_fallback_costs_9():
    assert calculate_cost("SMS", "SMS", True) == 9


def test_rcs_image_template_costs_40():
    assert calculate_cost("RCS", "ITMPL", True) == 40


def test_mms_costs_85():
    assert calculate_cost("MMS", "MMS", True) == 85


def test_failed_or_unknown_costs_0():
    assert calculate_cost("RCS", "SMS", False) == 0  # 실패는 무과금
    assert calculate_cost(None, None, True) == 0  # 채널 미상은 0


# ── estimate_cost: 견적 범위 (min/max 정렬) ──────────────────────────────────


def test_estimate_short_range_is_9_to_17():
    """단문 견적: SMS 9 ~ RCS 단방향 17 (RCS 가 더 비싸므로 min/max 정렬)."""
    assert estimate_cost("short", 100) == (900, 1700)


def test_estimate_image_range_is_40_to_85():
    """이미지 견적: RCS ITMPL 40 ~ MMS 85 (이미지는 RCS 가 이득)."""
    assert estimate_cost("image", 100) == (4000, 8500)


def test_estimate_long_range_is_flat_27():
    """장문: RCS LMS = LMS fallback = 27 → 27~27."""
    assert estimate_cost("long", 10) == (270, 270)
