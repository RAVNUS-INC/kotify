"""msghub API 요청/응답 데이터 모델."""
from __future__ import annotations

from dataclasses import dataclass, field


# ── 예외 ─────────────────────────────────────────────────────────────────────


class MsghubError(Exception):
    """msghub API 기본 예외."""

    def __init__(self, message: str, code: str | None = None, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code

    def __str__(self) -> str:
        parts = []
        if self.code:
            parts.append(f"[{self.code}]")
        parts.append(super().__str__())
        if self.status_code:
            parts.append(f"(HTTP {self.status_code})")
        return " ".join(parts)


class MsghubBadRequest(MsghubError):
    """파라미터/요청 오류. 재시도 불가."""


class MsghubAuthError(MsghubError):
    """인증 실패 (20xxx). 자격증명 점검 필요."""


class MsghubRateLimited(MsghubError):
    """CPS 초과 (29002). 재시도 필요."""


class MsghubServerError(MsghubError):
    """서버 오류 (5xx, 29012 등). 재시도 가능."""


# ── 공통 스키마 ──────────────────────────────────────────────────────────────


@dataclass
class RecvInfo:
    """수신자 정보 (발송 요청용)."""

    cli_key: str    # ^[a-zA-Z0-9-_.@]{1,30}$
    phone: str      # ^[0-9-]{1,20}$
    merge_data: dict[str, str] | None = None
    user_custom_fields: dict[str, str] | None = None

    def to_dict(self) -> dict:
        d: dict = {"cliKey": self.cli_key, "phone": self.phone}
        if self.merge_data is not None:
            d["mergeData"] = self.merge_data
        if self.user_custom_fields is not None:
            d["userCustomFields"] = self.user_custom_fields
        return d


@dataclass
class FbInfo:
    """Fallback (대체 발송) 정보."""

    ch: str          # "SMS" 또는 "MMS"
    msg: str         # 대체 메시지 본문
    title: str | None = None       # MMS 시 필수, 최대 40바이트
    file_id: str | None = None     # MMS 파일 (fileIdLst와 택1)
    file_id_lst: list[str] | None = None  # MMS 파일 목록 (최대 3개)

    def to_dict(self) -> dict:
        d: dict = {"ch": self.ch, "msg": self.msg}
        if self.title is not None:
            d["title"] = self.title
        if self.file_id is not None:
            d["fileId"] = self.file_id
        elif self.file_id_lst is not None:
            d["fileIdLst"] = self.file_id_lst
        return d


# ── 발송 응답 ────────────────────────────────────────────────────────────────


@dataclass
class SendResultItem:
    """발송 응답의 수신자별 결과."""

    cli_key: str
    msg_key: str
    phone: str
    code: str        # "10000" = 성공
    message: str


@dataclass
class SendResponse:
    """SMS/LMS/MMS/RCS 발송 응답."""

    code: str                    # 전체 요청 결과 코드
    message: str                 # 결과 메시지
    items: list[SendResultItem] = field(default_factory=list)

    @staticmethod
    def from_dict(data: dict) -> SendResponse:
        items = []
        for item in data.get("data") or []:
            if isinstance(item, dict):
                items.append(SendResultItem(
                    cli_key=item.get("cliKey", ""),
                    msg_key=item.get("msgKey", ""),
                    phone=item.get("phone", ""),
                    code=item.get("code", ""),
                    message=item.get("message", ""),
                ))
        return SendResponse(
            code=data.get("code", ""),
            message=data.get("message", ""),
            items=items,
        )


@dataclass
class ReserveResponse:
    """예약 발송 응답 (일반 발송과 구조 다름)."""

    code: str
    message: str
    web_req_id: str = ""
    reg_dt: str = ""

    @staticmethod
    def from_dict(data: dict) -> ReserveResponse:
        inner = data.get("data") or {}
        return ReserveResponse(
            code=data.get("code", ""),
            message=data.get("message", ""),
            web_req_id=inner.get("webReqId", ""),
            reg_dt=inner.get("regDt", ""),
        )


# ── 파일 업로드 응답 ─────────────────────────────────────────────────────────


@dataclass
class UploadFileResponse:
    """파일 사전등록 응답."""

    file_id: str
    file_exp_dt: str     # 만료일시
    ch: str = ""         # 채널 (mms/rcs)

    @staticmethod
    def from_dict(data: dict) -> UploadFileResponse:
        inner = data.get("data") or {}
        return UploadFileResponse(
            file_id=inner.get("fileId", ""),
            file_exp_dt=inner.get("fileExpDt", ""),
            ch=inner.get("ch", ""),
        )


# ── 리포트 ───────────────────────────────────────────────────────────────────


@dataclass
class FbReason:
    """Fallback 사유."""

    ch: str                  # 실패한 원래 채널 (예: "RCS")
    fb_result_code: str      # 실패 코드
    fb_result_desc: str      # 실패 설명
    telco: str = ""          # 이통사

    @staticmethod
    def from_dict(d: dict) -> FbReason:
        return FbReason(
            ch=d.get("ch", ""),
            fb_result_code=d.get("fbResultCode", ""),
            fb_result_desc=d.get("fbResultDesc", ""),
            telco=d.get("telco", ""),
        )


def _parse_fb_reason_lst(raw: list | None) -> list[FbReason]:
    return [FbReason.from_dict(fb) for fb in raw or []]


@dataclass
class ReportItem:
    """리포트 (웹훅/폴링) 수신자별 결과.

    v11 delivery report 웹훅 스펙 기준 전 필드 파싱. 기존 7필드 + 신규 5필드:
    isBi, phone, rpt_reg_dt, user_custom_fields, recv_dt.
    """

    msg_key: str
    cli_key: str
    ch: str                  # 실제 발송 채널 (SMS/LMS/MMS/RCS)
    result_code: str         # "10000" = 성공
    result_code_desc: str
    product_code: str        # 과금 상품코드
    telco: str = ""
    rpt_dt: str = ""         # 결과 수신 일시
    fb_reason_lst: list[FbReason] = field(default_factory=list)
    # v11 추가 필드
    is_bi: bool = False                         # RCS 양방향 여부
    phone: str = ""                             # 수신번호 (cliKey 매칭 실패 시 보조)
    rpt_reg_dt: str = ""                        # 결과 등록 일시
    recv_dt: str = ""                           # 발송 요청 일시
    user_custom_fields: dict | None = None      # 발송 시 심은 커스텀 필드

    @staticmethod
    def from_dict(d: dict) -> ReportItem:
        raw_ucf = d.get("userCustomFields")
        return ReportItem(
            msg_key=d.get("msgKey", ""),
            cli_key=d.get("cliKey", ""),
            ch=d.get("ch", ""),
            result_code=d.get("resultCode", ""),
            result_code_desc=d.get("resultCodeDesc", ""),
            product_code=d.get("productCode", ""),
            telco=d.get("telco", ""),
            rpt_dt=d.get("rptDt", ""),
            fb_reason_lst=_parse_fb_reason_lst(d.get("fbReasonLst")),
            is_bi=bool(d.get("isBi", False)),
            phone=d.get("phone", ""),
            rpt_reg_dt=d.get("rptRegDt", ""),
            recv_dt=d.get("recvDt", ""),
            user_custom_fields=raw_ucf if isinstance(raw_ucf, dict) else None,
        )


@dataclass
class WebhookReport:
    """웹훅 리포트 페이로드."""

    rpt_cnt: int
    items: list[ReportItem] = field(default_factory=list)

    @staticmethod
    def from_dict(data: dict) -> WebhookReport:
        items = [ReportItem.from_dict(d) for d in data.get("rptLst") or []]
        return WebhookReport(
            rpt_cnt=data.get("rptCnt", 0),
            items=items,
        )


@dataclass
class MoItem:
    """MO (수신) 항목 — RCS 양방향(rcsBiLst)과 SMS/MMS(moLst) 두 형식 통합.

    msghub는 두 가지 MO 웹훅 페이로드를 보낸다:

    1) RCS 양방향 MO (rcsBiLst 항목):
       { "msgKey", "phone", "chatbotId", "replyId", "eventType" (message|postback),
         "contentInfo": {"textMessage", "fileMessage", "geolocationPushMessage"},
         "postbackId", "postbackData", "moRecvDt", "ymd", "hm" }

    2) SMS/MMS MO (공식 §5.2, moLst 항목):
       { "moKey", "moNumber", "moCallback", "moType" (SMSMO|MMSMO|RCSMO),
         "moTitle", "moMsg", "telco", "productCode", "contentCnt",
         "contentInfoLst": [...], "moRecvDt" }
    """

    mo_key: str
    number: str                             # phone / moNumber
    callback: str = ""                      # chatbotId / moCallback
    mo_type: str = ""                       # eventType 또는 moType
    reply_id: str = ""                      # 양방향 전용 (답장 발송 시 필요)
    mo_title: str | None = None             # SMS/MMS MO 전용
    mo_msg: str | None = None               # textMessage / moMsg
    telco: str = ""
    content_cnt: int = 0
    content_info: dict | list | None = None # 양방향 dict / SMS-MMS list
    product_code: str = ""
    postback_id: str | None = None
    postback_data: str | None = None
    mo_recv_dt: str = ""

    @staticmethod
    def from_dict(d: dict) -> MoItem:
        # msgKey 존재 여부로 RCS 양방향 vs SMS/MMS 형식 자동 감지
        if "msgKey" in d:
            content = d.get("contentInfo") or {}
            text = content.get("textMessage") if isinstance(content, dict) else None
            return MoItem(
                mo_key=d.get("msgKey", ""),
                number=d.get("phone", ""),
                callback=d.get("chatbotId", ""),
                mo_type=d.get("eventType", ""),
                reply_id=d.get("replyId", ""),
                mo_msg=text,
                content_info=content if isinstance(content, dict) else None,
                postback_id=d.get("postbackId"),
                postback_data=d.get("postbackData"),
                mo_recv_dt=d.get("moRecvDt", ""),
            )
        # SMS/MMS MO (§5.2)
        content_lst = d.get("contentInfoLst")
        return MoItem(
            mo_key=d.get("moKey", ""),
            number=d.get("moNumber", ""),
            callback=d.get("moCallback", ""),
            mo_type=d.get("moType", ""),
            mo_title=d.get("moTitle"),
            mo_msg=d.get("moMsg"),
            telco=d.get("telco", ""),
            content_cnt=d.get("contentCnt", 0) or 0,
            content_info=content_lst if isinstance(content_lst, list) else None,
            product_code=d.get("productCode", ""),
            mo_recv_dt=d.get("moRecvDt", ""),
        )


@dataclass
class MoWebhookPayload:
    """MO 웹훅 페이로드 — 두 형식 자동 감지.

    RCS 양방향: { "rcsBiCnt", "rcsBiLst": [...], "rcsBiaLst", "rcsBirLst" }
    SMS/MMS:    { "moCnt", "moLst": [...] }
    """

    mo_cnt: int
    items: list[MoItem] = field(default_factory=list)

    @staticmethod
    def from_dict(data: dict) -> MoWebhookPayload:
        if "rcsBiLst" in data:
            raw_items = data.get("rcsBiLst") or []
            count = data.get("rcsBiCnt", 0) or len(raw_items)
        else:
            raw_items = data.get("moLst") or []
            count = data.get("moCnt", 0) or len(raw_items)
        return MoWebhookPayload(
            mo_cnt=count,
            items=[MoItem.from_dict(d) for d in raw_items],
        )


@dataclass
class SentQueryItem:
    """cliKey 기반 개별 조회 결과."""

    msg_key: str
    cli_key: str
    status: str              # REG/ING/DONE/OVER_DATE/INVALID_KEY
    ch: str = ""
    result_code: str = ""
    result_code_desc: str = ""
    product_code: str = ""
    telco: str = ""
    rpt_dt: str = ""
    fb_reason_lst: list[FbReason] = field(default_factory=list)

    @staticmethod
    def from_dict(d: dict) -> SentQueryItem:
        return SentQueryItem(
            msg_key=d.get("msgKey", ""),
            cli_key=d.get("cliKey", ""),
            status=d.get("status", ""),
            ch=d.get("ch", ""),
            result_code=d.get("resultCode", ""),
            result_code_desc=d.get("resultCodeDesc", ""),
            product_code=d.get("productCode", ""),
            telco=d.get("telco", ""),
            rpt_dt=d.get("rptDt", ""),
            fb_reason_lst=_parse_fb_reason_lst(d.get("fbReasonLst")),
        )
