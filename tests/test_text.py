"""app.util.text 단위 테스트.

measure_bytes, has_unsupported_chars, classify_message_type를 검증한다.
EUC-KR 경계값(SMS=90, LMS=2000)과 한글/영어 혼합 케이스를 포함.
"""
from __future__ import annotations

import pytest

from app.util.text import classify_message_type, has_unsupported_chars, measure_bytes


# ── measure_bytes ─────────────────────────────────────────────────────────────


class TestMeasureBytes:
    def test_ascii_only(self) -> None:
        # ASCII 1자 = 1 byte
        assert measure_bytes("hello") == 5

    def test_korean_only(self) -> None:
        # 한글 1자 = 2 byte (EUC-KR)
        assert measure_bytes("안녕") == 4

    def test_mixed(self) -> None:
        # "안녕 hi" → 4 + 1 + 2 = 7
        assert measure_bytes("안녕 hi") == 7

    def test_empty_string(self) -> None:
        assert measure_bytes("") == 0

    def test_exactly_90_bytes_ascii(self) -> None:
        # ASCII 90자 = 90 byte
        assert measure_bytes("a" * 90) == 90

    def test_exactly_45_korean(self) -> None:
        # 한글 45자 = 90 byte (SMS 경계)
        assert measure_bytes("가" * 45) == 90

    def test_91_bytes_ascii(self) -> None:
        assert measure_bytes("a" * 91) == 91

    def test_exactly_2000_bytes(self) -> None:
        # 한글 1000자 = 2000 byte (LMS 경계)
        assert measure_bytes("가" * 1000) == 2000

    def test_2001_bytes(self) -> None:
        # 한글 1000자 + ASCII 1자 = 2001 byte
        assert measure_bytes("가" * 1000 + "a") == 2001

    def test_number_chars(self) -> None:
        # 숫자/특수문자는 ASCII 1 byte
        assert measure_bytes("010-1234-5678") == 13


# ── has_unsupported_chars ─────────────────────────────────────────────────────


class TestHasUnsupportedChars:
    def test_pure_ascii(self) -> None:
        assert has_unsupported_chars("hello world") is False

    def test_korean(self) -> None:
        assert has_unsupported_chars("안녕하세요") is False

    def test_mixed_korean_ascii(self) -> None:
        assert has_unsupported_chars("안녕 hello 123") is False

    def test_emoji(self) -> None:
        # 이모지는 EUC-KR 미지원
        assert has_unsupported_chars("안녕 😊") is True

    def test_emoji_only(self) -> None:
        assert has_unsupported_chars("🎉🎊") is True

    def test_empty_string(self) -> None:
        assert has_unsupported_chars("") is False

    def test_chinese_character(self) -> None:
        # 일부 한자는 EUC-KR 지원, 일부 아님. 기본 CJK는 지원됨.
        # 테스트는 인코딩 시도 결과를 그대로 반영
        text = "中"
        result = has_unsupported_chars(text)
        try:
            text.encode("euc-kr")
            assert result is False
        except UnicodeEncodeError:
            assert result is True


# ── classify_message_type ─────────────────────────────────────────────────────


class TestClassifyMessageType:
    def test_short_ascii_is_sms(self) -> None:
        assert classify_message_type("hello") == "SMS"

    def test_short_korean_is_sms(self) -> None:
        # 10자 = 20 byte → SMS
        assert classify_message_type("안녕하세요반갑습니다") == "SMS"

    def test_exactly_90_bytes_is_sms(self) -> None:
        # 한글 45자 = 90 byte → SMS
        assert classify_message_type("가" * 45) == "SMS"

    def test_91_bytes_is_lms(self) -> None:
        # 한글 45자 + ASCII 1자 = 91 byte → LMS
        assert classify_message_type("가" * 45 + "a") == "LMS"

    def test_exactly_2000_bytes_is_lms(self) -> None:
        # 한글 1000자 = 2000 byte → LMS
        assert classify_message_type("가" * 1000) == "LMS"

    def test_2001_bytes_raises(self) -> None:
        # 2001 byte → ValueError
        with pytest.raises(ValueError, match="초과"):
            classify_message_type("가" * 1000 + "a")

    def test_emoji_raises(self) -> None:
        # 이모지 포함 → ValueError
        with pytest.raises(ValueError, match="EUC-KR"):
            classify_message_type("안녕 😊")

    def test_empty_string_is_sms(self) -> None:
        assert classify_message_type("") == "SMS"

    def test_mixed_content_boundary(self) -> None:
        # "공지: " (6 byte) + 한글 42자 (84 byte) = 90 byte → SMS
        prefix = "공지: "  # 6 byte
        prefix_bytes = len(prefix.encode("euc-kr"))
        remaining = (90 - prefix_bytes) // 2
        text = prefix + "가" * remaining
        result = classify_message_type(text)
        assert result == "SMS"
        assert measure_bytes(text) <= 90
