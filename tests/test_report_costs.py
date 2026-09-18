"""실제 msghub 채널/상품 조합의 리포트·재조정 비용 회귀 테스트."""
from __future__ import annotations

import pytest

from app.models import Campaign, Message, MsghubRequest
from app.msghub.schemas import ReportItem
from app.services.report import process_report, process_sent_query


@pytest.mark.parametrize("path", ["webhook", "sent_query"])
@pytest.mark.parametrize("channel,product,cost", [
    ("SMS", "LMS", 27), ("MMS", "LMS", 27), ("RCS", "RSMS", 17),
])
def test_result_updates_message_and_campaign_cost(db_session, sample_user, path, channel, product, cost):
    """실제 상품에 맞게 성공 1건만 과금하고 재전송돼도 합계가 늘지 않는다."""
    campaign = Campaign(
        created_by=sample_user.sub, caller_number="0212345678",
        message_type="short" if product == "RSMS" else "long",
        content="안내", total_count=2, pending_count=2, state="DISPATCHED",
        created_at="2026-09-18T00:00:00+00:00",
    )
    db_session.add(campaign)
    db_session.flush()
    request = MsghubRequest(
        campaign_id=campaign.id, chunk_index=0, sent_at=campaign.created_at,
    )
    db_session.add(request)
    db_session.flush()
    messages = [Message(
        campaign_id=campaign.id, msghub_request_id=request.id,
        to_number=f"0101234{index:04d}", to_number_raw=f"0101234{index:04d}",
        cli_key=f"c{campaign.id}-0-{index}", status="REG",
    ) for index in range(2)]
    db_session.add_all(messages)
    db_session.commit()

    payload = [{
        "cliKey": message.cli_key, "msgKey": f"msg-{index}", "status": "DONE",
        "resultCode": result, "ch": channel, "productCode": product,
    } for index, (message, result) in enumerate(zip(messages, ["10000", "59999"], strict=True))]

    def process():
        if path == "webhook":
            return process_report(db_session, [ReportItem.from_dict(item) for item in payload])
        return process_sent_query(db_session, payload)

    assert process() == (2, [])
    assert [(m.status, m.channel, m.product_code, m.cost) for m in messages] == [
        ("DONE", channel, product, cost), ("DONE", channel, product, 0),
    ]
    assert (campaign.ok_count, campaign.fail_count, campaign.pending_count) == (1, 1, 0)
    assert (campaign.total_cost, campaign.rcs_count, campaign.fallback_count) == (
        cost, int(channel == "RCS"), int(channel != "RCS"),
    )
    assert process() == (0, [])
    assert campaign.total_cost == cost
