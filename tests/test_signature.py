"""app.ncp.signature 단위 테스트 — 사용자 stub 검증용.

signature.py를 직접 작성한 뒤 이 테스트로 자가 검증하세요.
구현 전에는 NotImplementedError를 catch하여 skip 처리됩니다.

SPEC §5.1 알고리즘 검증:
- 반환 헤더 4개 키 존재 확인
- signature가 base64-decodable 확인
- timestamp가 numeric string (epoch ms) 확인
"""
from __future__ import annotations

import base64
import re

import pytest

try:
    from app.ncp.signature import make_headers
    _IMPORT_OK = True
except ImportError:
    _IMPORT_OK = False

pytestmark = pytest.mark.skipif(
    not _IMPORT_OK,
    reason="app.ncp.signature import 실패",
)

_REQUIRED_HEADERS = {
    "x-ncp-apigw-timestamp",
    "x-ncp-iam-access-key",
    "x-ncp-apigw-signature-v2",
    "Content-Type",
}

_SAMPLE = {
    "method": "GET",
    "uri": "/photos/puppy.jpg?query1=&query2",
    "access_key": "AAAA",
    "secret_key": "BBBB",
}


def _call_make_headers(**kwargs) -> dict[str, str] | None:
    """make_headers 호출. NotImplementedError이면 None 반환."""
    try:
        return make_headers(**kwargs)
    except NotImplementedError:
        return None


class TestMakeHeadersStructure:
    """반환값 구조 검증 (구현 여부와 무관하게 형식 확인)."""

    def test_returns_dict_or_not_implemented(self) -> None:
        result = _call_make_headers(**_SAMPLE)
        if result is None:
            pytest.skip("make_headers 미구현 (stub)")
        assert isinstance(result, dict)

    def test_has_required_keys(self) -> None:
        result = _call_make_headers(**_SAMPLE)
        if result is None:
            pytest.skip("make_headers 미구현 (stub)")
        missing = _REQUIRED_HEADERS - set(result.keys())
        assert not missing, f"누락된 헤더: {missing}"

    def test_access_key_matches(self) -> None:
        result = _call_make_headers(**_SAMPLE)
        if result is None:
            pytest.skip("make_headers 미구현 (stub)")
        assert result["x-ncp-iam-access-key"] == _SAMPLE["access_key"]

    def test_content_type_is_json(self) -> None:
        result = _call_make_headers(**_SAMPLE)
        if result is None:
            pytest.skip("make_headers 미구현 (stub)")
        assert result["Content-Type"] == "application/json"

    def test_timestamp_is_numeric_string(self) -> None:
        result = _call_make_headers(**_SAMPLE)
        if result is None:
            pytest.skip("make_headers 미구현 (stub)")
        ts = result["x-ncp-apigw-timestamp"]
        assert re.fullmatch(r"\d+", ts), f"timestamp가 숫자 문자열이 아님: {ts!r}"

    def test_timestamp_is_epoch_milliseconds(self) -> None:
        result = _call_make_headers(**_SAMPLE)
        if result is None:
            pytest.skip("make_headers 미구현 (stub)")
        ts = int(result["x-ncp-apigw-timestamp"])
        # epoch ms: 2020년 이후 ~ 2100년 이전
        assert 1_577_836_800_000 < ts < 4_102_444_800_000, (
            f"timestamp 범위 이상: {ts}"
        )

    def test_signature_is_base64_decodable(self) -> None:
        result = _call_make_headers(**_SAMPLE)
        if result is None:
            pytest.skip("make_headers 미구현 (stub)")
        sig = result["x-ncp-apigw-signature-v2"]
        try:
            decoded = base64.b64decode(sig)
            # HMAC-SHA256 출력은 32 byte
            assert len(decoded) == 32, f"signature 길이 이상: {len(decoded)} bytes"
        except Exception as exc:
            pytest.fail(f"signature base64 디코딩 실패: {exc}")


class TestMakeHeadersConsistency:
    """동일 입력에 대한 일관성 (timestamp 제외) 검증."""

    def test_same_access_key_in_output(self) -> None:
        result = _call_make_headers(**_SAMPLE)
        if result is None:
            pytest.skip("make_headers 미구현 (stub)")
        assert result["x-ncp-iam-access-key"] == "AAAA"

    def test_post_method_headers(self) -> None:
        result = _call_make_headers(
            method="POST",
            uri="/sms/v2/services/SVCID/messages",
            access_key="AAAA",
            secret_key="BBBB",
        )
        if result is None:
            pytest.skip("make_headers 미구현 (stub)")
        assert set(_REQUIRED_HEADERS).issubset(set(result.keys()))

    def test_not_implemented_is_expected_before_writing(self) -> None:
        """stub 상태임을 명시적으로 문서화하는 테스트.

        make_headers가 NotImplementedError를 raise하는 것은
        사용자가 작성하기 전의 의도된 동작입니다.
        """
        try:
            make_headers(**_SAMPLE)
            # 구현이 완료된 경우 — 통과
        except NotImplementedError:
            pytest.skip(
                "make_headers가 아직 구현되지 않았습니다. "
                "SPEC §5.1을 참고하여 signature.py를 작성하세요."
            )
