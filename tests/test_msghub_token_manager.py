"""msghub 토큰 발급·갱신 실패 처리.

- AuthError 는 MsghubAuthError 계열 — 발송 루프가 캠페인을 멈춘다(청크마다 재인증 금지).
- 응답 도중 끊김(ReadError·RemoteProtocolError)·data.token 누락도 AuthError 로 정리한다.
- 사전 갱신이 실패해도 아직 유효한 토큰은 계속 쓴다.
"""
from __future__ import annotations

import time

import httpx
import pytest

from app.msghub import auth as auth_mod
from app.msghub.auth import AuthError, TokenManager
from app.msghub.schemas import MsghubAuthError
from app.services.compose import dispatch_campaign

_BASE = "https://api.example.test"
_OK_AUTH = {"code": "10000", "data": {"token": "acc-1", "refreshToken": "ref-1"}}


def _manager(handler) -> tuple[TokenManager, list[httpx.Request]]:
    calls: list[httpx.Request] = []

    def _record(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(_record))
    return TokenManager(_BASE, "key", "pwd", http), calls


@pytest.fixture(autouse=True)
def _no_retry_delay(monkeypatch):
    async def _instant(_seconds):
        return None
    monkeypatch.setattr(auth_mod.asyncio, "sleep", _instant)


def _expire_soon(tm: TokenManager, remaining: float) -> None:
    """access token 이 remaining 초 남은 상태로 만든다 (사전 갱신 구간)."""
    assert tm._state is not None
    tm._state.access_expires_at = time.monotonic() + remaining


def test_auth_error_is_msghub_auth_error():
    exc = AuthError("20001", "인증 실패")
    assert isinstance(exc, MsghubAuthError)
    assert exc.code == "20001" and exc.status_code is None
    assert str(exc) == "[20001] 인증 실패"


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    httpx.ReadError("연결 끊김"),
    httpx.RemoteProtocolError("응답 도중 종료"),
])
async def test_authenticate_retries_transport_errors_then_raises_auth_error(error):
    def handler(request):
        raise error

    tm, calls = _manager(handler)
    with pytest.raises(AuthError) as info:
        await tm.get_token()
    assert info.value.code == "NETWORK_ERROR"
    assert len(calls) == 2  # _MAX_RETRIES


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"code": "10000", "data": {}},
    {"code": "10000", "data": None},
    {"code": "10000", "data": {"token": "acc"}},  # refreshToken 누락
    ["not", "an", "object"],
])
async def test_authenticate_missing_token_raises_auth_error(body):
    tm, _ = _manager(lambda request: httpx.Response(200, json=body))
    with pytest.raises(AuthError) as info:
        await tm.get_token()
    assert info.value.code == "PARSE_ERROR"


@pytest.mark.asyncio
async def test_failed_refresh_keeps_valid_token_and_backs_off():
    """만료 10분 전 갱신이 서버 오류로 실패해도 아직 유효한 토큰을 쓰고, 곧바로 다시 갱신하지 않는다."""
    refresh_ok = False

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json=_OK_AUTH)
        if refresh_ok:
            return httpx.Response(200, json={"code": "10000", "data": {"token": "acc-2"}})
        return httpx.Response(503)

    tm, calls = _manager(handler)
    assert await tm.get_token() == "acc-1"
    _expire_soon(tm, 300)

    assert await tm.get_token() == "acc-1"
    assert await tm.get_token() == "acc-1"
    assert [r.method for r in calls] == ["POST", "PUT"]  # 두 번째 호출은 재시도 대기 중

    tm._renew_retry_at = 0.0  # 재시도 대기가 지남
    refresh_ok = True
    assert await tm.get_token() == "acc-2"
    assert [r.method for r in calls] == ["POST", "PUT", "PUT"]


@pytest.mark.asyncio
async def test_failed_refresh_missing_token_keeps_valid_token():
    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json=_OK_AUTH)
        return httpx.Response(200, json={"code": "10000", "data": {}})

    tm, _ = _manager(handler)
    await tm.get_token()
    _expire_soon(tm, 300)
    assert await tm.get_token() == "acc-1"


@pytest.mark.asyncio
async def test_failed_renewal_raises_when_token_nearly_expired():
    posts = 0

    def handler(request):
        nonlocal posts
        if request.method == "POST":
            posts += 1
            if posts == 1:
                return httpx.Response(200, json=_OK_AUTH)
            return httpx.Response(200, json={"code": "20001", "message": "인증 실패"})
        return httpx.Response(503)

    tm, _ = _manager(handler)
    await tm.get_token()
    _expire_soon(tm, 10)  # ACCESS_MIN_REMAINING 미만 — 요청 도중 만료될 수 있다
    with pytest.raises(AuthError):
        await tm.get_token()


# ── 발송 루프 ────────────────────────────────────────────────────────────────


class _TokenFailingClient:
    """토큰 발급이 막혀 모든 발송 호출이 AuthError 로 끝나는 클라이언트."""

    def __init__(self):
        self.calls = 0

    async def send_sms(self, **kwargs):
        self.calls += 1
        raise AuthError("20001", "인증 실패")


@pytest.mark.asyncio
async def test_token_failure_stops_campaign_after_first_chunk(db_session, sample_user, sample_caller):
    """예전엔 AuthError 가 일반 예외라 청크마다 재인증을 반복했다(1만 명이면 ~1000회)."""
    client = _TokenFailingClient()
    with pytest.raises(MsghubAuthError):
        await dispatch_campaign(
            db=db_session,
            msghub_client=client,
            created_by=sample_user.sub,
            caller_number=sample_caller.number,
            content="안내",
            recipients=[f"010000000{i:02d}" for i in range(25)],  # 3청크
            message_type="SMS",
            send_channel="sms",
        )
    assert client.calls == 1
