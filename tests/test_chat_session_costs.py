"""RCS 양방향 CHAT의 24시간·10건 비용 상한 회귀 테스트."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models import Campaign, Message, MsghubRequest
from app.msghub.codes import allocate_chat_session_costs
from app.msghub.schemas import ReportItem
from app.services.report import process_report, process_sent_query


def _pending_chat(db, user_sub: str, *, caller: str, phone: str, created_at: datetime):
    stamp = created_at.isoformat()
    campaign = Campaign(
        created_by=user_sub,
        caller_number=caller,
        message_type="short",
        content="답장",
        total_count=1,
        pending_count=1,
        state="DISPATCHED",
        created_at=stamp,
        rcs_messagebase_id="RPCSAXX001",
    )
    db.add(campaign)
    db.flush()
    request = MsghubRequest(campaign_id=campaign.id, chunk_index=0, sent_at=stamp)
    db.add(request)
    db.flush()
    message = Message(
        campaign_id=campaign.id,
        msghub_request_id=request.id,
        to_number=phone,
        to_number_raw=phone,
        cli_key=f"c{campaign.id}-0-0-a1b2c3",
        status="REG",
    )
    db.add(message)
    db.flush()
    return campaign, message


def _success_payload(message: Message) -> dict:
    return {
        "cliKey": message.cli_key,
        "msgKey": f"msg-{message.id}",
        "status": "DONE",
        "resultCode": "10000",
        "ch": "RCS",
        "productCode": "CHAT",
    }


def _process(db, path: str, messages: list[Message]):
    payloads = [_success_payload(message) for message in messages]
    if path == "webhook":
        return process_report(db, [ReportItem.from_dict(payload) for payload in payloads])
    return process_sent_query(db, payloads)


def test_allocator_charges_first_ten_and_restarts_at_24_hour_boundary():
    start = datetime(2026, 9, 18, tzinfo=UTC)
    times = [start + timedelta(minutes=index) for index in range(11)]
    times.append(start + timedelta(hours=24))
    assert allocate_chat_session_costs(times) == [8] * 10 + [0, 8]


@pytest.mark.parametrize("path", ["webhook", "sent_query"])
def test_chat_reports_cap_same_pair_even_when_older_results_arrive_late(
    db_session, sample_user, path,
):
    start = datetime(2026, 9, 18, tzinfo=UTC)
    rows = [
        _pending_chat(
            db_session,
            sample_user.sub,
            caller="0212345678",
            phone="01012345678",
            created_at=start + timedelta(minutes=index),
        )
        for index in range(11)
    ]
    db_session.commit()
    campaigns = [campaign for campaign, _ in rows]
    messages = [message for _, message in rows]

    # 가장 늦게 보낸 결과가 먼저 오면 처음에는 8원이지만, 앞선 결과가 도착한 뒤
    # 세션 전체를 다시 배분해 11번째 메시지와 그 캠페인 합계를 0원으로 고친다.
    assert _process(db_session, path, [messages[-1]]) == (1, [])
    assert (messages[-1].cost, campaigns[-1].total_cost) == (8, 8)
    assert _process(db_session, path, list(reversed(messages[:-1]))) == (10, [])

    assert [message.cost for message in messages] == [8] * 10 + [0]
    assert [campaign.total_cost for campaign in campaigns] == [8] * 10 + [0]


@pytest.mark.parametrize("path", ["webhook", "sent_query"])
def test_chat_cap_isolated_by_pair_and_new_24_hour_session(db_session, sample_user, path):
    start = datetime(2026, 9, 18, tzinfo=UTC)
    base_rows = [
        _pending_chat(
            db_session,
            sample_user.sub,
            caller="0212345678",
            phone="01012345678",
            created_at=start + timedelta(minutes=index),
        )
        for index in range(11)
    ]
    other_pair = _pending_chat(
        db_session,
        sample_user.sub,
        caller="0212345678",
        phone="01099999999",
        created_at=start + timedelta(minutes=11),
    )
    other_caller = _pending_chat(
        db_session,
        sample_user.sub,
        caller="0311234567",
        phone="01012345678",
        created_at=start + timedelta(minutes=12),
    )
    next_session = _pending_chat(
        db_session,
        sample_user.sub,
        caller="0212345678",
        phone="01012345678",
        created_at=start + timedelta(hours=24),
    )
    db_session.commit()

    all_rows = [*base_rows, other_pair, other_caller, next_session]
    assert _process(db_session, path, [message for _, message in all_rows]) == (14, [])
    assert [message.cost for _, message in base_rows] == [8] * 10 + [0]
    assert other_pair[1].cost == 8
    assert other_caller[1].cost == 8
    assert next_session[1].cost == 8
