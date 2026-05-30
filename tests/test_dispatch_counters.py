"""dispatch_campaign 카운터 정합성 테스트 — item 단위 실패 즉시 반영 (H1).

msghub 가 HTTP 200 으로 응답하면서 응답 본문 item 단위로 일부 수신자를 실패
처리하는 경우, 웹훅(배달 리포트) 도착 전에도 campaign.fail_count/pending_count
가 정확해야 한다. 기존에는 청크 전체 실패만 집계해 item 실패가 누락되어
fail_count=0 으로 오표시되었다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import Campaign, Message, MsghubRequest
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import ReserveResponse, SendResponse, SendResultItem
from app.services.compose import _create_messages_from_response, dispatch_campaign


class _FakeRcsClient:
    """send_rcs 만 흉내내는 테스트 클라이언트 (덕 타이핑).

    fail_phones 에 든 번호는 item 단위 실패 코드(29002)로, 나머지는 성공(10000)
    으로 응답한다 — HTTP 200 부분 실패 시나리오를 재현한다.
    """

    def __init__(self, fail_phones: set[str] | None = None):
        self.fail_phones = set(fail_phones or [])
        self.send_calls = 0

    async def send_rcs(
        self, *, messagebase_id, callback, recv_list, fb_info_lst,
        resv_yn=None, resv_req_dt=None,
    ):
        self.send_calls += 1
        items = [
            SendResultItem(
                cli_key=recv.cli_key,
                msg_key=(f"mk-{recv.cli_key}" if recv.phone not in self.fail_phones else ""),
                phone=recv.phone,
                code=(SUCCESS_CODE if recv.phone not in self.fail_phones else "29002"),
                message=("성공" if recv.phone not in self.fail_phones else "수신거부 번호"),
            )
            for recv in recv_list
        ]
        return SendResponse(code="10000", message="OK", items=items)


def _status_counts(db, campaign_id) -> dict[str, int]:
    rows = db.execute(
        select(Message.status, func.count())
        .where(Message.campaign_id == campaign_id)
        .group_by(Message.status)
    ).all()
    return dict(rows)


# ── dispatch_campaign 통합 (H1) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_item_failures_reflected_immediately(db_session, sample_user, sample_caller):
    """HTTP 200 응답 내 item 실패 2건이 dispatch 직후 fail_count/pending_count 에 반영."""
    recipients = ["01000000001", "01000000002", "01000000003", "01000000004"]
    client = _FakeRcsClient(fail_phones={"01000000002", "01000000004"})

    campaign = await dispatch_campaign(
        db=db_session,
        msghub_client=client,
        created_by=sample_user.sub,
        caller_number=sample_caller.number,
        content="안내 메시지입니다",
        recipients=recipients,
        message_type="SMS",
    )

    # 웹훅 도착 전인데도 item 실패 2건이 즉시 집계됨
    assert campaign.fail_count == 2
    assert campaign.pending_count == 2
    assert campaign.state == "PARTIAL_FAILED"

    counts = _status_counts(db_session, campaign.id)
    assert counts.get("FAILED") == 2
    assert counts.get("REG") == 2


@pytest.mark.asyncio
async def test_dispatch_all_success_pending_until_webhook(db_session, sample_user, sample_caller):
    """전건 접수 성공 → fail_count=0, 전건 pending(배달 리포트 대기), DISPATCHED."""
    recipients = ["01000000001", "01000000002", "01000000003"]
    client = _FakeRcsClient()  # 실패 없음

    campaign = await dispatch_campaign(
        db=db_session,
        msghub_client=client,
        created_by=sample_user.sub,
        caller_number=sample_caller.number,
        content="안내 메시지입니다",
        recipients=recipients,
        message_type="SMS",
    )

    assert campaign.fail_count == 0
    assert campaign.pending_count == 3
    assert campaign.state == "DISPATCHED"  # REG 는 아직 성공 아님 — pending


@pytest.mark.asyncio
async def test_dispatch_all_items_fail(db_session, sample_user, sample_caller):
    """전건 item 실패 → fail_count=전체, pending=0, FAILED."""
    recipients = ["01000000001", "01000000002"]
    client = _FakeRcsClient(fail_phones=set(recipients))

    campaign = await dispatch_campaign(
        db=db_session,
        msghub_client=client,
        created_by=sample_user.sub,
        caller_number=sample_caller.number,
        content="안내 메시지입니다",
        recipients=recipients,
        message_type="SMS",
    )

    assert campaign.fail_count == 2
    assert campaign.pending_count == 0
    assert campaign.state == "FAILED"


# ── _create_messages_from_response 반환 계약 (H1) ─────────────────────────────


def _make_campaign_req(db, sub):
    campaign = Campaign(
        created_by=sub, caller_number="0212345678", message_type="short",
        content="x", total_count=3, pending_count=3, state="DISPATCHING",
        created_at="2026-01-01T00:00:00+00:00",
    )
    db.add(campaign)
    db.flush()
    req = MsghubRequest(
        campaign_id=campaign.id, chunk_index=0,
        sent_at="2026-01-01T00:00:00+00:00",
    )
    db.add(req)
    db.flush()
    return campaign, req


def test_create_messages_returns_accepted_and_failed(db_session, sample_user):
    """SendResponse 의 item 성공/실패를 (accepted, failed) 로 정확히 반환한다."""
    campaign, req = _make_campaign_req(db_session, sample_user.sub)
    resp = SendResponse(code="10000", message="OK", items=[
        SendResultItem(cli_key="c1-0-0", msg_key="m0", phone="01000000001", code=SUCCESS_CODE, message="ok"),
        SendResultItem(cli_key="c1-0-1", msg_key="", phone="01000000002", code="29002", message="blocked"),
        SendResultItem(cli_key="c1-0-2", msg_key="m2", phone="01000000003", code=SUCCESS_CODE, message="ok"),
    ])

    accepted, failed = _create_messages_from_response(
        db_session, campaign.id, req.id, resp,
        ["01000000001", "01000000002", "01000000003"], 0,
    )

    assert (accepted, failed) == (2, 1)


def test_create_messages_reserve_branch_all_accepted(db_session, sample_user):
    """ReserveResponse(예약)는 전건 PENDING 으로 accepted, 실패 0 — 예약 오집계 방지."""
    campaign, req = _make_campaign_req(db_session, sample_user.sub)
    resp = ReserveResponse(code="10000", message="OK", web_req_id="W1")

    accepted, failed = _create_messages_from_response(
        db_session, campaign.id, req.id, resp,
        ["01000000001", "01000000002"], 0,
    )

    assert (accepted, failed) == (2, 0)
