"""app.ncp.codes 단위 테스트.

describe() 함수가 주요 수신결과 코드를 올바르게 매핑하는지 검증한다.
"""
from __future__ import annotations

import pytest

from app.ncp.codes import RESULT_CODE_MAP, describe


class TestDescribe:
    def test_success_code(self) -> None:
        assert describe("0") == "성공"

    def test_power_off(self) -> None:
        assert describe("2000") == "단말 전원 꺼짐"

    def test_dead_number(self) -> None:
        assert describe("3001") == "결번"

    def test_invalid_format(self) -> None:
        assert describe("3003") == "수신번호 형식 오류"

    def test_spoofing_prevention(self) -> None:
        assert describe("3018") == "발신번호 스푸핑 방지 가입 번호"

    def test_unregistered_caller(self) -> None:
        # SPEC §5.6 핵심: 미등록 발신번호
        assert describe("3023") == "사전 등록되지 않은 발신번호"

    def test_shadow_area(self) -> None:
        assert describe("2002") == "음영 지역"

    def test_spam(self) -> None:
        assert describe("3012") == "스팸"

    def test_unknown_code_contains_code_value(self) -> None:
        # 매핑에 없는 코드 → 알 수 없음 + 코드 포함
        result = describe("9999")
        assert "9999" in result
        assert "알 수 없는" in result

    def test_unknown_code_empty_string(self) -> None:
        result = describe("")
        assert "알 수 없는" in result

    def test_all_mapped_codes_return_korean(self) -> None:
        # 매핑된 모든 코드가 비어 있지 않은 문자열을 반환하는지 확인
        for code, description in RESULT_CODE_MAP.items():
            result = describe(code)
            assert result == description
            assert len(result) > 0

    @pytest.mark.parametrize(
        "code,expected_substr",
        [
            ("0", "성공"),
            ("2001", "버퍼"),
            ("3004", "정지"),
            ("3006", "블랙"),
            ("3007", "거부"),
            ("3016", "길이"),
            ("4001", "시간 초과"),
        ],
    )
    def test_parametrized_codes(self, code: str, expected_substr: str) -> None:
        assert expected_substr in describe(code)
