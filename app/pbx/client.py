"""VitalPBX API v2 클라이언트 — CDR 조회, 가상 팩스 발송·로그 조회, 녹음 파일 스트리밍.

설계 원칙:
- **사내 직결만**: ``pbx.api_base_url``(기본 ``https://10.0.5.10:4430``)로만 요청한다.
  PBX 가 돌려주는 ``recording_url`` 의 공인 호스트는 버리고 경로만 쓴다.
- **로그에 개인정보 없음**: 전화번호·녹음 경로·응답 본문·키를 로그와 예외 메시지에
  넣지 않는다. 오류는 엔드포인트 이름과 HTTP 상태·오류 코드만 남긴다.
- **미설정 = 무동작**: 앱 키나 테넌트가 없으면 ``load_pbx_config`` 가 None 을 돌려준다.

설정 키 (SettingsStore):
- ``pbx.api_base_url``       : API 주소 (plain)
- ``pbx.tenant``             : 테넌트 헤더 값 (plain)
- ``pbx.app_key``            : 애플리케이션 키 (secret)
- ``pbx.tls_verify``         : "true"/"false" — 자체 서명 인증서라 기본 false (plain)
- ``pbx.fax_device_id``      : 가상 팩스 장치 ID (plain)
- ``pbx.fax_fetch_base_url`` : PBX 가 팩스 PDF 를 내려받을 kotify 사내 주소 (plain)
"""
from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.security.settings_store import SettingsStore

log = logging.getLogger(__name__)

DEFAULT_API_BASE_URL = "https://10.0.5.10:4430"

_TIMEOUT = httpx.Timeout(10.0, connect=3.0)
# 녹음 파일은 수 MB 라 읽기 시간을 넉넉히 둔다.
_STREAM_TIMEOUT = httpx.Timeout(30.0, connect=3.0)


@dataclass(frozen=True)
class PbxConfig:
    """PBX 접속 설정 스냅샷."""

    base_url: str
    tenant: str
    app_key: str
    tls_verify: bool
    fax_device_id: str
    fax_fetch_base_url: str


class PbxNotConfigured(Exception):
    """PBX 앱 키·테넌트가 설정되지 않음."""


class PbxError(Exception):
    """PBX 호출 실패.

    Attributes:
        code: ``timeout`` | ``network`` | ``http_<status>`` | ``rejected`` | ``bad_response``.
        uncertain: 요청이 PBX 에 닿았는지 알 수 없는 실패(시간 초과·연결 끊김·5xx).
            팩스 발송에서 이 값이 True 면 재전송하지 않는다(이중 발송 방지).
    """

    def __init__(self, code: str, *, uncertain: bool = False, status_code: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.uncertain = uncertain
        self.status_code = status_code


def load_pbx_config(db: Session) -> PbxConfig | None:
    """설정에서 PBX 접속 정보를 읽는다. 앱 키나 테넌트가 없으면 None."""
    store = SettingsStore(db)
    app_key = (store.get("pbx.app_key", "") or "").strip()
    tenant = (store.get("pbx.tenant", "") or "").strip()
    if not app_key or not tenant:
        return None
    base_url = (store.get("pbx.api_base_url", "") or "").strip() or DEFAULT_API_BASE_URL
    return PbxConfig(
        base_url=base_url.rstrip("/"),
        tenant=tenant,
        app_key=app_key,
        tls_verify=(store.get("pbx.tls_verify", "false") or "false").strip().lower() == "true",
        fax_device_id=(store.get("pbx.fax_device_id", "") or "").strip(),
        fax_fetch_base_url=(store.get("pbx.fax_fetch_base_url", "") or "").strip().rstrip("/"),
    )


def require_pbx_config(db: Session) -> PbxConfig:
    """설정이 없으면 PbxNotConfigured."""
    config = load_pbx_config(db)
    if config is None:
        raise PbxNotConfigured()
    return config


class PbxClient:
    """요청마다 짧게 쓰는 httpx 클라이언트 래퍼. 호출량이 적어 연결을 유지하지 않는다."""

    def __init__(self, config: PbxConfig) -> None:
        self._config = config

    def _client(
        self, timeout: httpx.Timeout = _TIMEOUT, *, with_key: bool = True
    ) -> httpx.AsyncClient:
        headers = (
            {"app-key": self._config.app_key, "tenant": self._config.tenant} if with_key else {}
        )
        return httpx.AsyncClient(
            base_url=self._config.base_url,
            headers=headers,
            timeout=timeout,
            verify=self._config.tls_verify,
            follow_redirects=False,
        )

    @staticmethod
    def _unwrap(resp: httpx.Response, endpoint: str) -> Any:
        """``{"status":"success","data":...}`` 에서 data 를 꺼낸다."""
        if resp.status_code >= 500:
            log.warning("PBX %s 실패: HTTP %s", endpoint, resp.status_code)
            raise PbxError(f"http_{resp.status_code}", uncertain=True, status_code=resp.status_code)
        if resp.status_code >= 400:
            log.warning("PBX %s 거부: HTTP %s", endpoint, resp.status_code)
            raise PbxError(f"http_{resp.status_code}", status_code=resp.status_code)
        try:
            body = resp.json()
        except ValueError:
            log.warning("PBX %s 응답 파싱 실패", endpoint)
            raise PbxError("bad_response", uncertain=True) from None
        if not isinstance(body, dict):
            log.warning("PBX %s 응답 형식 오류", endpoint)
            raise PbxError("bad_response", uncertain=True)
        if body.get("status") != "success":
            log.warning("PBX %s 거부: status=%s", endpoint, str(body.get("status"))[:20])
            raise PbxError("rejected")
        return body.get("data")

    async def _request(self, method: str, path: str, endpoint: str, **kwargs: Any) -> Any:
        try:
            async with self._client() as client:
                resp = await client.request(method, path, **kwargs)
        except httpx.TimeoutException:
            log.warning("PBX %s 시간 초과", endpoint)
            raise PbxError("timeout", uncertain=True) from None
        except httpx.HTTPError as exc:
            log.warning("PBX %s 연결 실패: %s", endpoint, type(exc).__name__)
            raise PbxError("network", uncertain=True) from None
        return self._unwrap(resp, endpoint)

    # ── CDR ────────────────────────────────────────────────────────────────

    async def list_cdr(self, params: dict[str, str]) -> list[dict]:
        """``GET /api/v2/cdr`` — ``data.result`` 배열을 반환한다."""
        data = await self._request("GET", "/api/v2/cdr", "cdr", params=params)
        if isinstance(data, dict):
            result = data.get("result")
        else:
            result = data
        if not isinstance(result, list):
            raise PbxError("bad_response")
        return [row for row in result if isinstance(row, dict)]

    # ── 가상 팩스 ─────────────────────────────────────────────────────────

    async def get_fax_device(self, device_id: str) -> dict:
        """``GET /api/v2/virtual_faxes/{id}`` — 장치 정보(호출자는 secret 을 버려야 함)."""
        data = await self._request("GET", f"/api/v2/virtual_faxes/{device_id}", "virtual_faxes")
        if not isinstance(data, dict):
            raise PbxError("bad_response")
        return data

    async def send_fax(
        self,
        device_id: str,
        *,
        url: str,
        recipient: str,
        resolution: str,
        retries: int,
        retry_time: int,
    ) -> dict:
        """``POST /api/v2/virtual_faxes/{id}/send`` (form-data).

        PBX 가 이 요청 안에서 ``url`` 의 PDF 를 내려받는다. 응답 ``data.file`` 이
        PBX 쪽 임시 파일 경로다.
        """
        form = {
            "url": url,
            "recipients": recipient,
            "resolution": resolution,
            "retries": str(retries),
            "retry_time": str(retry_time),
        }
        # httpx 는 files 가 있어야 multipart 로 보낸다 — 빈 파일 없이 multipart 를
        # 강제하려고 각 필드를 (None, 값) 튜플로 넘긴다.
        multipart = {k: (None, v) for k, v in form.items()}
        data = await self._request(
            "POST", f"/api/v2/virtual_faxes/{device_id}/send", "virtual_faxes.send", files=multipart,
        )
        if not isinstance(data, dict):
            raise PbxError("bad_response", uncertain=True)
        return data

    async def get_fax_log(self, log_id: int) -> dict | None:
        """``GET /api/v2/virtual_faxes/log/{id}`` — 없으면 None."""
        try:
            data = await self._request(
                "GET", f"/api/v2/virtual_faxes/log/{log_id}", "virtual_faxes.log",
            )
        except PbxError as exc:
            if exc.code in ("http_404", "rejected"):
                return None
            raise
        if not data:
            return None
        if not isinstance(data, dict):
            raise PbxError("bad_response")
        return data

    # ── 녹음 ───────────────────────────────────────────────────────────────

    async def open_recording(
        self, path: str, range_header: str | None
    ) -> tuple[httpx.Response, AsyncIterator[bytes]]:
        """녹음 파일을 스트리밍으로 연다.

        Returns:
            (응답 헤더용 Response, 본문 바이트 이터레이터). 이터레이터가 끝나거나
            닫히면 연결도 닫힌다.

        Raises:
            PbxError: 연결 실패 또는 200/206 이 아닌 응답.
        """
        # 녹음 경로는 앱 키를 요구하지 않는다 — 필요 없는 곳에 키를 보내지 않는다.
        client = self._client(_STREAM_TIMEOUT, with_key=False)
        headers = {"Range": range_header} if range_header else {}
        try:
            request = client.build_request("GET", path, headers=headers)
            resp = await client.send(request, stream=True)
        except httpx.TimeoutException:
            await client.aclose()
            log.warning("PBX 녹음 시간 초과")
            raise PbxError("timeout", uncertain=True) from None
        except httpx.HTTPError as exc:
            await client.aclose()
            log.warning("PBX 녹음 연결 실패: %s", type(exc).__name__)
            raise PbxError("network", uncertain=True) from None

        if resp.status_code not in (200, 206):
            status = resp.status_code
            await resp.aclose()
            await client.aclose()
            log.warning("PBX 녹음 응답 HTTP %s", status)
            raise PbxError(f"http_{status}", status_code=status)

        async def _body() -> AsyncIterator[bytes]:
            try:
                async for chunk in resp.aiter_bytes():
                    yield chunk
            finally:
                await resp.aclose()
                await client.aclose()

        return resp, _body()
