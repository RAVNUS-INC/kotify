"""연락처 서비스 + 권한별 라우트 테스트."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.models import Contact, User
from app.services.contacts import (
    bulk_mark_sent,
    create_contact,
    delete_contact,
    get_contact,
    list_contacts,
    mark_sent,
    update_contact,
)

# ── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture
def sender_user(db_session):
    """sender 역할 사용자."""
    user = User(
        sub="sender-sub-001",
        email="sender@example.com",
        name="발송자",
        roles=json.dumps(["sender"]),
        created_at=datetime.now(UTC).isoformat(),
        last_login_at=datetime.now(UTC).isoformat(),
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def sample_contact(db_session, sender_user):
    """테스트용 연락처."""
    contact = create_contact(
        db_session,
        name="홍길동",
        created_by=sender_user.sub,
        phone="01012345678",
        email="hong@example.com",
        department="마케팅팀",
    )
    db_session.commit()
    return contact


# ── create ───────────────────────────────────────────────────────────────────


class TestCreateContact:
    def test_creates_contact(self, db_session, sender_user):
        c = create_contact(db_session, name="김철수", created_by=sender_user.sub, phone="01099998888")
        db_session.commit()
        assert c.id is not None
        assert c.name == "김철수"
        assert c.phone == "01099998888"
        assert c.active == 1

    def test_optional_fields_are_none(self, db_session, sender_user):
        c = create_contact(db_session, name="이름만", created_by=sender_user.sub)
        db_session.commit()
        assert c.phone is None
        assert c.email is None
        assert c.department is None
        assert c.notes is None

    def test_created_at_set(self, db_session, sender_user):
        c = create_contact(db_session, name="타임스탬프", created_by=sender_user.sub)
        db_session.commit()
        assert c.created_at
        assert c.updated_at


# ── update ───────────────────────────────────────────────────────────────────


class TestUpdateContact:
    def test_updates_name(self, db_session, sample_contact):
        update_contact(db_session, sample_contact.id, name="홍길동2")
        db_session.commit()
        refreshed = db_session.get(Contact, sample_contact.id)
        assert refreshed.name == "홍길동2"

    def test_deactivate(self, db_session, sample_contact):
        update_contact(db_session, sample_contact.id, active=0)
        db_session.commit()
        refreshed = db_session.get(Contact, sample_contact.id)
        assert refreshed.active == 0

    def test_raises_for_missing_contact(self, db_session):
        with pytest.raises(ValueError, match="찾을 수 없습니다"):
            update_contact(db_session, 99999, name="없음")

    def test_updated_at_changes(self, db_session, sample_contact):
        old_ts = sample_contact.updated_at
        update_contact(db_session, sample_contact.id, notes="메모 추가")
        db_session.commit()
        refreshed = db_session.get(Contact, sample_contact.id)
        assert refreshed.updated_at >= old_ts


# ── delete ───────────────────────────────────────────────────────────────────


class TestDeleteContact:
    def test_deletes_contact(self, db_session, sample_contact):
        cid = sample_contact.id
        delete_contact(db_session, cid)
        db_session.commit()
        assert db_session.get(Contact, cid) is None

    def test_raises_for_missing(self, db_session):
        with pytest.raises(ValueError, match="찾을 수 없습니다"):
            delete_contact(db_session, 99999)


# ── get ──────────────────────────────────────────────────────────────────────


class TestGetContact:
    def test_returns_contact(self, db_session, sample_contact):
        c = get_contact(db_session, sample_contact.id)
        assert c is not None
        assert c.name == "홍길동"

    def test_returns_none_for_missing(self, db_session):
        assert get_contact(db_session, 99999) is None


# ── list ─────────────────────────────────────────────────────────────────────


class TestListContacts:
    def test_returns_all(self, db_session, sample_contact):
        contacts, total = list_contacts(db_session)
        assert total >= 1
        assert any(c.id == sample_contact.id for c in contacts)

    def test_search_by_name(self, db_session, sample_contact):
        contacts, total = list_contacts(db_session, search="홍길동")
        assert total >= 1
        assert all("홍" in c.name for c in contacts)

    def test_search_by_phone(self, db_session, sample_contact):
        contacts, total = list_contacts(db_session, search="01012345678")
        assert total >= 1

    def test_search_by_department(self, db_session, sample_contact):
        contacts, total = list_contacts(db_session, search="마케팅")
        assert total >= 1

    def test_filter_by_department(self, db_session, sample_contact):
        contacts, total = list_contacts(db_session, department="마케팅팀")
        assert total >= 1

    def test_active_only(self, db_session, sender_user, sample_contact):
        update_contact(db_session, sample_contact.id, active=0)
        db_session.commit()
        contacts, total = list_contacts(db_session, active_only=True)
        assert all(c.active == 1 for c in contacts)

    def test_pagination(self, db_session, sender_user):
        for i in range(5):
            create_contact(db_session, name=f"페이지테스트{i}", created_by=sender_user.sub)
        db_session.commit()
        _, total = list_contacts(db_session, per_page=2, page=1)
        contacts_p1, _ = list_contacts(db_session, per_page=2, page=1)
        contacts_p2, _ = list_contacts(db_session, per_page=2, page=2)
        assert len(contacts_p1) == 2
        ids_p1 = {c.id for c in contacts_p1}
        ids_p2 = {c.id for c in contacts_p2}
        assert ids_p1.isdisjoint(ids_p2)

    def test_no_results(self, db_session):
        contacts, total = list_contacts(db_session, search="존재하지않는검색어XXXYYY")
        assert total == 0
        assert contacts == []


# ── mark_sent ────────────────────────────────────────────────────────────────


class TestMarkSent:
    def test_mark_sent_updates_fields(self, db_session, sample_contact):
        assert sample_contact.last_sent_at is None
        mark_sent(db_session, sample_contact.id, channel="sms")
        db_session.commit()
        refreshed = db_session.get(Contact, sample_contact.id)
        assert refreshed.last_sent_at is not None
        assert refreshed.last_sent_channel == "sms"

    def test_mark_sent_missing_contact_noop(self, db_session):
        # 존재하지 않는 ID는 조용히 무시
        mark_sent(db_session, 99999, channel="sms")

    def test_bulk_mark_sent(self, db_session, sender_user):
        c1 = create_contact(db_session, name="벌크1", created_by=sender_user.sub, phone="01011110001")
        c2 = create_contact(db_session, name="벌크2", created_by=sender_user.sub, phone="01011110002")
        db_session.commit()

        bulk_mark_sent(db_session, [c1.id, c2.id], channel="sms")
        db_session.commit()

        r1 = db_session.get(Contact, c1.id)
        r2 = db_session.get(Contact, c2.id)
        assert r1.last_sent_at is not None
        assert r2.last_sent_channel == "sms"

    def test_bulk_mark_sent_empty_list_noop(self, db_session):
        bulk_mark_sent(db_session, [], channel="sms")
