"""kst_dt Jinja 필터 테스트."""
from __future__ import annotations

import pytest

from app.web import kst_dt


@pytest.mark.parametrize("value,expected", [
    # UTC ISO → KST (+9h)
    ("2024-01-15T00:00:00+00:00", "2024-01-15 09:00"),
    ("2024-01-15T15:30:00+00:00", "2024-01-16 00:30"),
    # 타임존 없는 naive datetime → UTC 가정
    ("2024-01-15T12:00:00", "2024-01-15 21:00"),
    # 자정 경계
    ("2024-12-31T15:00:00+00:00", "2025-01-01 00:00"),
])
def test_kst_conversion(value: str, expected: str) -> None:
    assert kst_dt(value) == expected


def test_none_returns_empty() -> None:
    assert kst_dt(None) == ""


def test_empty_string_returns_empty() -> None:
    assert kst_dt("") == ""


def test_invalid_falls_back() -> None:
    # 잘못된 형식이면 앞 16자로 폴백 (T→공백)
    result = kst_dt("2024-01-15 12:00:00 invalid")
    assert result  # 빈 문자열이 아님
