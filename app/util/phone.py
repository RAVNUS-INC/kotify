"""한국 휴대폰 번호 정규화 + 일괄 파싱.

명세 (SPEC §6):
- 입력 형식 (전부 허용):
    01012345678
    010-1234-5678
    010 1234 5678
    010.1234.5678
    +82-10-1234-5678
    +821012345678
    8210-1234-5678
- 정규화 규칙:
    1. 공백/-/./() 제거
    2. 선두 +82 → 0
    3. 선두 82 (10자리 이상) → 0
    4. 결과가 ^01[016789]\\d{7,8}$ 매치
    5. 미매치 → None
- 정책 (§6.3): 잘못된 번호 1개라도 있으면 발송 차단
"""
from __future__ import annotations

import re

_PHONE_PATTERN = re.compile(r"^01[016789]\d{7,8}$")
_STRIP_CHARS = re.compile(r"[\s\-.()]")
_SPLIT_PATTERN = re.compile(r"[\n,;]+")


def normalize_phone(raw: str) -> str | None:
    """단일 번호 정규화. 성공 시 '01012345678' 형태, 실패 시 None."""
    if raw is None:
        return None

    # 1. 공백/구분자 제거
    cleaned = _STRIP_CHARS.sub("", raw.strip())
    if not cleaned:
        return None

    # 2. 선두 +82 → 0
    if cleaned.startswith("+82"):
        cleaned = "0" + cleaned[3:]
    # 3. 선두 82 (그리고 0으로 시작 안 하는 12자리 이상) → 0
    elif cleaned.startswith("82") and len(cleaned) >= 12:
        cleaned = "0" + cleaned[2:]

    # 4. 한국 휴대폰 패턴 검증
    if _PHONE_PATTERN.fullmatch(cleaned):
        return cleaned
    return None


# 발송 수신번호로 받는 국내 번호 — 휴대폰(위 규칙), 0 으로 시작하는 유선·인터넷 전화 9~11자리,
# 050 안심번호 12자리(0505-1234-5678), 15xx~19xx 대표번호 8자리. msghub recvInfoLst[].phone 은
# 20자 이내라 이 형식이면 늘 들어간다.
_DOMESTIC_PATTERN = re.compile(r"^(?:0\d{8,10}|050\d{9}|1[5-9]\d{6})$")


def normalize_recipient(raw: str) -> str | None:
    """발송 수신번호 정규화. 숫자만 남긴 국내 번호, 형식이 틀리면 None.

    구분자(공백·-·.·괄호)를 지우고 +82/82 국가번호를 0 으로 바꾼다(normalize_phone 과 같은 규칙).
    이름·국제번호·자릿수가 틀린 값은 None — 그대로 보내면 msghub 가 요청째 거부할 수 있다.
    """
    if not isinstance(raw, str):
        return None
    mobile = normalize_phone(raw)
    if mobile is not None:
        return mobile
    cleaned = _STRIP_CHARS.sub("", raw.strip())
    if cleaned.startswith("+82"):
        cleaned = "0" + cleaned[3:]
    elif cleaned.startswith("82") and len(cleaned) >= 11:
        cleaned = "0" + cleaned[2:]
    return cleaned if _DOMESTIC_PATTERN.fullmatch(cleaned) else None


def parse_phone_list(text: str) -> tuple[list[str], list[str]]:
    """멀티라인/콤마/세미콜론 구분 텍스트에서 번호 추출.

    Returns:
        (valid_normalized, invalid_originals)
    """
    if not text or not text.strip():
        return [], []

    valid: list[str] = []
    invalid: list[str] = []

    for raw_token in _SPLIT_PATTERN.split(text):
        token = raw_token.strip()
        if not token:
            continue
        normalized = normalize_phone(token)
        if normalized is not None:
            valid.append(normalized)
        else:
            invalid.append(token)

    return valid, invalid


def mask_phone(value: str | None) -> str:
    """전화번호를 로그 노출용으로 마스킹한다 (PIPA — 개인정보 보호).

    예: "01012345678" → "010****5678". 앞 3·뒤 4자리만 남기고 가운데를 가린다.
    cliKey 없는 리포트의 비정형 값(하이픈·국제표기 포함 등)도 동일 규칙으로 처리하되,
    7자 이하면 전부 가린다(과다노출 방지). 빈 값/None 은 "(none)".

    고정 길이 "****" 로 가려 실제 자릿수도 노출하지 않는다. 로그·감사 출력 전용이며,
    발송·매칭 로직에는 절대 사용하지 않는다(원본 손실).
    """
    if not value:
        return "(none)"
    if len(value) <= 7:
        return "*" * len(value)
    return value[:3] + "****" + value[-4:]
