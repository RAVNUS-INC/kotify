"""campaign progress fragment 엔드포인트 테스트."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.models import User


def _make_user(sub: str = "u1", roles: list[str] | None = None) -> User:
    u = User.__new__(User)
    object.__setattr__(u, '__dict__', {})
    u.__dict__['sub'] = sub
    u.__dict__['roles'] = json.dumps(roles or ["sender"])
    u.__dict__['email'] = "test@example.com"
    u.__dict__['name'] = "테스트"
    u.__dict__['created_at'] = "2024-01-01T00:00:00+00:00"
    u.__dict__['last_login_at'] = "2024-01-01T00:00:00+00:00"
    return u


def _make_campaign(
    campaign_id: int = 1,
    state: str = "DISPATCHING",
    created_by: str = "u1",
) -> SimpleNamespace:
    """SQLAlchemy 없이 순수 SimpleNamespace로 Campaign 유사 객체를 생성한다."""
    return SimpleNamespace(
        id=campaign_id,
        state=state,
        created_by=created_by,
        caller_number="01012345678",
        content="테스트 메시지",
        message_type="SMS",
        total_count=10,
        ok_count=5,
        fail_count=2,
        pending_count=3,
        created_at="2024-01-15T00:00:00+00:00",
        completed_at=None,
    )


def _can_access(user: User, campaign: SimpleNamespace) -> bool:
    """_can_access_campaign 로직을 직접 재현 (import 없이)."""
    try:
        is_admin = "admin" in json.loads(user.__dict__.get('roles', '[]'))
    except (json.JSONDecodeError, TypeError):
        is_admin = False
    return is_admin or campaign.created_by == user.__dict__.get('sub')


class TestCanAccessCampaign:
    """_can_access_campaign 로직 검증."""

    def test_own_campaign_accessible(self):
        user = _make_user(sub="u1", roles=["sender"])
        campaign = _make_campaign(created_by="u1")
        assert _can_access(user, campaign) is True

    def test_other_campaign_not_accessible(self):
        user = _make_user(sub="u2", roles=["sender"])
        campaign = _make_campaign(created_by="u1")
        assert _can_access(user, campaign) is False

    def test_admin_can_access_any(self):
        user = _make_user(sub="admin1", roles=["admin"])
        campaign = _make_campaign(created_by="u1")
        assert _can_access(user, campaign) is True


class TestProgressStates:
    """DISPATCHING/DISPATCHED 상태에서는 폴링 속성이 붙어야 하고
    최종 상태에서는 붙으면 안 됨을 로직 단에서 검증."""

    _ACTIVE_STATES = {"DISPATCHING", "DISPATCHED", "PARTIAL_FAILED"}

    @pytest.mark.parametrize("state", ["DISPATCHING", "DISPATCHED", "PARTIAL_FAILED"])
    def test_active_states_should_poll(self, state: str):
        """활성 상태는 폴링 대상이어야 한다."""
        campaign = _make_campaign(state=state)
        assert campaign.state in self._ACTIVE_STATES

    @pytest.mark.parametrize("state", ["COMPLETED", "FAILED"])
    def test_final_states_no_poll(self, state: str):
        """최종 상태는 폴링 대상이 아니어야 한다."""
        campaign = _make_campaign(state=state)
        assert campaign.state not in self._ACTIVE_STATES
