"""예약 취소 상태 정합성 테스트 (H6).

msghub 가 취소를 거부(이미 발송/취소)하면 로컬 상태를 RESERVE_CANCELED 로
오표기하지 않고 유지해야 한다. 정상 취소만 RESERVE_CANCELED 로 전이한다.
정상 취소는 예약 접수로 대기(PENDING) 중인 메시지도 CANCELED 로 바꾼다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Campaign, Message, MsghubRequest
from app.msghub.schemas import MsghubBadRequest, MsghubError
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


def _add_chunk(db, campaign, chunk_index, statuses, phone_prefix="0101234"):
    """캠페인에 청크 1개(MsghubRequest) + 상태별 메시지를 붙인다. 반환: cli_key 목록."""
    req = MsghubRequest(
        campaign_id=campaign.id, chunk_index=chunk_index,
        sent_at="2026-06-01T03:00:00+00:00",  # 예약 발송은 예약 시각(UTC)을 저장
        response_message="fail" if "FAILED" in statuses else None,
    )
    db.add(req)
    db.flush()
    keys = []
    for i, status in enumerate(statuses):
        key = f"c{campaign.id}-{chunk_index}-{i}"
        phone = f"{phone_prefix}{chunk_index}{i:03d}"
        db.add(Message(
            campaign_id=campaign.id, msghub_request_id=req.id, to_number=phone,
            to_number_raw=phone, cli_key=key, status=status,
        ))
        keys.append(key)
    db.commit()
    return keys


def _statuses(db, campaign):
    return dict(db.execute(
        select(Message.cli_key, Message.status).where(Message.campaign_id == campaign.id)
    ).all())


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


class _OkClient:
    async def cancel_reservation(self, web_req_id, reason):
        return None


@pytest.mark.asyncio
async def test_cancel_success_marks_pending_messages_canceled(
    db_session, sample_user, monkeypatch
):
    """정상 취소는 그 캠페인의 대기(PENDING) 메시지만 CANCELED 로 — 발송되지 않을 메시지가
    대화방·수신자 배지에 영영 대기로 보이지 않게. 청크 요청 실패(FAILED)와 다른 예약은 그대로.
    """
    campaign = _reserved_campaign(db_session, sample_user.sub, "wr-3", "2026-01-01T00:00:02+00:00")
    accepted = _add_chunk(db_session, campaign, 0, ["PENDING", "PENDING"])
    failed = _add_chunk(db_session, campaign, 1, ["FAILED"])
    # 같은 번호에 걸린 다른 예약 — 취소 대상이 아니다.
    other = _reserved_campaign(db_session, sample_user.sub, "wr-4", "2026-01-01T00:00:03+00:00")
    other_keys = _add_chunk(db_session, other, 0, ["PENDING"])

    monkeypatch.setattr("app.main.get_msghub_client", lambda: _OkClient())

    await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert _statuses(db_session, campaign) == {
        accepted[0]: "CANCELED",
        accepted[1]: "CANCELED",
        failed[0]: "FAILED",
    }
    assert _statuses(db_session, other) == {other_keys[0]: "PENDING"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (MsghubBadRequest("이미 발송됨"), 409),  # 발송됐을 수 있다 — 리포트가 결과를 확정
        (MsghubError("timeout"), 502),
    ],
)
async def test_cancel_failure_keeps_messages_pending(
    db_session, sample_user, monkeypatch, error, status_code
):
    """취소가 거부·실패하면 메시지도 PENDING 그대로 — 재조정·리포트가 계속 결과를 받는다."""
    campaign = _reserved_campaign(db_session, sample_user.sub, "wr-5", "2026-01-01T00:00:04+00:00")
    keys = _add_chunk(db_session, campaign, 0, ["PENDING"])

    class _FailingClient:
        async def cancel_reservation(self, web_req_id, reason):
            raise error

    monkeypatch.setattr("app.main.get_msghub_client", lambda: _FailingClient())

    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert resp.status_code == status_code
    assert _statuses(db_session, campaign) == {keys[0]: "PENDING"}
