"""U+ msghub 메시징 API 클라이언트.

호스트 구조:
- API (인증/리포트/예약관리):  api.msghub.uplus.co.kr
- 메시지 발송 (SMS/MMS/RCS):  api-send.msghub.uplus.co.kr
- 파일/관리:                   mnt-api.msghub.uplus.co.kr

모든 HTTP 호출은 httpx.AsyncClient + TokenManager JWT 인증.
"""
from __future__ import annotations

import json
import logging
from typing import Literal
from urllib.parse import quote

import httpx

from app.msghub.auth import TokenManager
from app.msghub.codes import SUCCESS_CODE, is_retryable
from app.msghub.schemas import (
    FbInfo,
    MsghubAuthError,
    MsghubBadRequest,
    MsghubError,
    MsghubRateLimited,
    MsghubServerError,
    RecvInfo,
    ReserveResponse,
    SendResponse,
    UploadFileResponse,
)

log = logging.getLogger(__name__)

# 단일 호출당 최대 수신자 수 (msghub 제약)
CHUNK_SIZE = 10

# HTTP 요청 타임아웃 (초)
_TIMEOUT = 30.0

# 환경별 호스트 매핑
_HOSTS = {
    "production": {
        "api": "https://api.msghub.uplus.co.kr",
        "send": "https://api-send.msghub.uplus.co.kr",
        "mnt": "https://mnt-api.msghub.uplus.co.kr",
    },
    "qa": {
        "api": "https://api.msghub-qa.uplus.co.kr",
        "send": "https://api-send.msghub-qa.uplus.co.kr",
        "mnt": "https://mnt-api.msghub-qa.uplus.co.kr",
    },
}


def _raise_for_response(body: dict, http_status: int) -> None:
    """msghub 응답 코드에 따라 적절한 예외를 raise."""
    code = body.get("code", "")
    message = body.get("message", "")

    if code == SUCCESS_CODE:
        return

    # 인증 에러 (20xxx)
    if code.startswith("20") or code in ("29011", "29025"):
        raise MsghubAuthError(f"[{code}] {message}", code=code, status_code=http_status)

    # CPS 초과 (재시도 가능)
    if code == "29002":
        raise MsghubRateLimited(f"[{code}] {message}", code=code, status_code=http_status)

    # 서버 에러 또는 재시도 가능
    if is_retryable(code) or http_status >= 500:
        raise MsghubServerError(f"[{code}] {message}", code=code, status_code=http_status)

    # 그 외 요청 에러 (29020 용량 초과 포함 — 재시도 불가)
    raise MsghubBadRequest(f"[{code}] {message}", code=code, status_code=http_status)


def _parse_json(resp: httpx.Response) -> dict:
    """HTTP 응답을 JSON으로 파싱. 실패 시 MsghubServerError."""
    if resp.status_code >= 500:
        raise MsghubServerError(
            f"HTTP {resp.status_code} 서버 오류",
            code="HTTP_ERROR",
            status_code=resp.status_code,
        )
    try:
        body = resp.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise MsghubServerError(
            f"응답 파싱 실패 (HTTP {resp.status_code})",
            code="PARSE_ERROR",
            status_code=resp.status_code,
        ) from exc
    if not isinstance(body, dict):
        raise MsghubServerError(
            f"응답 형식 오류 (HTTP {resp.status_code})",
            code="PARSE_ERROR",
            status_code=resp.status_code,
        )
    return body


class MsghubClient:
    """U+ msghub 메시징 API 클라이언트.

    lifespan에서 생성하고 aclose()로 정리한다.

    사용법:
        client = MsghubClient(env, api_key, api_pwd, brand_id, chatbot_id)
        resp = await client.send_rcs_chat(callback, content, recv_list, fb_info)
    """

    def __init__(
        self,
        env: Literal["production", "qa"],
        api_key: str,
        api_pwd: str,
        brand_id: str = "",
        chatbot_id: str = "",
    ) -> None:
        if env not in _HOSTS:
            raise ValueError("msghub 환경은 'production' 또는 'qa'여야 합니다")
        hosts = _HOSTS[env]
        self._api_base = hosts["api"]
        self._send_base = hosts["send"]
        self._mnt_base = hosts["mnt"]
        self._brand_id = brand_id
        self._chatbot_id = chatbot_id

        self._http = httpx.AsyncClient(timeout=_TIMEOUT)
        self._token_mgr = TokenManager(
            base_url=self._api_base,
            api_key=api_key,
            api_pwd=api_pwd,
            http=self._http,
        )

    async def aclose(self) -> None:
        """HTTP 클라이언트를 닫는다."""
        await self._http.aclose()

    async def test_auth(self) -> bool:
        """인증 테스트. AuthError 시 raise."""
        return await self._token_mgr.test_auth()

    async def health_check(self) -> bool:
        """공식 세션 health check. 1분 이하 주기로 호출해야 세션 알람이 동작한다."""
        await self._call(
            "PUT", f"{self._api_base}/client/v1/healthCheck", json_content=False, timeout=_TIMEOUT,
        )
        return True

    def update_rcs_config(self, brand_id: str, chatbot_id: str) -> None:
        """RCS 설정 업데이트 (런타임)."""
        self._brand_id = brand_id
        self._chatbot_id = chatbot_id

    def update_credentials(self, api_key: str, api_pwd: str) -> None:
        """자격증명 업데이트 (설정 변경 시)."""
        self._token_mgr.invalidate()
        self._token_mgr = TokenManager(
            base_url=self._api_base,
            api_key=api_key,
            api_pwd=api_pwd,
            http=self._http,
        )

    # ── 인증 헤더 ────────────────────────────────────────────────────────────

    async def _auth_headers(self) -> dict[str, str]:
        token = await self._token_mgr.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def _call(
        self, method: str, url: str, *, json_content: bool = True, **kwargs,
    ) -> tuple[dict, int]:
        """토큰을 붙여 요청하고 결과 코드를 검사한다. (응답 JSON, HTTP 상태) 를 돌려준다.

        서버가 인증 오류(20xxx·29011·29025)로 거부하면 캐시한 토큰을 버리고 한 번만 새로 발급받아
        다시 보낸다 — 로컬 만료 시각 전에 서버가 토큰을 무효화하면(무효화 조건은 문서에 없음)
        예전엔 만료까지 최대 ~50분 같은 토큰으로 계속 실패했다. 거부된 요청은 접수되지 않았으므로
        다시 보내도 중복이 없다. 두 번째도 거부되면 MsghubAuthError 를 그대로 올린다.
        """
        for attempt in range(2):
            headers = await self._auth_headers()
            if not json_content:
                headers.pop("Content-Type", None)
            resp = await self._http.request(method, url, headers=headers, **kwargs)
            data = _parse_json(resp)
            try:
                _raise_for_response(data, resp.status_code)
            except MsghubAuthError as exc:
                if attempt:
                    raise
                log.warning("msghub 가 토큰을 거부함 [%s] — 토큰 재발급 후 1회 재시도", exc.code)
                self._token_mgr.invalidate()
                continue
            return data, resp.status_code
        raise AssertionError("unreachable")

    # ── SMS 발송 ─────────────────────────────────────────────────────────────

    async def send_sms(
        self,
        callback: str,
        msg: str,
        recv_list: list[RecvInfo],
        *,
        campaign_id: str | None = None,
        resv_yn: str | None = None,
        resv_req_dt: str | None = None,
    ) -> SendResponse | ReserveResponse:
        """SMS 발송 (최대 10명/요청, 90바이트 이하).

        예약 발송(resv_yn="Y") 시 ReserveResponse 반환.
        """
        if not recv_list:
            raise ValueError("수신자 목록이 비어있습니다")
        if len(recv_list) > CHUNK_SIZE:
            raise ValueError(f"SMS 최대 {CHUNK_SIZE}건: {len(recv_list)}건 요청됨")

        body: dict = {
            "callback": callback,
            "msg": msg,
            "recvInfoLst": [r.to_dict() for r in recv_list],
        }
        if campaign_id:
            body["campaignId"] = campaign_id
        if resv_yn:
            body["resvYn"] = resv_yn
        if resv_req_dt:
            body["resvReqDt"] = resv_req_dt

        # v11 통합 RCS 기준 SMS endpoint. 구버전 /msg/v1/sms는 deprecated.
        data, _ = await self._call("POST", f"{self._send_base}/xms/sms/v1", json=body)

        if resv_yn == "Y":
            return ReserveResponse.from_dict(data)
        return SendResponse.from_dict(data)

    # ── LMS/MMS 발송 ────────────────────────────────────────────────────────

    async def send_mms(
        self,
        callback: str,
        title: str,
        msg: str,
        recv_list: list[RecvInfo],
        *,
        file_id_lst: list[str] | None = None,
        campaign_id: str | None = None,
        resv_yn: str | None = None,
        resv_req_dt: str | None = None,
    ) -> SendResponse | ReserveResponse:
        """LMS/MMS 발송 (최대 10명/요청).

        file_id_lst 없으면 LMS, 있으면 MMS.
        예약 발송(resv_yn="Y") 시 ReserveResponse 반환.
        """
        if not recv_list:
            raise ValueError("수신자 목록이 비어있습니다")
        if len(recv_list) > CHUNK_SIZE:
            raise ValueError(f"MMS 최대 {CHUNK_SIZE}건: {len(recv_list)}건 요청됨")

        body: dict = {
            "callback": callback,
            "title": title,
            "msg": msg,
            "recvInfoLst": [r.to_dict() for r in recv_list],
        }
        if file_id_lst:
            body["fileIdLst"] = file_id_lst
        if campaign_id:
            body["campaignId"] = campaign_id
        if resv_yn:
            body["resvYn"] = resv_yn
        if resv_req_dt:
            body["resvReqDt"] = resv_req_dt

        # v11 기준 MMS/LMS endpoint (파일ID 사용 또는 본문만).
        # multipart 직접 첨부는 /xms/mms/file/v1 — 이 앱은 사전등록 방식만 사용.
        # 구버전 /msg/v1/mms는 deprecated.
        data, _ = await self._call("POST", f"{self._send_base}/xms/mms/v1", json=body)

        if resv_yn == "Y":
            return ReserveResponse.from_dict(data)
        return SendResponse.from_dict(data)

    # ── RCS 단방향 ───────────────────────────────────────────────────────────

    async def send_rcs(
        self,
        messagebase_id: str,
        callback: str,
        recv_list: list[RecvInfo],
        *,
        header: str = "0",
        fb_info_lst: list[FbInfo] | None = None,
        expiry_option: str | None = None,
        campaign_id: str | None = None,
        resv_yn: str | None = None,
        resv_req_dt: str | None = None,
    ) -> SendResponse | ReserveResponse:
        """RCS 단방향 발송 (통합 RCS v11, 최대 10명/요청).

        messagebase_id (v11):
          RPSSAXX001 (SMS형), RPLSAXX001 (LMS형),
          RPMSMTX001 (MMS T형), RPMSMMX001 (MMS M형)

        예약 발송(resv_yn="Y") 시 ReserveResponse 반환.
        """
        if not recv_list:
            raise ValueError("수신자 목록이 비어있습니다")
        if len(recv_list) > CHUNK_SIZE:
            raise ValueError(f"RCS 최대 {CHUNK_SIZE}건: {len(recv_list)}건 요청됨")

        # v11 통합 RCS 스펙(공식 문서 §2.3.2 §1)의 필드만 조립:
        # messagebaseId, callback, header, recvInfoLst,
        # fbInfoLst, expiryOption, campaignId, resvYn, resvReqDt, buttons 등.
        # copyAllowed, footer는 스펙에 없음.
        body: dict = {
            "messagebaseId": messagebase_id,
            "callback": callback,
            "header": header,
            "recvInfoLst": [r.to_dict() for r in recv_list],
        }
        if fb_info_lst:
            body["fbInfoLst"] = [fb.to_dict() for fb in fb_info_lst]
        if expiry_option:
            body["expiryOption"] = expiry_option
        if campaign_id:
            body["campaignId"] = campaign_id
        if resv_yn:
            body["resvYn"] = resv_yn
        if resv_req_dt:
            body["resvReqDt"] = resv_req_dt

        data, _ = await self._call("POST", f"{self._send_base}/rcs/v1.1", json=body)

        if resv_yn == "Y":
            return ReserveResponse.from_dict(data)
        return SendResponse.from_dict(data)

    # ── RCS 양방향 ───────────────────────────────────────────────────────────

    async def send_rcs_chat(
        self,
        description: str,
        phone: str,
        cli_key: str,
        *,
        messagebase_id: str = "RPCSAXX001",
        reply_id: str = "",
        telco: str = "",
        header: str = "0",
        campaign_id: str | None = None,
    ) -> SendResponse:
        """RCS 양방향 응답메시지 발송 (v11 통합 RCS, 단건).

        ⚠️  **이 엔드포인트는 MO 응답 전용.** msghub 공식 문서 §2.3.2 §2에
        따르면 `/rcs/bi/v1.1`은 "고객의 MO 수신에 대한 응답 발송"에만 사용
        가능하다. outbound 브로드캐스트엔 응답할 MO 의 replyId 가 없다.
        outbound 단문은 `send_rcs`를 `messagebase_id="RPSSAXX001"`(통합 RCS
        SMS형)로 호출해야 한다.

        호출: 대화방 답장(compose.dispatch_chat_reply). 요청 필드는 공식 §2.3.2 §2
        Request Body 기준이며 moRecvDt 같은 MO 수신 시각 필드는 없다.
        양방향엔 fbInfoLst 도 없어, 리포트 실패 시 webhook 이 대체 발송한다.

        messagebase_id 기본값: RPCSAXX001 (양방향 텍스트형, 8원).
        양방향은 recvInfoLst 대신 최상위 phone/cliKey 사용 (cliKey 최대 20자).
        chatbot_id는 인스턴스의 _chatbot_id 사용.

        reply_id: 고객 MO(rcsBiLst)의 replyId. 받은 뒤 24시간 유효
            (codes.REPLY_ID_VALID_HOURS).
        telco: 수신자 통신사 (LGU/SKT/KT). 공식 스펙상 필수(●)지만 RCS 양방향 MO
            페이로드에 telco 가 없고, MNP 때문에 번호만으로 판정할 수도 없어 빈
            문자열로 보낸다. 빈 값을 msghub 가 어떻게 처리하는지는 문서에 없다(확인 필요).
        """
        if not self._chatbot_id:
            raise MsghubError("RCS 양방향 발송에 chatbot_id가 필요합니다", code="CONFIG_ERROR")

        # v11 양방향 스펙에는 copyAllowed, footer 필드가 없음 (제거).
        body: dict = {
            "messagebaseId": messagebase_id,
            "chatbotId": self._chatbot_id,
            "replyId": reply_id,
            "cliKey": cli_key,
            "telco": telco,
            "phone": phone,
            "body": {"description": description},
            "header": header,
        }
        if campaign_id:
            body["campaignId"] = campaign_id

        data, _ = await self._call("POST", f"{self._send_base}/rcs/bi/v1.1", json=body)
        return SendResponse.from_dict(data)

    # ── 파일 업로드 ──────────────────────────────────────────────────────────

    async def upload_file(
        self,
        channel: Literal["mms", "rcs"],
        file_id: str,
        file_bytes: bytes,
        content_type: str = "image/jpeg",
    ) -> UploadFileResponse:
        """파일 사전등록.

        Args:
            channel: "mms" 또는 "rcs"
            file_id: 클라이언트 지정 파일 ID (^[a-zA-Z0-9-_]{0,64}$)
            file_bytes: 파일 바이트
            content_type: MIME 타입
        """
        req_file = json.dumps({"fileId": file_id, "wideYn": "N"})

        # multipart에서는 Content-Type을 직접 설정하지 않음 (httpx가 boundary 자동 설정)
        data, _ = await self._call(
            "POST",
            f"{self._mnt_base}/file/v1/{channel}",
            json_content=False,
            data={"reqFile": req_file},
            files={"filePart": (f"{file_id}.jpg", file_bytes, content_type)},
        )
        return UploadFileResponse.from_dict(data)

    # ── 예약 발송 관리 ───────────────────────────────────────────────────────

    async def cancel_reservation(self, web_req_id: str, reason: str = "") -> None:
        """예약 발송 취소."""
        body = {"webReqId": web_req_id, "resvCnclReason": reason or "사용자 취소"}
        await self._call("POST", f"{self._api_base}/msg/v1/resv/sendCancel", json=body)

    # ── MO 컨텐츠 ────────────────────────────────────────────────────────────

    async def fetch_mo_content(self, mo_key: str, *, max_bytes: int) -> tuple[bytes, str]:
        """MMS MO 첨부 파일을 받는다 (GET /mo/v1/file/{moKey}). (본문, Content-Type) 을 돌려준다.

        응답은 JSON 이 아니라 파일 본문이다. JSON 이 오면 오류 응답으로 보고 결과 코드대로 예외를 낸다
        (토큰 거부는 _call 처럼 한 번 재발급해 다시 받는다). max_bytes 를 넘으면 MsghubBadRequest
        ("TOO_LARGE") — 다시 받아도 같으니 재시도하지 않는다. 컨텐츠는 msghub 에 7일 보관된다.
        """
        url = f"{self._api_base}/mo/v1/file/{quote(mo_key, safe='')}"
        for attempt in range(2):
            headers = await self._auth_headers()
            async with self._http.stream("GET", url, headers=headers) as resp:
                content_type = resp.headers.get("content-type", "application/octet-stream")
                if resp.status_code >= 500:
                    raise MsghubServerError(
                        f"HTTP {resp.status_code} 서버 오류", code="HTTP_ERROR", status_code=resp.status_code,
                    )
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise MsghubBadRequest(
                            f"MO 컨텐츠가 상한({max_bytes} bytes)을 넘음", code="TOO_LARGE",
                            status_code=resp.status_code,
                        )
                    chunks.append(chunk)
                status_code = resp.status_code
            body = b"".join(chunks)
            if "json" not in content_type.lower() and status_code == 200:
                if not body:
                    raise MsghubServerError("MO 컨텐츠가 비어 있음", code="EMPTY", status_code=status_code)
                return body, content_type.split(";")[0].strip()
            try:
                data = json.loads(body)
            except ValueError as exc:
                raise MsghubServerError(
                    f"MO 컨텐츠 응답 해석 실패 (HTTP {status_code})", code="PARSE_ERROR", status_code=status_code,
                ) from exc
            if not isinstance(data, dict):
                raise MsghubServerError("MO 컨텐츠 응답 형식 오류", code="PARSE_ERROR", status_code=status_code)
            try:
                _raise_for_response(data, status_code)
            except MsghubAuthError:
                if attempt:
                    raise
                self._token_mgr.invalidate()
                continue
            raise MsghubServerError(
                "MO 컨텐츠 대신 JSON 성공 응답이 옴", code="PARSE_ERROR", status_code=status_code,
            )
        raise AssertionError("unreachable")

    # ── 리포트 (개별 조회) ───────────────────────────────────────────────────

    async def query_sent(self, cli_keys: list[tuple[str, str]]) -> list[dict]:
        """cliKey 기반 발송 결과 개별 조회.

        Args:
            cli_keys: [(cliKey, reqDt), ...] 최대 10건.
                reqDt 형식: "YYYY-MM-DD"
        """
        if len(cli_keys) > 10:
            raise ValueError(f"최대 10건 조회 가능: {len(cli_keys)}건 요청됨")

        url = f"{self._api_base}/msg/v1/sent"
        body = {
            "cliKeyLst": [
                {"cliKey": ck, "reqDt": dt} for ck, dt in cli_keys
            ],
        }
        data, _ = await self._call("POST", url, json=body)
        inner = data.get("data")
        items = inner.get("cliKeyLst") if isinstance(inner, dict) else None
        return [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []

    # ── 통계 조회 ────────────────────────────────────────────────────────────

    async def get_daily_stats(self, ymd: str, project_id: str) -> list[dict]:
        """일자별 발송 통계 조회 (msghub 서버 기준).

        우리 DB의 campaign/message 집계(_refresh_campaign_counters)와 대조해
        누락된 webhook/과금 차이를 감사할 때 사용.

        Args:
            ymd: 조회 일자 "YYYYMMDD" 형식
            project_id: msghub 프로젝트 ID

        Returns:
            채널별 통계 dict 리스트. 각 항목:
              - ymd, projectId, apiKey, ch
              - totCnt (전체 발송), succCnt (성공), failCnt (실패)
        """
        url = f"{self._mnt_base}/msg/v1/stat"
        body = {"ymd": ymd, "projectId": project_id}
        data, _ = await self._call("POST", url, json=body)
        payload = data.get("data")
        if isinstance(payload, list):
            return payload
        return []
