"""CSV 가져오기/내보내기 서비스 테스트."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.models import User
from app.services.contacts import list_contacts
from app.services.csv_import import export_contacts, import_contacts, parse_csv

# ── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture
def admin_user(db_session):
    user = User(
        sub="csv-admin-001",
        email="csv@example.com",
        name="CSV관리자",
        roles=json.dumps(["admin"]),
        created_at=datetime.now(UTC).isoformat(),
        last_login_at=datetime.now(UTC).isoformat(),
    )
    db_session.add(user)
    db_session.commit()
    return user


VALID_CSV = """name,phone,email,department,notes
홍길동,010-1234-5678,hong@example.com,마케팅팀,VIP
김철수,01099998888,,영업팀,
이영희,,lee@example.com,,,
"""

INVALID_PHONE_CSV = """name,phone,email
잘못된번호,12345abcde,
"""

MISSING_NAME_CSV = """name,phone,email
,010-1111-2222,
"""

MISSING_CONTACT_CSV = """name,phone,email
이름만있음,,
"""

HEADER_ONLY_CSV = """name,phone,email
"""


# ── parse_csv ─────────────────────────────────────────────────────────────────


class TestParseCsv:
    def test_valid_rows(self):
        valid, invalid = parse_csv(VALID_CSV)
        assert len(valid) == 3
        assert len(invalid) == 0

    def test_phone_normalized(self):
        valid, _ = parse_csv(VALID_CSV)
        hong = next(r for r in valid if r["name"] == "홍길동")
        assert hong["phone"] == "01012345678"  # 하이픈 제거됨

    def test_invalid_phone_row(self):
        valid, invalid = parse_csv(INVALID_PHONE_CSV)
        assert len(valid) == 0
        assert len(invalid) == 1
        assert "전화번호" in invalid[0]["error"]

    def test_missing_name_invalid(self):
        valid, invalid = parse_csv(MISSING_NAME_CSV)
        assert len(valid) == 0
        assert len(invalid) == 1
        assert "name" in invalid[0]["error"]

    def test_missing_phone_and_email_invalid(self):
        valid, invalid = parse_csv(MISSING_CONTACT_CSV)
        assert len(valid) == 0
        assert len(invalid) == 1

    def test_header_only_returns_empty(self):
        valid, invalid = parse_csv(HEADER_ONLY_CSV)
        assert valid == []
        assert invalid == []

    def test_missing_required_header(self):
        # name 헤더 없음
        csv_data = "phone,email\n01011111111,x@x.com\n"
        valid, invalid = parse_csv(csv_data)
        assert len(valid) == 0
        assert len(invalid) == 1
        assert "헤더" in invalid[0]["error"]

    def test_row_number_reported(self):
        csv_data = "name,phone\n홍길동,01011111111\n,01022222222\n"
        _, invalid = parse_csv(csv_data)
        assert len(invalid) == 1
        assert invalid[0]["row_number"] == 3  # 헤더=1, 홍길동=2, 빈이름=3

    def test_empty_csv(self):
        valid, invalid = parse_csv("")
        assert valid == []
        assert len(invalid) == 1  # 헤더 없음 오류

    def test_email_only_row_valid(self):
        csv_data = "name,phone,email\n이메일만,, only@example.com\n"
        valid, invalid = parse_csv(csv_data)
        assert len(valid) == 1
        assert valid[0]["email"] == "only@example.com"
        assert valid[0]["phone"] is None


# ── import_contacts ───────────────────────────────────────────────────────────


class TestImportContacts:
    def test_mode_skip(self, db_session, admin_user):
        """기존 번호 있으면 건너뜀."""
        valid, _ = parse_csv(VALID_CSV)
        r1 = import_contacts(db_session, valid, created_by=admin_user.sub, mode="skip")
        db_session.commit()
        assert r1["created"] == 3

        # 같은 데이터 다시 import (skip)
        r2 = import_contacts(db_session, valid, created_by=admin_user.sub, mode="skip")
        db_session.commit()
        assert r2["skipped"] == 2  # phone 있는 행만 중복 체크
        assert r2["created"] == 0 or r2["created"] == 1  # email-only는 항상 새로 생성

    def test_mode_update(self, db_session, admin_user):
        """기존 번호 있으면 덮어씀."""
        valid, _ = parse_csv(VALID_CSV)
        import_contacts(db_session, valid, created_by=admin_user.sub, mode="skip")
        db_session.commit()

        # 이름 변경
        modified = [dict(r, name="변경된이름") for r in valid if r.get("phone")]
        r2 = import_contacts(db_session, modified, created_by=admin_user.sub, mode="update")
        db_session.commit()
        assert r2["updated"] >= 1

    def test_mode_create(self, db_session, admin_user):
        """항상 새로 추가."""
        valid, _ = parse_csv(VALID_CSV)
        import_contacts(db_session, valid, created_by=admin_user.sub, mode="skip")
        db_session.commit()

        r2 = import_contacts(db_session, valid, created_by=admin_user.sub, mode="create")
        db_session.commit()
        assert r2["created"] == len(valid)

    def test_returns_summary(self, db_session, admin_user):
        valid, _ = parse_csv(VALID_CSV)
        result = import_contacts(db_session, valid, created_by=admin_user.sub)
        db_session.commit()
        assert "created" in result
        assert "updated" in result
        assert "skipped" in result
        assert "errors" in result

    def test_empty_valid_rows(self, db_session, admin_user):
        result = import_contacts(db_session, [], created_by=admin_user.sub)
        assert result["created"] == 0


# ── export_contacts ───────────────────────────────────────────────────────────


class TestExportContacts:
    def test_exports_all(self, db_session, admin_user):
        valid, _ = parse_csv(VALID_CSV)
        import_contacts(db_session, valid, created_by=admin_user.sub)
        db_session.commit()

        csv_out = export_contacts(db_session)
        assert "홍길동" in csv_out
        assert "name" in csv_out  # 헤더 포함

    def test_exports_specific_ids(self, db_session, admin_user):
        valid, _ = parse_csv(VALID_CSV)
        import_contacts(db_session, valid, created_by=admin_user.sub)
        db_session.commit()

        contacts, _ = list_contacts(db_session, search="홍길동")
        assert len(contacts) >= 1
        csv_out = export_contacts(db_session, contact_ids=[contacts[0].id])
        assert "홍길동" in csv_out

    def test_empty_export(self, db_session):
        csv_out = export_contacts(db_session)
        lines = csv_out.strip().split("\n")
        # 헤더만 있거나 빈 데이터
        assert len(lines) >= 1
        assert "name" in lines[0]

    def test_csv_has_header(self, db_session, admin_user):
        csv_out = export_contacts(db_session)
        first_line = csv_out.split("\n")[0]
        assert "name" in first_line
        assert "phone" in first_line
