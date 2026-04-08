"""그룹 서비스 테스트."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from app.models import ContactGroup, ContactGroupMember, User
from app.services.contacts import create_contact
from app.services.groups import (
    add_members,
    create_group,
    delete_group,
    expand_groups_to_contacts,
    get_group_size,
    list_groups,
    list_members,
    remove_members,
    update_group,
)

# ── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture
def admin_user(db_session):
    user = User(
        sub="admin-sub-001",
        email="admin@example.com",
        name="관리자",
        roles=json.dumps(["admin"]),
        created_at=datetime.now(UTC).isoformat(),
        last_login_at=datetime.now(UTC).isoformat(),
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def sample_group(db_session, admin_user):
    g = create_group(db_session, name="테스트그룹", created_by=admin_user.sub, description="설명")
    db_session.commit()
    return g


@pytest.fixture
def contacts_3(db_session, admin_user):
    """테스트용 연락처 3개."""
    cs = []
    for i in range(3):
        c = create_contact(
            db_session,
            name=f"연락처{i}",
            created_by=admin_user.sub,
            phone=f"0101234000{i}",
        )
        cs.append(c)
    db_session.commit()
    return cs


# ── create ───────────────────────────────────────────────────────────────────


class TestCreateGroup:
    def test_creates_group(self, db_session, admin_user):
        g = create_group(db_session, name="신규그룹", created_by=admin_user.sub)
        db_session.commit()
        assert g.id is not None
        assert g.name == "신규그룹"

    def test_optional_description(self, db_session, admin_user):
        g = create_group(db_session, name="설명없음", created_by=admin_user.sub)
        db_session.commit()
        assert g.description is None


# ── update ───────────────────────────────────────────────────────────────────


class TestUpdateGroup:
    def test_updates_name(self, db_session, sample_group):
        update_group(db_session, sample_group.id, name="변경된이름")
        db_session.commit()
        refreshed = db_session.get(ContactGroup, sample_group.id)
        assert refreshed.name == "변경된이름"

    def test_raises_for_missing(self, db_session):
        with pytest.raises(ValueError, match="찾을 수 없습니다"):
            update_group(db_session, 99999, name="없음")


# ── delete ───────────────────────────────────────────────────────────────────


class TestDeleteGroup:
    def test_deletes_group(self, db_session, sample_group):
        gid = sample_group.id
        delete_group(db_session, gid)
        db_session.commit()
        assert db_session.get(ContactGroup, gid) is None

    def test_deletes_memberships_too(self, db_session, sample_group, contacts_3, admin_user):
        add_members(db_session, sample_group.id, [c.id for c in contacts_3], added_by=admin_user.sub)
        db_session.commit()
        assert get_group_size(db_session, sample_group.id) == 3

        gid = sample_group.id
        delete_group(db_session, gid)
        db_session.commit()

        from sqlalchemy import select
        remaining = db_session.execute(
            select(ContactGroupMember).where(ContactGroupMember.group_id == gid)
        ).scalars().all()
        assert list(remaining) == []

    def test_raises_for_missing(self, db_session):
        with pytest.raises(ValueError, match="찾을 수 없습니다"):
            delete_group(db_session, 99999)


# ── add/remove members ────────────────────────────────────────────────────────


class TestMembers:
    def test_add_members(self, db_session, sample_group, contacts_3, admin_user):
        ids = [c.id for c in contacts_3]
        added = add_members(db_session, sample_group.id, ids, added_by=admin_user.sub)
        db_session.commit()
        assert added == 3
        assert get_group_size(db_session, sample_group.id) == 3

    def test_add_members_no_duplicate(self, db_session, sample_group, contacts_3, admin_user):
        ids = [contacts_3[0].id]
        add_members(db_session, sample_group.id, ids, added_by=admin_user.sub)
        db_session.commit()
        # 같은 멤버 다시 추가
        added2 = add_members(db_session, sample_group.id, ids, added_by=admin_user.sub)
        db_session.commit()
        assert added2 == 0
        assert get_group_size(db_session, sample_group.id) == 1

    def test_add_empty_list(self, db_session, sample_group):
        added = add_members(db_session, sample_group.id, [])
        assert added == 0

    def test_remove_members(self, db_session, sample_group, contacts_3, admin_user):
        ids = [c.id for c in contacts_3]
        add_members(db_session, sample_group.id, ids, added_by=admin_user.sub)
        db_session.commit()

        removed = remove_members(db_session, sample_group.id, [contacts_3[0].id])
        db_session.commit()
        assert removed == 1
        assert get_group_size(db_session, sample_group.id) == 2

    def test_remove_empty_list(self, db_session, sample_group):
        removed = remove_members(db_session, sample_group.id, [])
        assert removed == 0

    def test_list_members(self, db_session, sample_group, contacts_3, admin_user):
        ids = [c.id for c in contacts_3]
        add_members(db_session, sample_group.id, ids, added_by=admin_user.sub)
        db_session.commit()

        members, total = list_members(db_session, sample_group.id)
        assert total == 3
        member_ids = {m.id for m in members}
        assert member_ids == set(ids)


# ── expand_groups_to_contacts ─────────────────────────────────────────────────


class TestExpandGroups:
    def test_expand_single_group(self, db_session, sample_group, contacts_3, admin_user):
        ids = [c.id for c in contacts_3]
        add_members(db_session, sample_group.id, ids, added_by=admin_user.sub)
        db_session.commit()

        result = expand_groups_to_contacts(db_session, [sample_group.id])
        assert len(result) == 3

    def test_expand_deduplicates_across_groups(self, db_session, contacts_3, admin_user):
        """두 그룹에 같은 연락처가 있어도 한 번만 나와야 함."""
        g1 = create_group(db_session, name="그룹A", created_by=admin_user.sub)
        g2 = create_group(db_session, name="그룹B", created_by=admin_user.sub)
        db_session.commit()

        # contacts_3[0]은 두 그룹 모두에 속함
        add_members(db_session, g1.id, [contacts_3[0].id, contacts_3[1].id], added_by=admin_user.sub)
        add_members(db_session, g2.id, [contacts_3[0].id, contacts_3[2].id], added_by=admin_user.sub)
        db_session.commit()

        result = expand_groups_to_contacts(db_session, [g1.id, g2.id])
        result_ids = [c.id for c in result]
        # 중복 없이 3개
        assert len(result_ids) == 3
        assert len(set(result_ids)) == 3

    def test_expand_empty_list(self, db_session):
        result = expand_groups_to_contacts(db_session, [])
        assert result == []

    def test_expand_empty_group(self, db_session, sample_group):
        result = expand_groups_to_contacts(db_session, [sample_group.id])
        assert result == []


# ── list_groups ───────────────────────────────────────────────────────────────


class TestListGroups:
    def test_list_all(self, db_session, sample_group):
        groups, total = list_groups(db_session)
        assert total >= 1

    def test_search(self, db_session, admin_user):
        create_group(db_session, name="검색대상그룹", created_by=admin_user.sub)
        db_session.commit()
        groups, total = list_groups(db_session, search="검색대상")
        assert total >= 1

    def test_pagination(self, db_session, admin_user):
        for i in range(5):
            create_group(db_session, name=f"페이지그룹{i}", created_by=admin_user.sub)
        db_session.commit()
        g1, _ = list_groups(db_session, per_page=2, page=1)
        g2, _ = list_groups(db_session, per_page=2, page=2)
        ids1 = {g.id for g in g1}
        ids2 = {g.id for g in g2}
        assert ids1.isdisjoint(ids2)


# ── get_group_size ────────────────────────────────────────────────────────────


class TestGetGroupSize:
    def test_empty_group(self, db_session, sample_group):
        assert get_group_size(db_session, sample_group.id) == 0

    def test_with_members(self, db_session, sample_group, contacts_3, admin_user):
        add_members(db_session, sample_group.id, [contacts_3[0].id], added_by=admin_user.sub)
        db_session.commit()
        assert get_group_size(db_session, sample_group.id) == 1
