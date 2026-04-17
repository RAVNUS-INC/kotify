"""msghub JWT 인증 모듈.

인증 흐름:
1. apiKey + apiPwd(SHA512 이중 해싱) → POST /auth/v1/{randomStr} → access + refresh token
2. access token 만료 10분 전 → PUT /auth/v1/refresh → 새 access token
3. refresh token 만료 30분 전 → 재인증 (step 1)

비밀번호 암호화:
  step1 = Base64(SHA512(raw_password))
  step2 = Base64(SHA512(step1 + "." + randomStr))
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)


class AuthError(Exception):
    """인증 실패."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


@dataclass
class _TokenState:
    access_token: str
    refresh_token: str
    access_expires_at: float   # monotonic seconds
    refresh_expires_at: float  # monotonic seconds


def _encrypt_password(raw_password: str, random_str: str) -> str:
    """msghub SHA512 이중 해싱.

    공식: Base64(SHA512( Base64(SHA512(pwd)) + "." + randomStr ))
    """
    step1 = base64.b64encode(
        hashlib.sha512(raw_password.encode("utf-8")).digest(),
    ).decode("utf-8")

    combined = step1 + "." + random_str
    step2 = base64.b64encode(
        hashlib.sha512(combined.encode("utf-8")).digest(),
    ).decode("utf-8")

    return step2


def _random_str() -> str:
    """인증용 랜덤 문자열 (최대 20자, 영숫자+하이픈+언더스코어).

    msghub API 제약: randomStr은 최대 20자, [a-zA-Z0-9-_] 허용.
    token_urlsafe(15)는 ~20자를 생성하며, 초과 시 절삭.
    """
    return secrets.token_urlsafe(15)[:20]


def _parse_response(resp: httpx.Response) -> dict:
    """HTTP 응답을 파싱하고 에러를 처리."""
    if resp.status_code >= 500:
        raise AuthError("HTTP_SERVER_ERROR", f"서버 오류: HTTP {resp.status_code}")
    try:
        body = resp.json()
    except Exception:
        raise AuthError("PARSE_ERROR", f"응답 파싱 실패 (HTTP {resp.status_code})")
    return body


_MAX_RETRIES = 2
_RETRY_DELAY = 1.0  # seconds


class TokenManager:
    """msghub JWT 토큰 관리.

    사용법:
        tm = TokenManager(base_url, api_key, api_pwd, http_client)
        token = await tm.get_token()  # 자동 발급/갱신
        headers = {"Authorization": f"Bearer {token}"}
    """

    ACCESS_LIFETIME = 3600       # 1시간
    REFRESH_LIFETIME = 90000     # 25시간
    ACCESS_RENEW_BEFORE = 600    # 만료 10분 전 갱신
    REFRESH_RENEW_BEFORE = 1800  # 만료 30분 전 재인증

    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_pwd: str,
        http: httpx.AsyncClient,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._api_pwd = api_pwd
        self._http = http
        self._state: _TokenState | None = None
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        """유효한 access token을 반환. 필요 시 자동 갱신/재발급."""
        now = time.monotonic()

        # Fast path: 토큰 유효하면 lock 없이 반환
        state = self._state
        if (
            state is not None
            and now < state.access_expires_at - self.ACCESS_RENEW_BEFORE
        ):
            return state.access_token

        # Slow path: 갱신 필요 — lock으로 stampede 방지
        async with self._lock:
            # 다른 코루틴이 이미 갱신했을 수 있음
            now = time.monotonic()
            state = self._state
            if (
                state is not None
                and now < state.access_expires_at - self.ACCESS_RENEW_BEFORE
            ):
                return state.access_token

            if state is None:
                await self._authenticate()
            elif now >= state.refresh_expires_at - self.REFRESH_RENEW_BEFORE:
                await self._authenticate()
            else:
                await self._refresh()

            return self._state.access_token  # type: ignore[union-attr]

    async def test_auth(self) -> bool:
        """인증 테스트. 성공 시 True, 실패 시 AuthError raise."""
        await self._authenticate()
        return True

    def invalidate(self) -> None:
        """토큰 상태 초기화 (자격증명 변경 시)."""
        self._state = None

    async def _authenticate(self) -> None:
        """apiKey + apiPwd로 토큰 발급. 일시 장애 시 재시도."""
        last_err: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                rand = _random_str()
                encrypted_pwd = _encrypt_password(self._api_pwd, rand)

                resp = await self._http.post(
                    f"{self._base_url}/auth/v1/{rand}",
                    json={"apiKey": self._api_key, "apiPwd": encrypted_pwd},
                    headers={"Content-Type": "application/json"},
                    timeout=15.0,
                )

                body = _parse_response(resp)
                code = body.get("code", "")
                if code != "10000":
                    raise AuthError(code, body.get("message", "인증 실패"))

                data = body["data"]
                now = time.monotonic()
                self._state = _TokenState(
                    access_token=data["token"],
                    refresh_token=data["refreshToken"],
                    access_expires_at=now + self.ACCESS_LIFETIME,
                    refresh_expires_at=now + self.REFRESH_LIFETIME,
                )
                return

            except AuthError:
                raise  # 인증 에러는 재시도하지 않음
            except (httpx.TimeoutException, httpx.ConnectError, OSError) as exc:
                last_err = exc
                log.warning(
                    "msghub 인증 시도 %d/%d 실패: %s",
                    attempt + 1,
                    _MAX_RETRIES,
                    exc,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(_RETRY_DELAY)

        raise AuthError(
            "NETWORK_ERROR",
            f"msghub 인증 서버 연결 실패 ({_MAX_RETRIES}회 시도): {last_err}",
        )

    async def _refresh(self) -> None:
        """refresh token으로 access token 갱신."""
        if self._state is None:
            await self._authenticate()
            return

        try:
            resp = await self._http.put(
                f"{self._base_url}/auth/v1/refresh",
                headers={
                    "Authorization": f"Bearer {self._state.refresh_token}",
                    "Content-Type": "application/json",
                },
                timeout=15.0,
            )

            body = _parse_response(resp)
            code = body.get("code", "")
            if code != "10000":
                log.warning(
                    "msghub 토큰 갱신 실패 [%s] %s — 전체 재인증 시도",
                    code,
                    body.get("message", ""),
                )
                await self._authenticate()
                return

            now = time.monotonic()
            self._state = _TokenState(
                access_token=body["data"]["token"],
                refresh_token=self._state.refresh_token,
                access_expires_at=now + self.ACCESS_LIFETIME,
                refresh_expires_at=self._state.refresh_expires_at,
            )

        except (httpx.TimeoutException, httpx.ConnectError, OSError) as exc:
            log.warning("msghub 토큰 갱신 네트워크 오류: %s — 전체 재인증 시도", exc)
            await self._authenticate()
