"""NCP SENS SMS v2 API 클라이언트.

모든 HTTP 호출은 httpx.AsyncClient로 수행한다.
signature.py의 make_headers()가 NotImplementedError를 raise하면
자연스럽게 전파된다 (사용자가 직접 작성할 때까지 의도된 동작).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import quote

import httpx

from app.ncp.signature import make_headers

_BASE_URL = "https://sens.apigw.ntruss.com"
_SEND_PATH = "/sms/v2/services/{service_id}/messages"
_LIST_PATH = "/sms/v2/services/{service_id}/messages"
_RESERVE_STATUS_PATH = (
    "/sms/v2/services/{service_id}/reservations/{reserve_id}/reserve-status"
)
_RESERVE_CANCEL_PATH = "/sms/v2/services/{service_id}/reservations/{reserve_id}"

# 단일 호출당 최대 수신자 수 (NCP 제약)
_CHUNK_SIZE = 100

# HTTP 요청 타임아웃 (초)
_TIMEOUT = 30.0


# ── 예외 ─────────────────────────────────────────────────────────────────────


class NCPError(Exception):
    """NCP API 관련 기본 예외."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class NCPAuthError(NCPError):
    """401 — 시그니처/timestamp 오류. 관리자 점검 필요."""


class NCPBadRequest(NCPError):
    """400 — 요청 본문/스키마 오류. 재시도 불가."""


class NCPForbidden(NCPError):
    """403 — 권한 없음. serviceId 점검."""


class NCPRateLimited(NCPError):
    """429 — Rate limit 초과."""


class NCPServerError(NCPError):
    """5xx — NCP 서버 일시 오류."""


# ── 응답 모델 ────────────────────────────────────────────────────────────────


@dataclass
class SendResponse:
    """POST /messages 성공 응답."""

    request_id: str
    request_time: str
    status_code: str
    status_name: str


@dataclass
class MessageItem:
    """수신자 단위 결과 항목 (list API 응답 내 messages[] 요소)."""

    message_id: str
    to: str
    status: str
    status_name: str | None = None
    status_code: str | None = None
    status_message: str | None = None
    telco_code: str | None = None
    complete_time: str | None = None


@dataclass
class ListResponse:
    """GET /messages 성공 응답."""

    request_id: str
    status_code: str
    status_name: str
    messages: list[MessageItem] = field(default_factory=list)


@dataclass
class ReserveStatusResponse:
    """GET /reservations/{reserveId}/reserve-status 응답.

    reserve_status 가능 값 (NCP SENS v2):
        READY | PROCESSING | CANCELED | FAIL | DONE | STALE | SKIP
    """

    reserve_id: str
    reserve_timezone: str
    reserve_time: str        # "YYYY-MM-DD HH:mm" 로컬
    reserve_status: str


# ── 클라이언트 ───────────────────────────────────────────────────────────────


class NCPClient:
    """NCP SENS SMS v2 API 클라이언트.

    httpx.AsyncClient를 인스턴스 수준에서 재사용한다.
    lifespan에서 aclose()를 호출해야 한다.

    Args:
        access_key: NCP IAM Access Key.
        secret_key: NCP IAM Secret Key.
        service_id: SENS 서비스 ID.
    """

    def __init__(self, access_key: str, secret_key: str, service_id: str) -> None:
        self._access_key = access_key
        self._secret_key = secret_key
        self._service_id = service_id
        self._client = httpx.AsyncClient(base_url=_BASE_URL, timeout=_TIMEOUT)

    async def aclose(self) -> None:
        """HTTP 클라이언트 연결을 닫는다."""
        await self._client.aclose()

    # ── 내부 헬퍼 ────────────────────────────────────────────────────────────

    def _send_path(self) -> str:
        return _SEND_PATH.format(service_id=self._service_id)

    def _list_path(self, request_id: str) -> str:
        # URL 인코딩으로 특수문자 안전 처리 (#26)
        safe_id = quote(request_id, safe="")
        return f"{_LIST_PATH.format(service_id=self._service_id)}?requestId={safe_id}"

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        """HTTP 상태 코드에 따라 적절한 예외를 raise한다."""
        code = response.status_code
        if code in (200, 202):
            return
        text = response.text
        if code == 400:
            raise NCPBadRequest(f"NCP 400 Bad Request: {text}", status_code=code)
        if code == 401:
            raise NCPAuthError(f"NCP 401 Unauthorized (시그니처/시간 오류): {text}", status_code=code)
        if code == 403:
            raise NCPForbidden(f"NCP 403 Forbidden (serviceId 점검 필요): {text}", status_code=code)
        if code == 404:
            raise NCPError(f"NCP 404 Not Found: {text}", status_code=code)
        if code == 429:
            raise NCPRateLimited(f"NCP 429 Rate Limited: {text}", status_code=code)
        if code >= 500:
            raise NCPServerError(f"NCP {code} Server Error: {text}", status_code=code)
        raise NCPError(f"NCP 예상치 못한 응답 {code}: {text}", status_code=code)

    # ── 공개 API ─────────────────────────────────────────────────────────────

    async def send_sms(
        self,
        from_number: str,
        content: str,
        to_numbers: list[str],
        message_type: Literal["SMS", "LMS"] = "SMS",
        subject: str | None = None,
        reserve_time: str | None = None,
        reserve_time_zone: str | None = None,
    ) -> SendResponse:
        """SMS/LMS를 단일 청크(최대 100건)로 발송한다.

        이슈 #2: 청크 분할은 dispatch_campaign이 전담한다.
        100건 초과 시 ValueError를 raise한다.

        예약 발송: reserve_time 이 주어지면 NCP는 즉시 발송하지 않고 예약 큐에
        등록한다. 응답의 request_id는 이후 reserveId로 사용된다.

        Args:
            from_number: 발신번호 (숫자만, 예: ``"0212345678"``).
            content: 메시지 본문.
            to_numbers: 수신번호 목록 (정규화된 숫자만, 최대 100건).
            message_type: ``"SMS"`` 또는 ``"LMS"``.
            subject: LMS 제목 (message_type=LMS 시 권장).
            reserve_time: 예약 시각 ``"YYYY-MM-DD HH:mm"`` (로컬).
                None이면 즉시 발송.
            reserve_time_zone: 예약 타임존, 예 ``"Asia/Seoul"``.
                reserve_time 지정 시 필수.

        Returns:
            SendResponse.

        Raises:
            ValueError: 100건 초과 또는 reserve 파라미터 불일치.
            NotImplementedError: signature.py가 아직 구현되지 않은 경우.
            NCPAuthError: 인증 실패.
            NCPBadRequest: 요청 오류.
            NCPRateLimited: Rate limit 초과.
            NCPServerError: NCP 서버 오류.
        """
        if len(to_numbers) > _CHUNK_SIZE:
            raise ValueError(
                f"send_sms는 최대 {_CHUNK_SIZE}건을 처리합니다. "
                f"청크 분할은 dispatch_campaign이 전담합니다. "
                f"요청 건수: {len(to_numbers)}"
            )
        if (reserve_time is None) != (reserve_time_zone is None):
            raise ValueError(
                "reserve_time 과 reserve_time_zone 은 함께 지정하거나 함께 None이어야 합니다."
            )

        path = self._send_path()

        body: dict = {
            "type": message_type,
            "contentType": "COMM",
            "countryCode": "82",
            "from": from_number,
            "content": content,
            "messages": [{"to": num} for num in to_numbers],
        }
        if subject and message_type == "LMS":
            body["subject"] = subject
        if reserve_time is not None:
            body["reserveTime"] = reserve_time
            body["reserveTimeZone"] = reserve_time_zone

        headers = make_headers("POST", path, self._access_key, self._secret_key)

        response = await self._client.post(path, json=body, headers=headers)
        self._raise_for_status(response)

        data = response.json()
        return SendResponse(
            request_id=data["requestId"],
            request_time=data["requestTime"],
            status_code=data["statusCode"],
            status_name=data["statusName"],
        )

    async def list_by_request_id(self, request_id: str) -> ListResponse:
        """requestId로 메시지 결과 목록을 조회한다.

        발송 직후 1회 호출하여 messageId를 수집하거나,
        폴링 워커에서 상태를 갱신할 때 사용한다.

        Args:
            request_id: NCP requestId (발송 응답에서 수신).

        Returns:
            ListResponse (messages 목록 포함).

        Raises:
            NotImplementedError: signature.py가 아직 구현되지 않은 경우.
            NCPAuthError: 인증 실패.
            NCPError: 기타 API 오류.
        """
        path = self._list_path(request_id)
        # 서명용 URI는 querystring 포함 전체 경로
        uri = path

        headers = make_headers("GET", uri, self._access_key, self._secret_key)

        response = await self._client.get(path, headers=headers)
        self._raise_for_status(response)

        data = response.json()

        raw_messages = data.get("messages") or []
        items = [
            MessageItem(
                message_id=m["messageId"],
                to=m["to"],
                status=m.get("status", "UNKNOWN"),
                status_name=m.get("statusName"),
                status_code=m.get("statusCode"),
                status_message=m.get("statusMessage"),
                telco_code=m.get("telcoCode"),
                complete_time=m.get("completeTime"),
            )
            for m in raw_messages
        ]

        return ListResponse(
            request_id=data.get("requestId", request_id),
            status_code=data.get("statusCode", ""),
            status_name=data.get("statusName", ""),
            messages=items,
        )

    async def get_reserve_status(self, reserve_id: str) -> ReserveStatusResponse:
        """예약 발송의 현재 상태를 조회한다.

        Args:
            reserve_id: send_sms(reserve_time=...) 호출의 request_id.

        Returns:
            ReserveStatusResponse.

        Raises:
            NCPAuthError / NCPError: API 오류.
        """
        safe_id = quote(reserve_id, safe="")
        path = _RESERVE_STATUS_PATH.format(
            service_id=self._service_id, reserve_id=safe_id
        )
        headers = make_headers("GET", path, self._access_key, self._secret_key)

        response = await self._client.get(path, headers=headers)
        self._raise_for_status(response)

        data = response.json()
        return ReserveStatusResponse(
            reserve_id=data.get("reserveId", reserve_id),
            reserve_timezone=data.get("reserveTimeZone", ""),
            reserve_time=data.get("reserveTime", ""),
            reserve_status=data.get("reserveStatus", ""),
        )

    async def cancel_reservation(self, reserve_id: str) -> None:
        """예약 발송을 취소한다.

        NCP는 ``reserveStatus == READY`` 인 예약만 취소 가능하다.
        이미 PROCESSING/DONE 으로 넘어간 예약은 400을 돌려준다.

        Args:
            reserve_id: send_sms(reserve_time=...) 호출의 request_id.

        Raises:
            NCPBadRequest: 이미 취소/실행된 예약.
            NCPAuthError: 인증 실패.
            NCPError: 기타 API 오류.
        """
        safe_id = quote(reserve_id, safe="")
        path = _RESERVE_CANCEL_PATH.format(
            service_id=self._service_id, reserve_id=safe_id
        )
        headers = make_headers("DELETE", path, self._access_key, self._secret_key)

        response = await self._client.delete(path, headers=headers)
        # 성공은 200 또는 204
        if response.status_code in (200, 204):
            return
        self._raise_for_status(response)
