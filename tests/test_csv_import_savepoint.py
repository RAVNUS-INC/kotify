"""CSV import 행 단위 savepoint 격리 테스트 (P2-D / P3).

import_contacts 가 행 단위 savepoint(begin_nested)로 동작해, 한 행이 실패해도
그 행만 롤백되고 나머지 정상 행은 저장되는지 검증한다.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import Contact
from app.services import csv_import as mod
from app.services.csv_import import import_contacts


def _row(name: str, phone: str) -> dict:
    return {"name": name, "phone": phone, "email": None, "department": None, "notes": None}


def test_row_failure_is_isolated(db_session, sample_user, monkeypatch):
    """가운데 행 생성이 실패해도 앞뒤 정상 행은 저장된다 (savepoint 격리)."""
    orig = mod.create_contact

    def _flaky(db, **kw):
        if kw.get("phone") == "01022220000":
            raise RuntimeError("simulated row failure")
        return orig(db, **kw)

    monkeypatch.setattr(mod, "create_contact", _flaky)

    rows = [_row("A", "01011110000"), _row("B", "01022220000"), _row("C", "01033330000")]
    result = import_contacts(db_session, rows, created_by=sample_user.sub, mode="skip")

    assert result["created"] == 2  # A, C
    assert len(result["errors"]) == 1  # B

    phones = {c.phone for c in db_session.execute(select(Contact)).scalars().all()}
    assert "01011110000" in phones  # A 저장
    assert "01033330000" in phones  # C 저장
    assert "01022220000" not in phones  # B 는 롤백되어 미저장


def test_all_rows_succeed_when_no_error(db_session, sample_user):
    """오류가 없으면 모든 행이 정상 저장된다 (savepoint 가 정상 경로를 깨지 않음)."""
    rows = [_row(f"u{i}", f"010{str(i).zfill(8)}") for i in range(20)]
    result = import_contacts(db_session, rows, created_by=sample_user.sub, mode="skip")

    assert result["created"] == 20
    assert result["errors"] == []
    count = len(db_session.execute(select(Contact)).scalars().all())
    assert count == 20
