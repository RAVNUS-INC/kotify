"""CSV import N+1 제거 회귀 테스트 (P1-B / P3).

import_contacts 가 행별 SELECT(N+1) 대신 IN 쿼리 일괄 조회 + dict 캐싱으로
동작하면서도, 기존 동작(DB 기존 매칭, CSV 내 중복 처리)을 보존하는지 검증한다.
"""
from __future__ import annotations

import pytest

from app.services.contacts import create_contact
from app.services.csv_import import import_contacts


def _row(name: str, phone: str) -> dict:
    return {"name": name, "phone": phone, "email": None, "department": None, "notes": None}


def test_skip_existing_db_contact(db_session, sample_user):
    """DB에 이미 있는 phone 은 skip 모드에서 건너뛴다 (IN 쿼리 매칭)."""
    create_contact(db_session, name="기존", created_by=sample_user.sub, phone="01099998888")
    db_session.commit()

    result = import_contacts(
        db_session, [_row("신규", "01099998888")], created_by=sample_user.sub, mode="skip"
    )
    assert result["skipped"] == 1
    assert result["created"] == 0


def test_update_existing_db_contact(db_session, sample_user):
    """update 모드: 기존 phone 의 이름을 덮어쓴다."""
    create_contact(db_session, name="옛이름", created_by=sample_user.sub, phone="01077776666")
    db_session.commit()

    result = import_contacts(
        db_session, [_row("새이름", "01077776666")], created_by=sample_user.sub, mode="update"
    )
    assert result["updated"] == 1
    assert result["created"] == 0


def test_dedup_within_csv_skip_mode(db_session, sample_user):
    """같은 phone 2행을 skip 모드로 import → 1 created + 1 skipped.

    N+1 제거(루프 전 IN 1회) 후에도 CSV 내 중복이 보존되는지 — 캐시 갱신 검증.
    """
    rows = [_row("A", "01011112222"), _row("B", "01011112222")]
    result = import_contacts(db_session, rows, created_by=sample_user.sub, mode="skip")
    assert result["created"] == 1
    assert result["skipped"] == 1


def test_create_mode_always_creates(db_session, sample_user):
    """create 모드: 기존 여부 무관하게 항상 생성 (조회 스킵)."""
    create_contact(db_session, name="기존", created_by=sample_user.sub, phone="01055554444")
    db_session.commit()

    result = import_contacts(
        db_session, [_row("또생성", "01055554444")], created_by=sample_user.sub, mode="create"
    )
    assert result["created"] == 1
    assert result["skipped"] == 0


def test_bulk_import_all_new(db_session, sample_user):
    """100건 신규 import — 전부 생성."""
    rows = [_row(f"u{i}", f"010{str(i).zfill(8)}") for i in range(100)]
    result = import_contacts(db_session, rows, created_by=sample_user.sub, mode="skip")
    assert result["created"] == 100
    assert result["skipped"] == 0
