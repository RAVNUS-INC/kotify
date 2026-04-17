"""t_error 매핑 테스트."""
from __future__ import annotations

import pytest

from app.i18n import t_error


@pytest.mark.parametrize("slug,expected", [
    ("invalid_caller", "선택한 발신번호가 활성 목록에 없습니다."),
    ("invalid_numbers", "잘못된 전화번호가 포함되어 있습니다. 모두 수정한 뒤 다시 시도하세요."),
    ("too_many_recipients", "1회 최대 1,000명까지만 발송할 수 있습니다."),
    ("msghub_not_configured", "msghub 발송 서비스가 구성되지 않았습니다. 관리자에게 문의하세요."),
    ("stub_phone", "전화번호 검증 모듈이 구현되지 않았습니다 (개발자 영역)."),
    ("invalid_token", "올바르지 않은 setup token입니다."),
])
def test_known_slugs(slug: str, expected: str) -> None:
    assert t_error(slug) == expected


def test_none_returns_empty() -> None:
    assert t_error(None) == ""


def test_empty_string_returns_empty() -> None:
    assert t_error("") == ""


def test_unknown_slug_returns_fallback() -> None:
    result = t_error("some_unknown_error")
    assert "some_unknown_error" in result
