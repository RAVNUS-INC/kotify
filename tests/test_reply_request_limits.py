"""대화방 답장 — 웹 요청 안에서 기다리지 않고, 같은 답장을 두 번 보내지 않는다(M3), 인증 실패 집계(M4)."""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from app.models import Campaign, Message
from app.msghub.schemas import MsghubAuthError
from app.routes.threads import MessageCreateBody, api_post_message
from app.services.compose import dispatch_campaign
from tests.test_reply_fallback import _SMS, _response
from tests.test_reply_fallback import provider_client as _provider_client_fixture
from tests.test_send_reply import _CALLER, _PHONE

provider_client = _provider_client_fixture


async def _post(db, user, key=None):
    return await api_post_message(
        f"{_CALLER}:{_PHONE}", MessageCreateBody(text="안내드립니다", sendChannel="sms"),
        user=user, db=db, idempotency_key=key,
    )


async def test_rate_limited_reply_fails_without_waiting(
    db_session, sample_user, sample_caller, provider_client, monkeypatch,
):
    sleeps = []

    async def _sleep(seconds):
        sleeps.append(seconds)
    monkeypatch.setattr("app.services.compose.asyncio.sleep", _sleep)
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(400, json={"code": "29002", "message": "CPS 초과"})

    await provider_client(handler)
    result = await _post(db_session, sample_user)

    assert isinstance(result, JSONResponse) and result.status_code == 502
    assert json.loads(result.body)["error"]["code"] == "send_failed"
    assert (calls, sleeps) == ([_SMS], [])  # 다시 보내지도, 기다리지도 않는다


async def test_same_idempotency_key_sends_once(db_session, sample_user, sample_caller, provider_client):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return _response(json.loads(request.content))

    await provider_client(handler)
    first = await _post(db_session, sample_user, key="reply-key-1")
    again = await _post(db_session, sample_user, key="reply-key-1")

    assert calls == [_SMS]
    assert first["data"]["message"]["id"] == again["data"]["message"]["id"]
    assert db_session.scalar(select(func.count()).select_from(Campaign)) == 1
    await _post(db_session, sample_user, key="reply-key-2")
    assert calls == [_SMS, _SMS]  # 새 키는 새 답장


async def test_retry_of_failed_reply_with_same_key_reports_failure_again(
    db_session, sample_user, sample_caller, provider_client,
):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(400, json={"code": "29003", "message": "거부"})

    await provider_client(handler)
    assert (await _post(db_session, sample_user, key="k")).status_code == 502
    assert (await _post(db_session, sample_user, key="k")).status_code == 502
    assert calls == [_SMS]


async def test_token_failure_reply_is_failed_bubble_not_500(
    db_session, sample_user, sample_caller, provider_client, monkeypatch,
):
    from app.msghub.auth import AuthError

    client = await provider_client(lambda r: _response(json.loads(r.content)))

    async def _fail():
        raise AuthError("20002", "패스워드 불일치")
    monkeypatch.setattr(client._token_mgr, "get_token", _fail)

    result = await _post(db_session, sample_user)
    assert isinstance(result, JSONResponse) and result.status_code == 502
    assert json.loads(result.body)["error"]["code"] == "send_failed"
    campaign = db_session.scalar(select(Campaign))
    assert (campaign.state, campaign.fail_count, campaign.pending_count) == ("FAILED", 1, 0)


class _AuthFailsOnSecondChunk:
    def __init__(self):
        self.calls = 0

    async def send_sms(self, *, callback, msg, recv_list, resv_yn=None, resv_req_dt=None):
        from app.msghub.schemas import SendResponse, SendResultItem

        self.calls += 1
        if self.calls == 2:
            raise MsghubAuthError("[20004] 헤더 데이터 오류", code="20004", status_code=401)
        return SendResponse(code="10000", message="OK", items=[
            SendResultItem(cli_key=r.cli_key, msg_key="mk", phone=r.phone, code="10000", message="성공")
            for r in recv_list
        ])


@pytest.mark.asyncio
async def test_auth_error_settles_campaign_before_raising(db_session, sample_user, sample_caller):
    """멈춘 뒤 남은 청크도 거부 실패로 기록해 state·카운트를 확정한다 — 예전엔 DISPATCHING·pending=전체."""
    client = _AuthFailsOnSecondChunk()
    with pytest.raises(MsghubAuthError) as info:
        await dispatch_campaign(
            db=db_session, msghub_client=client, created_by=sample_user.sub,
            caller_number=sample_caller.number, content="안내",
            recipients=[f"010000000{i:02d}" for i in range(25)], message_type="SMS", send_channel="sms",
        )
    campaign = db_session.get(Campaign, info.value.campaign_id)
    assert client.calls == 2
    assert (campaign.state, campaign.fail_count, campaign.pending_count) == ("PARTIAL_FAILED", 15, 10)
    failed = db_session.execute(
        select(Message.result_code, func.count()).where(
            Message.campaign_id == campaign.id, Message.status == "FAILED"
        ).group_by(Message.result_code)
    ).all()
    assert failed == [("20004", 15)]
