"""연락처 전화번호 정규화 통일 테스트 (테마 D, P1-A).

contacts POST/PATCH validator 가 normalize_phone 으로 통일되어 경로에 무관하게
같은 번호가 같은 형태('01012345678')로 저장되는지 검증한다. 이전에는 숫자만
추출해 유선번호·국제표기가 그대로 저장되어 dedup·발송 불일치를 유발했다.
(groups bulk-add 도 동일한 normalize_phone 을 사용한다.)
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.routes.contacts import ContactCreateBody, ContactUpdateBody


# ── POST /contacts ───────────────────────────────────────────────────────────


def test_create_normalizes_hyphenated():
    assert ContactCreateBody(name="홍길동", phone="010-1234-5678").phone == "01012345678"


def test_create_normalizes_international():
    assert ContactCreateBody(name="x", phone="+82-10-1234-5678").phone == "01012345678"


def test_create_normalizes_dotted():
    assert ContactCreateBody(name="x", phone="010.1234.5678").phone == "01012345678"


def test_create_rejects_landline():
    """유선번호(02-...)는 휴대폰이 아니므로 거부 (이전엔 '0212345678' 저장됨)."""
    with pytest.raises(ValidationError):
        ContactCreateBody(name="x", phone="02-1234-5678")


def test_create_rejects_garbage():
    with pytest.raises(ValidationError):
        ContactCreateBody(name="x", phone="00012345")


def test_create_empty_or_none_phone_is_none():
    assert ContactCreateBody(name="x", phone="").phone is None
    assert ContactCreateBody(name="x", phone="   ").phone is None
    assert ContactCreateBody(name="x", phone=None).phone is None


# ── PATCH /contacts/{id} ─────────────────────────────────────────────────────


def test_update_empty_phone_is_none():
    """PATCH 빈 문자열은 None — 이전엔 '' 가 그대로 저장됐다 (P3 버그)."""
    assert ContactUpdateBody(phone="").phone is None


def test_update_normalizes_valid():
    assert ContactUpdateBody(phone="+821012345678").phone == "01012345678"


def test_update_rejects_invalid():
    with pytest.raises(ValidationError):
        ContactUpdateBody(phone="02-1234-5678")
