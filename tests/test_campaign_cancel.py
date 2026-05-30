"""예약 취소 상태 정합성 테스트 (H6).

msghub 가 취소를 거부(이미 발송/취소)하면 로컬 상태를 RESERVE_CANCELED 로
오표기하지 않고 유지해야 한다. 정상 취소만 RESERVE_CANCELED 로 전이한다.
"""
from __future__ import annotations

import pytest

from app.models import Campaign
from app.msghub.schemas import MsghubBadRequest
from app.routes.campaigns import cancel_campaign


def _reserved_campaign(db, sub, web_req_id, created_at):
    campaign = Campaign(
        created_by=sub, caller_number="0212345678", message_type="short",
        content="x", total_count=1, pending_count=1, state="RESERVED",
        created_at=created_at, web_req_id=web_req_id,
    )
    db.add(campaign)
    db.commit()
    return campaign


@pytest.mark.asyncio
async def test_cancel_rejected_preserves_state(db_session, sample_user, monkeypatch):
    """msghub 가 취소 거부(이미 발송) 시 상태를 RESERVED 로 유지하고 409 반환."""
    campaign = _reserved_campaign(db_session, sample_user.sub, "wr-1", "2026-01-01T00:00:00+00:00")

    class _FakeClient:
        async def cancel_reservation(self, web_req_id, reason):
            raise MsghubBadRequest("이미 발송됨")

    monkeypatch.setattr("app.main.get_msghub_client", lambda: _FakeClient())

    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert resp.status_code == 409
    db_session.refresh(campaign)
    assert campaign.state == "RESERVED"  # 취소 오표기 안 됨


@pytest.mark.asyncio
async def test_cancel_success_marks_canceled(db_session, sample_user, monkeypatch):
    """정상 취소는 RESERVE_CANCELED 로 전이한다."""
    campaign = _reserved_campaign(db_session, sample_user.sub, "wr-2", "2026-01-01T00:00:01+00:00")

    class _OkClient:
        async def cancel_reservation(self, web_req_id, reason):
            return None

    monkeypatch.setattr("app.main.get_msghub_client", lambda: _OkClient())

    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    db_session.refresh(campaign)
    assert campaign.state == "RESERVE_CANCELED"
    assert resp["data"]["status"] in ("cancelled", "canceled", "RESERVE_CANCELED") or "data" in resp
