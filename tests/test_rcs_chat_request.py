"""RCS 양방향 응답 요청(MsghubClient.send_rcs_chat) 본문 — 공식 스펙 필드 고정.

msghub 공식 2.3.2 통합 RCS §2(POST /rcs/bi/v1.1) Request Body 의 필수(●) 필드만 보낸다.
moRecvDt(MO 수신 시각)는 이 요청의 필드가 아니다 — 이전 인계 문서의 "replyId+moRecvDt 필수"
기록은 스펙과 다르다(claudedocs/review/reply-id-verification.md).
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx

from app.msghub.client import MsghubClient


async def test_chat_request_sends_spec_required_fields_only(monkeypatch):
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json={
            "code": "10000", "message": "성공",
            "data": [{
                "cliKey": "c1-0-0", "msgKey": "mk", "replyId": "rid-1",
                "chatbotId": "0212345678", "code": "10000", "message": "성공",
            }],
        })

    client = MsghubClient("qa", "key", "pwd", chatbot_id="0212345678")
    await client.aclose()
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(client._token_mgr, "get_token", AsyncMock(return_value="tok"))
    try:
        resp = await client.send_rcs_chat(
            description="네 안내드릴게요", phone="01099998888", cli_key="c1-0-0", reply_id="rid-1",
        )
    finally:
        await client.aclose()

    [request] = captured
    assert request.url.path == "/rcs/bi/v1.1"
    body = json.loads(request.content)
    assert set(body) == {
        "messagebaseId", "chatbotId", "replyId", "cliKey", "telco", "phone", "body", "header",
    }
    assert (body["replyId"], body["cliKey"], body["phone"]) == ("rid-1", "c1-0-0", "01099998888")
    assert body["body"] == {"description": "네 안내드릴게요"}
    assert resp.items[0].msg_key == "mk"
