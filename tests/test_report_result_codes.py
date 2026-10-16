"""리포트 결과 코드 분류 — 30124 성공, 전달됐을 수 있는 실패 코드는 '결과 불확실'.

- 30124(코드표 "성공")는 전달 성공으로 집계하고 과금한다.
- 41007·54004·55806·55820(단말 전달 가능)·32114·55821·56003(성공 불확실)은 실패로 확정하되
  양방향 답장의 대체 SMS 를 보내지 않는다(이중 수신 방지). 수신자·말풍선에는 '불확실' 로 보인다.
"""
from __future__ import annotations

import pytest

from app.models import Campaign
from app.msghub.codes import UNCERTAIN_CODES, is_delivered, is_uncertain
from app.routes.campaigns import _message_to_recipient
from app.services.chat import delivery_status, get_thread
from tests.test_sms_fallback import (
    _PHONE,
    _make_chat_reply,
    _message,
    _post_report,
    _setup_token,
    _SmsClient,
)


def _chat_report(cli_key, code, desc="결과"):
    return {
        "msgKey": "mk-chat", "cliKey": cli_key, "ch": "RCS", "resultCode": code,
        "resultCodeDesc": desc, "productCode": "CHAT", "phone": _PHONE,
        "rptDt": "2026-09-15T10:00:01",
    }


def test_code_sets():
    assert is_delivered("10000") and is_delivered("30124")
    assert not is_delivered("32114") and not is_delivered(None)
    assert UNCERTAIN_CODES == {"41007", "54004", "55806", "55820", "32114", "55821", "56003"}
    assert not is_uncertain("51004")


def test_30124_counts_as_delivered_and_billed(db_session, sample_user, monkeypatch):
    _setup_token(db_session)
    client = _SmsClient()
    monkeypatch.setattr("app.main.get_msghub_client", lambda: client)
    campaign, cli_key = _make_chat_reply(db_session)

    _post_report(db_session, _chat_report(cli_key, "30124", "성공"))

    msg = _message(db_session, campaign.id)
    assert (msg.status, msg.result_code, msg.cost) == ("DONE", "30124", 8)
    assert client.cli_keys == []  # 실패가 아니라 대체 SMS 없음
    campaign = db_session.get(Campaign, campaign.id)
    assert (campaign.state, campaign.ok_count, campaign.fail_count, campaign.total_cost) == ("COMPLETED", 1, 0, 8)
    assert _message_to_recipient(msg)["status"] == "delivered"
    assert delivery_status(msg.status, msg.result_code, msg.cli_key) == "sent"


@pytest.mark.parametrize("code", sorted(UNCERTAIN_CODES))
def test_uncertain_code_fails_without_sms_fallback(db_session, sample_user, monkeypatch, code):
    _setup_token(db_session)
    client = _SmsClient()
    monkeypatch.setattr("app.main.get_msghub_client", lambda: client)
    campaign, cli_key = _make_chat_reply(db_session)

    resp = _post_report(db_session, _chat_report(cli_key, code, "전송 성공 불확실"))

    assert resp.status_code == 200
    assert client.cli_keys == []  # 이중 수신 방지 — 대체 SMS 를 보내지 않는다
    msg = _message(db_session, campaign.id)
    assert (msg.status, msg.result_code, msg.cost, msg.cli_key) == ("DONE", code, 0, cli_key)
    campaign = db_session.get(Campaign, campaign.id)
    assert (campaign.state, campaign.ok_count, campaign.fail_count) == ("FAILED", 0, 1)

    recipient = _message_to_recipient(msg)
    assert recipient["status"] == "uncertain"
    assert recipient["failureReason"] == "전송 성공 불확실"
    [bubble] = get_thread(db_session, campaign.caller_number, _PHONE)
    assert bubble.delivery == "uncertain"


def test_definite_failure_still_falls_back(db_session, sample_user, monkeypatch):
    _setup_token(db_session)
    client = _SmsClient()
    monkeypatch.setattr("app.main.get_msghub_client", lambda: client)
    campaign, cli_key = _make_chat_reply(db_session)

    _post_report(db_session, _chat_report(cli_key, "51004", "RCS 미지원 단말"))

    assert client.cli_keys == [f"{cli_key}-fb"]
    assert _message(db_session, campaign.id).status == "FB_PENDING"
