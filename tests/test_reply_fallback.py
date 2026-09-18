"""실제 msghub 응답 파싱을 거친 답장 거부·미확정·대체 발송 회귀 테스트."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.responses import JSONResponse
from sqlalchemy import select

from app.models import Campaign, Message, MsghubRequest
from app.msghub.client import MsghubClient
from app.routes.threads import MessageCreateBody, api_post_message
from app.services.reconcile import reconcile_pending_messages
from tests.test_send_reply import _CALLER, _PHONE, _make_mo

_BI = "/rcs/bi/v1.1"
_RCS = "/rcs/v1.1"
_SMS = "/xms/sms/v1"
_QUERY = "/msg/v1/sent"


@pytest.fixture
async def provider_client(monkeypatch):
    clients = []

    async def make(handler):
        client = MsghubClient("qa", "test-key", "test-password", chatbot_id=_CALLER)
        await client.aclose()
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        monkeypatch.setattr(client._token_mgr, "get_token", AsyncMock(return_value="test-token"))
        monkeypatch.setattr("app.main.get_msghub_client", lambda: client)
        clients.append(client)
        return client

    yield make
    for client in clients:
        await client.aclose()


def _response(body, code="10000"):
    item = body if "cliKey" in body else body["recvInfoLst"][0]
    return httpx.Response(200, json={
        "code": "10000", "message": "OK", "data": [{
            "cliKey": item["cliKey"], "msgKey": f"mk-{item['cliKey']}",
            "phone": item.get("phone", ""), "code": code,
            "message": "성공" if code == "10000" else "명시적 수신자 거부",
        }],
    })


async def _post(db, user, channel="rcs"):
    return await api_post_message(
        f"{_CALLER}:{_PHONE}", MessageCreateBody(text="안내드립니다", sendChannel=channel),
        user=user, db=db,
    )


def _only_attempt(db):
    return (
        db.execute(select(Campaign)).scalar_one(),
        db.execute(select(Message)).scalar_one(),
        db.execute(select(MsghubRequest)).scalar_one(),
    )


@pytest.mark.parametrize("bi_code, expected_paths", [
    ("10000", [_BI]),
    ("51004", [_BI, _RCS]),
])
async def test_chat_item_rejection_falls_back_once_without_duplicate_rows(
    db_session, sample_user, sample_caller, provider_client, bi_code, expected_paths,
):
    _make_mo(db_session, reply_id="test-reply-id")
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append((request.url.path, body))
        return _response(body, bi_code if request.url.path == _BI else "10000")

    await provider_client(handler)
    result = await _post(db_session, sample_user)

    assert isinstance(result, dict) and "message" in result["data"]
    assert [path for path, _ in calls] == expected_paths
    campaign, msg, req = _only_attempt(db_session)
    assert (campaign.state, campaign.fail_count, campaign.pending_count) == ("DISPATCHED", 0, 1)
    assert (msg.status, msg.result_code) == ("REG", "10000")
    final_body = calls[-1][1]
    final_key = final_body.get("cliKey") or final_body["recvInfoLst"][0]["cliKey"]
    assert msg.cli_key == final_key
    if len(calls) == 2:
        assert calls[0][1]["cliKey"] != final_key
        assert campaign.rcs_messagebase_id == "RPSSAXX001"


@pytest.mark.parametrize("direct_sms", [False, True], ids=["oneway-item", "direct-sms-item"])
async def test_final_rejection_returns_error_and_keeps_one_failed_message(
    db_session, sample_user, sample_caller, provider_client, direct_sms,
):
    _make_mo(db_session, reply_id="test-reply-id")
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(request.url.path)
        if request.url.path == _BI:
            return _response(body, "51004")
        if request.url.path == _RCS and direct_sms:
            return httpx.Response(400, json={"code": "29003", "message": "RCS 요청 거부"})
        return _response(body, "31101")

    await provider_client(handler)
    result = await _post(db_session, sample_user)

    assert isinstance(result, JSONResponse) and result.status_code == 502
    error = json.loads(result.body)["error"]
    assert error["code"] == "send_failed"
    assert calls == ([_BI, _RCS, _SMS] if direct_sms else [_BI, _RCS])
    campaign, msg, req = _only_attempt(db_session)
    assert error["fields"]["campaignId"] == str(campaign.id)
    assert (campaign.state, campaign.fail_count, campaign.pending_count) == ("FAILED", 1, 0)
    assert (msg.status, msg.result_code) == ("FAILED", "31101")
    assert msg.cli_key.endswith("-fb") == direct_sms


@pytest.mark.parametrize("code", ["29003", "51004"])
async def test_http_200_top_level_chat_rejection_is_explicit(
    db_session, sample_user, sample_caller, provider_client, code,
):
    _make_mo(db_session, reply_id="test-reply-id")
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == _BI:
            return httpx.Response(200, json={"code": code, "message": "명시적 요청 거부"})
        return _response(json.loads(request.content))

    await provider_client(handler)
    result = await _post(db_session, sample_user)
    assert isinstance(result, dict) and "message" in result["data"]
    assert calls == [_BI, _RCS]
    campaign, msg, req = _only_attempt(db_session)
    assert (campaign.rcs_messagebase_id, campaign.pending_count) == ("RPSSAXX001", 1)
    assert (msg.status, msg.result_code) == ("REG", "10000")


@pytest.mark.parametrize("failure", ["timeout", "server", "parse", "missing-item-code", "wrong-key"])
async def test_uncertain_chat_is_not_retried_and_its_actual_key_is_reconciled(
    db_session, sample_user, sample_caller, provider_client, failure,
):
    _make_mo(db_session, reply_id="test-reply-id")
    calls, sent_keys = [], []

    def handler(request):
        body = json.loads(request.content)
        calls.append(request.url.path)
        if request.url.path == _QUERY:
            assert [item["cliKey"] for item in body["cliKeyLst"]] == sent_keys
            return httpx.Response(200, json={"code": "10000", "data": {"cliKeyLst": [{
                "cliKey": sent_keys[0], "status": "DONE", "resultCode": "10000",
                "ch": "RCS", "productCode": "CHAT",
            }]}})
        assert request.url.path == _BI, "미확정 양방향 요청을 즉시 중복 발송했습니다"
        sent_keys.append(body["cliKey"])
        if failure == "timeout":
            raise httpx.ReadTimeout("접수 응답 유실", request=request)
        if failure == "server":
            return httpx.Response(500, text="upstream error")
        if failure == "missing-item-code":
            return _response(body, "")
        if failure == "wrong-key":
            return _response({**body, "cliKey": "unexpected-key"}, "51004")
        return httpx.Response(200, text="unparseable response")

    client = await provider_client(handler)
    result = await _post(db_session, sample_user)

    assert isinstance(result, JSONResponse) and result.status_code == 502
    error = json.loads(result.body)["error"]
    assert error["code"] == "send_status_unknown"
    assert "재발송 전에" in error["message"]
    campaign, msg, req = _only_attempt(db_session)
    assert (msg.cli_key, msg.status, msg.result_code) == (sent_keys[0], "FAILED", None)
    assert req.response_code is None and req.error_body
    assert calls == [_BI]

    assert await reconcile_pending_messages(db_session, client, older_than_minutes=0) == 1
    db_session.refresh(campaign)
    db_session.refresh(msg)
    assert (msg.cli_key, msg.status, msg.cost) == (sent_keys[0], "DONE", 8)
    assert (campaign.state, campaign.ok_count, campaign.fail_count) == ("COMPLETED", 1, 0)
    assert calls == [_BI, _QUERY]


async def test_rejected_chat_then_uncertain_oneway_preserves_only_latest_attempt(
    db_session, sample_user, sample_caller, provider_client,
):
    _make_mo(db_session, reply_id="test-reply-id")
    calls, keys = [], []

    def handler(request):
        body = json.loads(request.content)
        calls.append(request.url.path)
        if request.url.path == _BI:
            return _response(body, "51004")
        assert request.url.path == _RCS
        keys.append(body["recvInfoLst"][0]["cliKey"])
        raise httpx.ReadTimeout("단방향 접수 응답 유실", request=request)

    await provider_client(handler)
    result = await _post(db_session, sample_user)

    assert isinstance(result, JSONResponse) and result.status_code == 502
    assert json.loads(result.body)["error"]["code"] == "send_status_unknown"
    campaign, msg, req = _only_attempt(db_session)
    assert calls == [_BI, _RCS]
    assert (msg.cli_key, msg.status, msg.result_code) == (keys[0], "FAILED", None)
    assert campaign.rcs_messagebase_id == "RPSSAXX001"


async def test_direct_sms_rejection_also_returns_error(
    db_session, sample_user, sample_caller, provider_client,
):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return _response(json.loads(request.content), "31101")

    await provider_client(handler)
    result = await _post(db_session, sample_user, channel="sms")
    assert isinstance(result, JSONResponse) and result.status_code == 502
    assert json.loads(result.body)["error"]["code"] == "send_failed"
    assert calls == [_SMS]
