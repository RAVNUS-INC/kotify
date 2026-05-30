"""app.util.time.parse_mixed_ts — 혼합 타임스탬프 파싱.

회귀: msghub moRecvDt("2026-05-30 11:36:38" — 공백 구분·오프셋 없는 KST)를
이전엔 naive=UTC 로 파싱해 9시간 늦게 계산했다(읽음 처리 버그의 근본 원인).
오프셋 없는 값은 KST 로 간주해야 한다.
"""
from __future__ import annotations

from datetime import UTC

from app.util.time import parse_mixed_ts


def test_iso_with_offset_stays_utc():
    dt = parse_mixed_ts("2026-05-30T03:00:00+00:00")
    assert dt is not None
    assert dt.astimezone(UTC).hour == 3


def test_z_suffix_is_utc():
    dt = parse_mixed_ts("2026-05-30T03:00:00Z")
    assert dt is not None
    assert dt.astimezone(UTC).hour == 3


def test_msghub_space_format_is_kst():
    """'2026-05-30 11:36:38'(오프셋 없음) = KST 11:36 = UTC 02:36 (이전엔 UTC 11:36 버그)."""
    dt = parse_mixed_ts("2026-05-30 11:36:38")
    assert dt is not None
    u = dt.astimezone(UTC)
    assert (u.hour, u.minute) == (2, 36)


def test_msghub_native_14digit_is_kst():
    dt = parse_mixed_ts("20260530113638")
    assert dt is not None
    u = dt.astimezone(UTC)
    assert (u.hour, u.minute) == (2, 36)


def test_empty_or_none_is_none():
    assert parse_mixed_ts("") is None
    assert parse_mixed_ts(None) is None
