"""캠페인 멱등키(C1) DB 레벨 보장 테스트.

POST /campaigns 의 Idempotency-Key 는 Campaign.idempotency_key UNIQUE 제약으로
중복 발송을 차단한다. 라우트 흐름(헤더→사전조회→발송)이 아니라, 그 안전성의
근거가 되는 DB 불변식을 직접 검증한다:

1. 같은 키로 2건 INSERT → IntegrityError (중복 발송 차단)
2. NULL 키는 여러 건 허용 (기존 레코드·키 미전송 요청 — NULL 은 UNIQUE 충돌 안 함)
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import Campaign


def _make_campaign(created_by: str, content: str, created_at: str, idem_key: str | None) -> Campaign:
    return Campaign(
        created_by=created_by,
        caller_number="0212345678",
        message_type="short",
        content=content,
        total_count=1,
        state="DISPATCHED",
        created_at=created_at,
        idempotency_key=idem_key,
    )


def test_same_idempotency_key_raises_integrity_error(db_session, sample_user):
    """동일 idempotency_key 로 2건 INSERT 시 UNIQUE 위반(IntegrityError)."""
    db_session.add(
        _make_campaign(sample_user.sub, "first", "2026-01-01T00:00:00+00:00", "dup-key")
    )
    db_session.commit()

    db_session.add(
        _make_campaign(sample_user.sub, "second", "2026-01-01T00:00:01+00:00", "dup-key")
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_null_idempotency_key_allows_multiple(db_session, sample_user):
    """idempotency_key=None 은 여러 건 허용 (NULL 은 UNIQUE 제약에서 충돌하지 않음)."""
    for i in range(3):
        db_session.add(
            _make_campaign(sample_user.sub, f"m{i}", f"2026-01-01T00:00:0{i}+00:00", None)
        )
    db_session.commit()  # 예외가 발생하지 않아야 한다

    count = db_session.execute(select(func.count()).select_from(Campaign)).scalar()
    assert count == 3


def test_distinct_idempotency_keys_coexist(db_session, sample_user):
    """서로 다른 키는 정상 공존한다."""
    db_session.add(
        _make_campaign(sample_user.sub, "a", "2026-01-01T00:00:00+00:00", "key-a")
    )
    db_session.add(
        _make_campaign(sample_user.sub, "b", "2026-01-01T00:00:01+00:00", "key-b")
    )
    db_session.commit()

    count = db_session.execute(select(func.count()).select_from(Campaign)).scalar()
    assert count == 2
