"""app.ncp.codes 단위 테스트.

describe()는 NCP가 돌려준 statusMessage를 그대로 노출하고,
없을 때만 raw 코드를 표시한다. 우리가 코드를 자체 번역하지 않는다.
"""
from __future__ import annotations

from app.ncp.codes import describe


class TestDescribeUsesNcpMessage:
    """NCP statusMessage가 있을 때는 그대로 반환해야 한다."""

    def test_prefers_raw_message_over_code(self) -> None:
        # NCP가 보내준 메시지가 있으면 그것이 유일한 진실
        result = describe("3018", "휴대폰 가입 이동통신사를 통해 발신번호 변작 방지 부가 서비스에 가입된 번호를 발신번호로 사용하는 경우")
        assert result == "휴대폰 가입 이동통신사를 통해 발신번호 변작 방지 부가 서비스에 가입된 번호를 발신번호로 사용하는 경우"

    def test_success_message_passthrough(self) -> None:
        assert describe("0", "success") == "success"

    def test_korean_message_passthrough(self) -> None:
        assert describe("3001", "가입자 없음") == "가입자 없음"


class TestDescribeFallback:
    """NCP statusMessage가 비어있을 때는 raw 코드만 노출 (번역 금지)."""

    def test_no_message_shows_raw_code(self) -> None:
        # 메시지 없으면 숫자만 노출, 우리가 "결번" 같은 추측을 하지 않음
        assert describe("3001") == "결과 코드 3001"

    def test_empty_message_shows_raw_code(self) -> None:
        assert describe("3023", "") == "결과 코드 3023"

    def test_none_message_shows_raw_code(self) -> None:
        assert describe("2000", None) == "결과 코드 2000"

    def test_unknown_code_not_guessed(self) -> None:
        # 존재하지 않는 코드도 그대로 노출
        assert describe("9999") == "결과 코드 9999"


class TestDescribeEmpty:
    """코드와 메시지 모두 없으면 대시."""

    def test_both_none(self) -> None:
        assert describe(None, None) == "—"

    def test_both_empty(self) -> None:
        assert describe("", "") == "—"

    def test_none_code_only(self) -> None:
        assert describe(None) == "—"


class TestDescribeNoHardcodedTranslations:
    """우리가 임의로 번역한 한국어가 나오지 않는다는 구조적 보증."""

    def test_no_hardcoded_success_translation(self) -> None:
        # raw_message 없이 "0"만 주면 한국어 "성공"이 나오면 안 됨
        assert describe("0") == "결과 코드 0"
        assert "성공" not in describe("0")

    def test_no_hardcoded_3023_translation(self) -> None:
        # 우리는 "사전 등록되지 않은 발신번호" 같은 번역을 들고 있지 않음
        result = describe("3023")
        assert "등록" not in result
        assert "발신번호" not in result
