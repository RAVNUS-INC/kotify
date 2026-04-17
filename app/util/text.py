"""메시지 본문 검증 유틸 — EUC-KR 기준 byte 측정 및 SMS/LMS 판정.

SPEC §7 참조:
- SMS: ≤ 90 byte
- LMS: ≤ 2000 byte
- 초과: ValueError
- EUC-KR 미지원 문자(이모지 등) 포함 시 사전 차단
"""
from __future__ import annotations

from typing import Literal

# SMS/LMS 분류 경계 (byte, EUC-KR 기준)
_SMS_MAX_BYTES = 90
_LMS_MAX_BYTES = 2000


def encode_or_raise(text: str) -> bytes:
    """EUC-KR로 인코딩하여 bytes를 반환한다.

    Args:
        text: 인코딩할 문자열.

    Returns:
        EUC-KR 인코딩된 bytes.

    Raises:
        ValueError: EUC-KR 미지원 문자가 포함된 경우.
    """
    try:
        return text.encode("euc-kr")
    except UnicodeEncodeError as e:
        raise ValueError(f"EUC-KR로 인코딩할 수 없는 문자: {e}") from e


def measure_bytes(text: str) -> int:
    """EUC-KR 인코딩 기준 byte 길이를 반환한다.

    인코딩을 한 번만 수행하여 불필요한 이중 인코딩을 방지한다 (R6).

    Args:
        text: 측정할 문자열.

    Returns:
        byte 길이 (한글 1자 = 2, ASCII 1자 = 1).

    Raises:
        UnicodeEncodeError: EUC-KR 미지원 문자가 포함된 경우.
            호출 전 ``has_unsupported_chars()`` 로 사전 검사 권장.
    """
    return len(text.encode("euc-kr"))


def has_unsupported_chars(text: str) -> bool:
    """EUC-KR 인코딩이 불가능한 문자(이모지 등)가 포함되어 있으면 True.

    Args:
        text: 검사할 문자열.

    Returns:
        True이면 발송 시 실패할 수 있으므로 발송 차단 권장.
    """
    try:
        text.encode("euc-kr")
        return False
    except UnicodeEncodeError:
        return True


def classify_message_type(content: str) -> Literal["SMS", "LMS"]:
    """본문 byte 길이를 기준으로 SMS 또는 LMS를 반환한다.

    Args:
        content: 메시지 본문 (EUC-KR 인코딩 가능한 문자열).

    Returns:
        ``"SMS"`` (≤ 90 byte) 또는 ``"LMS"`` (≤ 2000 byte).

    Raises:
        ValueError: EUC-KR 미지원 문자가 포함된 경우.
        ValueError: byte 길이가 2000을 초과하는 경우.
    """
    if has_unsupported_chars(content):
        raise ValueError(
            "EUC-KR 미지원 문자(이모지 등)가 포함되어 있습니다. 발송 전 제거하세요."
        )

    byte_len = measure_bytes(content)

    if byte_len <= _SMS_MAX_BYTES:
        return "SMS"
    if byte_len <= _LMS_MAX_BYTES:
        return "LMS"

    raise ValueError(
        f"메시지 길이({byte_len} byte)가 LMS 최대치({_LMS_MAX_BYTES} byte)를 초과합니다."
    )
