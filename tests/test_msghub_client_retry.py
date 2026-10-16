"""msghub 클라이언트 — 서버의 토큰 거부 재시도, 응답 형식 방어, [재전송] 코드 분류."""
from __future__ import annotations

import httpx
import pytest

from app.msghub.client import MsghubClient
from app.msghub.codes import is_retryable
from app.msghub.schemas import (
    MsghubAuthError,
    MsghubServerError,
    RecvInfo,
    ReserveResponse,
    UploadFileResponse,
)


def _client(send_handler) -> tuple[MsghubClient, dict]:
    seen = {"auth": 0, "send_tokens": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/auth/v1/"):
            seen["auth"] += 1
            return httpx.Response(200, json={
                "code": "10000", "data": {"token": f"acc-{seen['auth']}", "refreshToken": "ref"},
            })
        seen["send_tokens"].append(request.headers["Authorization"])
        return send_handler(request, len(seen["send_tokens"]))

    client = MsghubClient("qa", "key", "pwd")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client._http = http
    client._token_mgr._http = http
    return client, seen


def _ok(_request, _n):
    return httpx.Response(200, json={"code": "10000", "data": []})


async def _send(client):
    return await client.send_sms(callback="0212345678", msg="안내", recv_list=[
        RecvInfo(cli_key="c1-0-0", phone="01011112222"),
    ])


@pytest.mark.asyncio
async def test_rejected_token_is_reissued_once_and_request_retried():
    def handler(request, n):
        if n == 1:
            return httpx.Response(401, json={"code": "20004", "message": "헤더 데이터 오류"})
        return _ok(request, n)

    client, seen = _client(handler)
    resp = await _send(client)

    assert resp.code == "10000"
    assert seen["auth"] == 2  # 첫 발급 + 거부 뒤 재발급
    assert seen["send_tokens"] == ["Bearer acc-1", "Bearer acc-2"]


@pytest.mark.asyncio
async def test_second_token_rejection_raises():
    client, seen = _client(lambda r, n: httpx.Response(401, json={"code": "20004", "message": "헤더 오류"}))
    with pytest.raises(MsghubAuthError):
        await _send(client)
    assert seen["auth"] == 2
    assert len(seen["send_tokens"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["20000", "20001", "20002", "29011", "29025"])
async def test_non_token_auth_error_is_not_reissued(code):
    """키·IP·비밀번호·권한 오류는 재발급해도 같다 — 공유 토큰을 버리지 않고 바로 올린다(M5)."""
    client, seen = _client(lambda r, n: httpx.Response(401, json={"code": code, "message": "거부"}))
    with pytest.raises(MsghubAuthError):
        await _send(client)
    assert (seen["auth"], len(seen["send_tokens"])) == (1, 1)
    assert client._token_mgr._state is not None  # 캐시 토큰 유지


def test_only_the_rejected_token_is_dropped():
    """동시 요청 중 하나가 이미 새 토큰을 받았으면 늦게 온 거부가 그 새 토큰을 버리지 않는다."""
    from app.msghub.auth import TokenManager, _TokenState

    tm = TokenManager("https://x.test", "k", "p", httpx.AsyncClient())
    tm._state = _TokenState("new-token", "ref", 1e12, 1e12)
    assert tm.invalidate_token("old-token") is False
    assert tm._state.access_token == "new-token"
    assert tm.invalidate_token("new-token") is True
    assert tm._state is None


@pytest.mark.asyncio
async def test_health_check_uses_same_retry_without_content_type():
    def handler(request, n):
        assert "content-type" not in request.headers
        if n == 1:
            return httpx.Response(401, json={"code": "20004", "message": "헤더 데이터 오류"})
        return httpx.Response(200, json={"code": "10000"})

    client, seen = _client(handler)
    assert await client.health_check() is True
    assert seen["auth"] == 2


@pytest.mark.asyncio
async def test_non_object_response_is_parse_error():
    client, _ = _client(lambda r, n: httpx.Response(200, json=["x"]))
    with pytest.raises(MsghubServerError) as info:
        await _send(client)
    assert info.value.code == "PARSE_ERROR"


@pytest.mark.asyncio
async def test_query_sent_tolerates_unexpected_data_shape():
    client, _ = _client(lambda r, n: httpx.Response(200, json={"code": "10000", "data": ["x"]}))
    assert await client.query_sent([("c1-0-0", "2026-10-16")]) == []


@pytest.mark.parametrize("data, expected", [
    ({"webReqId": "w1", "regDt": "2026"}, "w1"),
    ([{"webReqId": "w2"}], "w2"),
    ("w3", ""),
    (None, ""),
])
def test_reserve_response_data_shapes(data, expected):
    resp = ReserveResponse.from_dict({"code": "10000", "message": "ok", "data": data})
    assert resp.web_req_id == expected


def test_upload_response_data_list():
    resp = UploadFileResponse.from_dict({"code": "10000", "data": [{"fileId": "f1"}]})
    assert resp.file_id == "f1"


def test_retryable_codes_follow_current_code_table():
    assert is_retryable("21400") and is_retryable("29002") and is_retryable("41007")
    assert not is_retryable("49001")  # 현행 코드표에 49xxx 대역 없음
    assert not is_retryable("29012")
    assert not is_retryable("")
