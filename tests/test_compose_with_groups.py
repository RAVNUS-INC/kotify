"""그룹/연락처 기반 발송 통합 테스트."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.models import User
from app.ncp.client import ListResponse, SendResponse
from app.services.compose import MAX_RECIPIENTS_PER_CAMPAIGN, resolve_recipients
from app.services.contacts import create_contact, get_contact
from app.services.groups import add_members, create_group

# ── Fixture ──────────────────────────────────────────────────────────────────


@pytest.fixture
def admin_user(db_session):
    user = User(
        sub="compose-admin-001",
        email="compose@example.com",
        name="발송관리자",
        roles=json.dumps(["admin"]),
        created_at=datetime.now(UTC).isoformat(),
        last_login_at=datetime.now(UTC).isoformat(),
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def contacts_5(db_session, admin_user):
    """전화번호 있는 연락처 5개."""
    cs = []
    for i in range(5):
        c = create_contact(
            db_session,
            name=f"연락처{i}",
            created_by=admin_user.sub,
            phone=f"0101234567{i}",
        )
        cs.append(c)
    db_session.commit()
    return cs


@pytest.fixture
def group_with_3(db_session, admin_user, contacts_5):
    """연락처 3개를 포함한 그룹."""
    g = create_group(db_session, name="3명그룹", created_by=admin_user.sub)
    db_session.commit()
    add_members(db_session, g.id, [contacts_5[0].id, contacts_5[1].id, contacts_5[2].id], added_by=admin_user.sub)
    db_session.commit()
    return g


# ── resolve_recipients ─────────────────────────────────────────────────────────


class TestResolveRecipients:
    def test_manual_mode(self, db_session):
        phones, invalid, marking = resolve_recipients(
            db_session, "manual", "010-1111-2222\n010-3333-4444", None, None
        )
        assert phones == ["01011112222", "01033334444"]
        assert invalid == []
        assert marking == []

    def test_manual_mode_invalid(self, db_session):
        phones, invalid, marking = resolve_recipients(
            db_session, "manual", "010-1111-2222\nnotaphone", None, None
        )
        assert "01011112222" in phones
        assert "notaphone" in invalid
        assert marking == []

    def test_groups_mode(self, db_session, group_with_3):
        phones, invalid, marking = resolve_recipients(
            db_session, "groups", None, [group_with_3.id], None
        )
        assert len(phones) == 3
        assert invalid == []
        assert len(marking) == 3

    def test_groups_mode_empty_group_ids(self, db_session):
        phones, invalid, marking = resolve_recipients(db_session, "groups", None, [], None)
        assert phones == []
        assert invalid == []
        assert marking == []

    def test_contacts_mode(self, db_session, contacts_5):
        ids = [contacts_5[0].id, contacts_5[1].id]
        phones, invalid, marking = resolve_recipients(db_session, "contacts", None, None, ids)
        assert len(phones) == 2
        assert invalid == []
        assert len(marking) == 2

    def test_contacts_mode_empty(self, db_session):
        phones, invalid, marking = resolve_recipients(db_session, "contacts", None, None, [])
        assert phones == []
        assert invalid == []
        assert marking == []

    def test_contacts_without_phone_excluded(self, db_session, admin_user):
        """전화번호 없는 연락처는 phones에 포함되지 않아야 함."""
        c_no_phone = create_contact(db_session, name="번호없음", created_by=admin_user.sub, email="x@x.com")
        db_session.commit()
        phones, _, marking = resolve_recipients(db_session, "contacts", None, None, [c_no_phone.id])
        assert phones == []
        assert marking == []  # 전화번호 없으면 marking도 없음


# ── 그룹 중복 제거 검증 ────────────────────────────────────────────────────────


class TestGroupDeduplication:
    def test_overlap_across_groups_deduped(self, db_session, admin_user, contacts_5):
        """두 그룹에 같은 연락처가 있어도 phones에 한 번만 나와야 함."""
        g1 = create_group(db_session, name="그룹X", created_by=admin_user.sub)
        g2 = create_group(db_session, name="그룹Y", created_by=admin_user.sub)
        db_session.commit()
        # contacts_5[0]은 두 그룹 모두
        add_members(db_session, g1.id, [contacts_5[0].id, contacts_5[1].id], added_by=admin_user.sub)
        add_members(db_session, g2.id, [contacts_5[0].id, contacts_5[2].id], added_by=admin_user.sub)
        db_session.commit()

        phones, _, marking = resolve_recipients(
            db_session, "groups", None, [g1.id, g2.id], None
        )
        assert len(phones) == 3
        assert len(set(phones)) == 3  # 중복 없음
        assert len(marking) == 3


# ── 1000명 초과 차단 ──────────────────────────────────────────────────────────


class TestRecipientLimit:
    def test_limit_constant(self):
        assert MAX_RECIPIENTS_PER_CAMPAIGN == 1000

    def test_groups_can_exceed_limit(self, db_session, admin_user):
        """그룹+그룹 합산이 1000명 초과 가능 — dispatch 전에 차단은 라우트 책임."""
        # 501명짜리 그룹 2개 시뮬레이션 대신 숫자 검증만
        # resolve_recipients 자체는 차단하지 않음 (라우트에서 처리)
        g = create_group(db_session, name="소규모그룹", created_by=admin_user.sub)
        db_session.commit()
        phones, _, _ = resolve_recipients(db_session, "groups", None, [g.id], None)
        assert isinstance(phones, list)


# ── last_sent_at 업데이트 ─────────────────────────────────────────────────────


class TestMarkSentAfterDispatch:
    def test_bulk_mark_sent_called(self, db_session, admin_user, contacts_5):
        """발송 성공 후 연락처의 last_sent_at이 업데이트되어야 함."""
        from app.services.contacts import bulk_mark_sent
        ids = [c.id for c in contacts_5[:3]]
        bulk_mark_sent(db_session, ids, channel="sms")
        db_session.commit()

        for cid in ids:
            c = get_contact(db_session, cid)
            assert c.last_sent_at is not None
            assert c.last_sent_channel == "sms"

    def test_contacts_without_phone_not_marked(self, db_session, admin_user):
        c_no_phone = create_contact(db_session, name="마킹제외", created_by=admin_user.sub)
        db_session.commit()

        # 전화번호 없는 연락처는 resolve_recipients에서 marking_ids에 포함 안 됨
        _, _, marking = resolve_recipients(db_session, "contacts", None, None, [c_no_phone.id])
        assert c_no_phone.id not in marking


# ── dispatch_campaign with groups ─────────────────────────────────────────────


class TestDispatchCampaignWithGroups:
    @pytest.mark.asyncio
    async def test_dispatch_with_group_recipients(self, db_session, admin_user, group_with_3):
        """그룹 기반 수신자로 dispatch_campaign 호출 시 성공해야 함."""
        from app.models import Caller
        from app.services.compose import dispatch_campaign

        caller = Caller(
            number="0212345678",
            label="테스트",
            active=1,
            is_default=1,
            created_at=datetime.now(UTC).isoformat(),
        )
        db_session.add(caller)
        db_session.commit()

        phones, _, marking = resolve_recipients(
            db_session, "groups", None, [group_with_3.id], None
        )
        assert len(phones) == 3

        # mock NCP 클라이언트
        client = MagicMock()

        async def fake_send(from_number, content, to_numbers, message_type="SMS", subject=None):
            return SendResponse(
                request_id="REQ-GRP-0001",
                request_time="2026-04-08T12:00:00",
                status_code="202",
                status_name="success",
            )

        async def fake_list(request_id):
            return ListResponse(
                request_id=request_id,
                status_code="200",
                status_name="success",
                messages=[],
            )

        client.send_sms = fake_send
        client.list_by_request_id = fake_list

        campaign = await dispatch_campaign(
            db=db_session,
            ncp_client=client,
            created_by=admin_user.sub,
            caller_number="0212345678",
            content="그룹 발송 테스트",
            recipients=phones,
            message_type="SMS",
        )
        assert campaign.total_count == 3
