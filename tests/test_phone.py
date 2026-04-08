"""app.util.phone 단위 테스트 — 사용자 stub 검증용.

phone.py를 직접 작성한 뒤 이 테스트로 자가 검증하세요.
구현 전에는 NotImplementedError로 skip 처리됩니다.
"""
from __future__ import annotations

import pytest

# NotImplementedError → 전체 모듈 skip 처리
try:
    from app.util.phone import normalize_phone, parse_phone_list
    _NOT_IMPLEMENTED = False
except ImportError:
    _NOT_IMPLEMENTED = True

pytestmark = pytest.mark.skipif(
    _NOT_IMPLEMENTED,
    reason="app.util.phone import 실패",
)


def _skip_if_not_implemented(fn):
    """개별 함수가 NotImplementedError를 raise하면 skip."""
    import functools

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except NotImplementedError:
            pytest.skip("normalize_phone / parse_phone_list 미구현 (stub)")

    return wrapper


# ── normalize_phone 정상 케이스 ──────────────────────────────────────────────


class TestNormalizePhoneValid:
    """다양한 입력 형식이 모두 '01012345678'로 정규화되어야 한다."""

    EXPECTED = "01012345678"

    @_skip_if_not_implemented
    def test_digits_only(self) -> None:
        assert normalize_phone("01012345678") == self.EXPECTED

    @_skip_if_not_implemented
    def test_hyphen_format(self) -> None:
        assert normalize_phone("010-1234-5678") == self.EXPECTED

    @_skip_if_not_implemented
    def test_space_format(self) -> None:
        assert normalize_phone("010 1234 5678") == self.EXPECTED

    @_skip_if_not_implemented
    def test_dot_format(self) -> None:
        assert normalize_phone("010.1234.5678") == self.EXPECTED

    @_skip_if_not_implemented
    def test_plus82_hyphen(self) -> None:
        assert normalize_phone("+82-10-1234-5678") == self.EXPECTED

    @_skip_if_not_implemented
    def test_plus82_no_hyphen(self) -> None:
        assert normalize_phone("+821012345678") == self.EXPECTED

    @_skip_if_not_implemented
    def test_82_prefix_with_hyphen(self) -> None:
        assert normalize_phone("8210-1234-5678") == self.EXPECTED

    @_skip_if_not_implemented
    def test_leading_trailing_spaces(self) -> None:
        # 앞뒤 공백 포함 입력도 처리
        assert normalize_phone("  010-1234-5678  ") == self.EXPECTED


# ── normalize_phone 다른 prefix ──────────────────────────────────────────────


class TestNormalizePhoneOtherPrefixes:
    """01[016789] 패턴의 다른 prefix도 유효하다."""

    @_skip_if_not_implemented
    def test_011_prefix(self) -> None:
        result = normalize_phone("01112345678")
        assert result == "01112345678"

    @_skip_if_not_implemented
    def test_016_prefix(self) -> None:
        result = normalize_phone("01612345678")
        assert result == "01612345678"

    @_skip_if_not_implemented
    def test_017_prefix(self) -> None:
        result = normalize_phone("01712345678")
        assert result == "01712345678"

    @_skip_if_not_implemented
    def test_018_prefix(self) -> None:
        result = normalize_phone("01812345678")
        assert result == "01812345678"

    @_skip_if_not_implemented
    def test_019_prefix(self) -> None:
        result = normalize_phone("01912345678")
        assert result == "01912345678"

    @_skip_if_not_implemented
    def test_010_8digit_subscriber(self) -> None:
        # 010 + 8자리 = 11자리 (현행 표준)
        result = normalize_phone("01012345678")
        assert result == "01012345678"

    @_skip_if_not_implemented
    def test_011_7digit_subscriber(self) -> None:
        # 011 + 7자리 = 10자리 (구형 번호)
        result = normalize_phone("0111234567")
        assert result == "0111234567"


# ── normalize_phone 실패 케이스 ──────────────────────────────────────────────


class TestNormalizePhoneInvalid:
    """invalid 입력은 None을 반환해야 한다."""

    @_skip_if_not_implemented
    def test_empty_string(self) -> None:
        assert normalize_phone("") is None

    @_skip_if_not_implemented
    def test_alpha_chars(self) -> None:
        assert normalize_phone("abc") is None

    @_skip_if_not_implemented
    def test_landline_02(self) -> None:
        # 유선번호 (02-)는 휴대폰 패턴 불일치 → None
        assert normalize_phone("02-1234-5678") is None

    @_skip_if_not_implemented
    def test_too_short_digits(self) -> None:
        # 010 + 4자리 = 자릿수 부족 → None
        assert normalize_phone("010-12-3456") is None

    @_skip_if_not_implemented
    def test_missing_leading_zero(self) -> None:
        # 선두 0 없는 10자리 (01로 시작 안 함) → None
        assert normalize_phone("1012345678") is None

    @_skip_if_not_implemented
    def test_invalid_prefix_013(self) -> None:
        # 013으로 시작 → 패턴 불일치 → None
        assert normalize_phone("01312345678") is None

    @_skip_if_not_implemented
    def test_too_long(self) -> None:
        # 12자리 이상 → None
        assert normalize_phone("010123456789") is None


# ── parse_phone_list ──────────────────────────────────────────────────────────


class TestParsePhoneList:
    """멀티라인/콤마/세미콜론 혼합 입력을 올바르게 파싱해야 한다."""

    @_skip_if_not_implemented
    def test_multiline_all_valid(self) -> None:
        text = "010-1234-5678\n01087654321\n010.9999.8888"
        valid, invalid = parse_phone_list(text)
        assert len(valid) == 3
        assert len(invalid) == 0
        assert "01012345678" in valid or "01087654321" in valid

    @_skip_if_not_implemented
    def test_comma_separated(self) -> None:
        text = "010-1234-5678, 010-8765-4321"
        valid, invalid = parse_phone_list(text)
        assert len(valid) == 2
        assert len(invalid) == 0

    @_skip_if_not_implemented
    def test_semicolon_separated(self) -> None:
        text = "010-1234-5678;010-8765-4321"
        valid, invalid = parse_phone_list(text)
        assert len(valid) == 2
        assert len(invalid) == 0

    @_skip_if_not_implemented
    def test_mixed_separators(self) -> None:
        text = "010-1234-5678\n01087654321, 010-9999-8888"
        valid, invalid = parse_phone_list(text)
        assert len(valid) == 3
        assert len(invalid) == 0

    @_skip_if_not_implemented
    def test_empty_lines_ignored(self) -> None:
        text = "010-1234-5678\n\n\n01087654321\n"
        valid, invalid = parse_phone_list(text)
        assert len(valid) == 2
        assert len(invalid) == 0

    @_skip_if_not_implemented
    def test_invalid_numbers_captured(self) -> None:
        text = "010-1234-5678\nabc\n02-1234-5678"
        valid, invalid = parse_phone_list(text)
        assert len(valid) == 1
        assert len(invalid) == 2

    @_skip_if_not_implemented
    def test_mixed_valid_invalid(self) -> None:
        text = "010-1234-5678\n잘못된번호\n01087654321\n02-999-8888"
        valid, invalid = parse_phone_list(text)
        assert len(valid) == 2
        assert len(invalid) == 2

    @_skip_if_not_implemented
    def test_empty_input(self) -> None:
        valid, invalid = parse_phone_list("")
        assert valid == []
        assert invalid == []

    @_skip_if_not_implemented
    def test_valid_returns_normalized(self) -> None:
        # valid 목록은 항상 정규화된 형태 (숫자만)
        text = "+82-10-1234-5678"
        valid, invalid = parse_phone_list(text)
        assert valid == ["01012345678"]
        assert invalid == []

    @_skip_if_not_implemented
    def test_duplicate_numbers(self) -> None:
        # 중복 번호 처리 — 구현에 따라 중복 허용/제거 가능
        # 최소한 crash 없이 실행되어야 함
        text = "010-1234-5678\n010-1234-5678"
        valid, invalid = parse_phone_list(text)
        assert all(n == "01012345678" for n in valid)
        assert len(invalid) == 0
