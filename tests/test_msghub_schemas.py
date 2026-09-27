"""msghub 페이로드 파싱 테스트.

실제 production에서 관측된 페이로드 샘플을 fixture로 고정해두어,
schemas.py가 MO/Report 웹훅을 올바르게 파싱하는지 회귀를 방지한다.

과거 사고: schemas.py 의 from_dict 변경이 커밋에 누락됐는데도 런타임에
`items=0`으로 조용히 무시되어 DB에 저장되지 않던 문제가 있었다. 해당
같은 버그는 이 테스트에서 `assert items[0].mo_key == ...`가 실패하며
CI에서 빨간색으로 잡힌다.
"""
from __future__ import annotations

import pytest

from app.msghub.schemas import (
    MoItem,
    MoWebhookPayload,
    PayloadFormatError,
    ReportItem,
    WebhookReport,
)

# ─── RCS 양방향 MO (rcsBiLst) ────────────────────────────────────────────────
# 2026-04-22 production에서 받은 실제 페이로드 형식.
RCS_BI_MO_PAYLOAD = {
    "rcsBiCnt": 1,
    "rcsBiLst": [
        {
            "msgKey": "xntL6UT2mP.6gGoIL",
            "ymd": "2026-04-22",
            "hm": "0507",
            "chatbotId": "0236639888",
            "replyId": "B02R052026042205073823365159662155453906",
            "postbackId": None,
            "postbackData": None,
            "eventType": "message",
            "contentInfo": {
                "textMessage": "ㄴ",
                "fileMessage": None,
                "geolocationPushMessage": None,
            },
            "moRecvDt": "2026-04-22T05:07:38",
            "phone": "01043439107",
        }
    ],
    "rcsBiaLst": [],
    "rcsBirLst": [],
}


def test_mo_webhook_payload_parses_rcsBiLst() -> None:
    """RCS 양방향 MO(rcsBiLst) 페이로드를 정확히 파싱한다."""
    payload = MoWebhookPayload.from_dict(RCS_BI_MO_PAYLOAD)
    assert payload.mo_cnt == 1
    assert len(payload.items) == 1
    item = payload.items[0]
    assert item.mo_key == "xntL6UT2mP.6gGoIL"
    assert item.number == "01043439107"
    assert item.callback == "0236639888"
    assert item.reply_id == "B02R052026042205073823365159662155453906"
    assert item.mo_type == "message"
    assert item.mo_msg == "ㄴ"
    assert item.mo_recv_dt == "2026-04-22T05:07:38"
    # contentInfo 전체가 dict로 보존되어야 한다
    assert isinstance(item.content_info, dict)
    assert item.content_info["textMessage"] == "ㄴ"


def test_mo_item_from_rcs_bi_direct() -> None:
    """MoItem.from_dict 가 rcsBiLst 항목을 직접 처리한다."""
    item = MoItem.from_dict(RCS_BI_MO_PAYLOAD["rcsBiLst"][0])
    assert item.mo_key == "xntL6UT2mP.6gGoIL"
    assert item.reply_id == "B02R052026042205073823365159662155453906"
    assert item.mo_type == "message"
    assert item.mo_msg == "ㄴ"


def test_mo_item_postback_event_preserves_fields() -> None:
    """postback 이벤트(버튼 클릭 등)는 postback_id/postback_data를 담는다."""
    d = {
        "msgKey": "AAA111",
        "phone": "01012345678",
        "chatbotId": "0236639888",
        "replyId": "R01",
        "eventType": "postback",
        "contentInfo": {"textMessage": None, "fileMessage": None},
        "postbackId": "btn-001",
        "postbackData": "set_by_chatbot_open_url",
        "moRecvDt": "2026-04-22T10:00:00",
    }
    item = MoItem.from_dict(d)
    assert item.mo_type == "postback"
    assert item.postback_id == "btn-001"
    assert item.postback_data == "set_by_chatbot_open_url"
    assert item.mo_msg is None  # textMessage가 None이면 본문 없음


# ─── SMS/MMS MO (moLst) — 공식 §5.2 ─────────────────────────────────────────
SMS_MO_PAYLOAD = {
    "moCnt": 1,
    "moLst": [
        {
            "moKey": "1234",
            "moNumber": "15445367",
            "moType": "SMSMO",
            "moCallback": "01012345678",
            "productCode": "",
            "moTitle": "테스트",
            "moMsg": "테스트 본문",
            "telco": "LGU",
            "contentCnt": 1,
            "contentInfoLst": [
                {
                    "contentName": "",
                    "contentSize": "",
                    "contentExt": "",
                    "contentUrl": "",
                }
            ],
            "moRecvDt": "2024-01-29T09:22:55",
        }
    ],
}


def test_mo_webhook_payload_parses_moLst() -> None:
    """SMS/MMS MO(moLst) 페이로드를 정확히 파싱한다 — §5.2 호환."""
    payload = MoWebhookPayload.from_dict(SMS_MO_PAYLOAD)
    assert payload.mo_cnt == 1
    assert len(payload.items) == 1
    item = payload.items[0]
    assert item.mo_key == "1234"
    assert item.number == "15445367"
    assert item.callback == "01012345678"
    assert item.mo_type == "SMSMO"
    assert item.mo_title == "테스트"
    assert item.mo_msg == "테스트 본문"
    assert item.telco == "LGU"
    assert item.content_cnt == 1
    # contentInfoLst 은 list 로 보존
    assert isinstance(item.content_info, list)


# ─── 엣지 케이스 ─────────────────────────────────────────────────────────────


def test_mo_webhook_payload_empty_body() -> None:
    """빈 body는 items 0건으로 안전하게 파싱된다."""
    payload = MoWebhookPayload.from_dict({})
    assert payload.mo_cnt == 0
    assert payload.items == []


def test_mo_webhook_payload_only_rcsBiaLst() -> None:
    """rcsBiaLst/rcsBirLst만 있는 heartbeat/ack 페이로드도 items=0."""
    payload = MoWebhookPayload.from_dict(
        {"rcsBiCnt": 0, "rcsBiLst": [], "rcsBiaLst": [{}], "rcsBirLst": [{}]}
    )
    assert payload.mo_cnt == 0
    assert payload.items == []


# ─── Report 웹훅 (rptLst) — §2.8 §3 ────────────────────────────────────────
REPORT_WEBHOOK_PAYLOAD = {
    "rptCnt": 1,
    "rptLst": [
        {
            "isBi": False,
            "msgKey": "lXXYpOIuCd.6cGlYN",
            "cliKey": "c1-0-0",
            "ch": "RCS",
            "resultCode": "10000",
            "resultCodeDesc": "성공",
            "productCode": "SMS",
            "fbReasonLst": [
                {
                    "ch": "RCS",
                    "fbResultCode": "54002",
                    "fbResultDesc": "No Rcs Capability",
                    "telco": "KT",
                }
            ],
            "rptDt": "2026-04-22T05:07:38",
            "rptRegDt": "2026-04-22T05:07:39",
            "phone": "01043439107",
            "userCustomFields": {"key1": "value1"},
            "recvDt": "2026-04-22T05:06:30",
        }
    ],
}


def test_webhook_report_parses_rptLst() -> None:
    """Report 웹훅이 v11 delivery report 필드를 모두 파싱한다."""
    report = WebhookReport.from_dict(REPORT_WEBHOOK_PAYLOAD)
    assert report.rpt_cnt == 1
    assert len(report.items) == 1
    item = report.items[0]
    assert item.msg_key == "lXXYpOIuCd.6cGlYN"
    assert item.cli_key == "c1-0-0"
    assert item.ch == "RCS"
    assert item.result_code == "10000"
    assert item.phone == "01043439107"
    assert item.rpt_dt == "2026-04-22T05:07:38"
    # v11 신규 필드
    assert item.rpt_reg_dt == "2026-04-22T05:07:39"
    assert item.recv_dt == "2026-04-22T05:06:30"
    assert item.user_custom_fields == {"key1": "value1"}
    # fallback 사유 파싱
    assert len(item.fb_reason_lst) == 1
    fb = item.fb_reason_lst[0]
    assert fb.fb_result_code == "54002"
    assert fb.telco == "KT"


def test_report_item_empty_fb_reason() -> None:
    """fbReasonLst가 없을 때 빈 리스트로 파싱된다."""
    d = {
        "msgKey": "abc",
        "cliKey": "c1-0-0",
        "ch": "SMS",
        "resultCode": "10000",
        "resultCodeDesc": "성공",
        "productCode": "SMS",
    }
    item = ReportItem.from_dict(d)
    assert item.fb_reason_lst == []
    assert item.is_bi is False
    assert item.phone == ""


# ─── 구조 오류 (PayloadFormatError) ──────────────────────────────────────────
# 웹훅 라우트가 메시지를 로그에 그대로 남긴다 — 필드 경로와 JSON 타입만 담고 값은 담지 않는다.


@pytest.mark.parametrize(
    ("parse", "body", "message"),
    [
        (WebhookReport.from_dict, ["01012345678"], "body: object 자리에 array"),
        (WebhookReport.from_dict, {"rptLst": "01012345678"}, "rptLst: array 자리에 string"),
        (WebhookReport.from_dict, {"rptLst": [{}, 1012345678]}, "rptLst[1]: object 자리에 number"),
        (
            WebhookReport.from_dict,
            {"rptLst": [{"phone": "01012345678", "fbReasonLst": [{}, "환불 요청"]}]},
            "rptLst[0].fbReasonLst[1]: object 자리에 string",
        ),
        (MoWebhookPayload.from_dict, None, "body: object 자리에 null"),
        (MoWebhookPayload.from_dict, {"moLst": True}, "moLst: array 자리에 boolean"),
        (
            MoWebhookPayload.from_dict,
            {"moLst": {"moCallback": "01012345678", "moMsg": "환불 요청"}},
            "moLst: array 자리에 object",
        ),
        (
            MoWebhookPayload.from_dict,
            {"rcsBiLst": [{"msgKey": "k"}, "01012345678"]},
            "rcsBiLst[1]: object 자리에 string",
        ),
    ],
)
def test_payload_format_error_names_path_and_type_only(parse, body, message) -> None:
    with pytest.raises(PayloadFormatError) as excinfo:
        parse(body)
    assert str(excinfo.value) == message


@pytest.mark.parametrize("empty", [None, "", 0, False, {}, []])
def test_empty_list_fields_still_mean_no_items(empty) -> None:
    """빈 값은 예전처럼 항목 0건이다 — 구조 검사를 더해도 받아들이는 페이로드는 같다.

    엄격하게 거부하면 heartbeat 같은 빈 페이로드가 400 이 돼 msghub 가 계속 재전송한다.
    """
    assert WebhookReport.from_dict({"rptCnt": 0, "rptLst": empty}).items == []
    assert MoWebhookPayload.from_dict({"moLst": empty}).items == []
    assert MoWebhookPayload.from_dict({"rcsBiLst": empty}).items == []
    assert ReportItem.from_dict({"msgKey": "k", "fbReasonLst": empty}).fb_reason_lst == []


# ─── 건수 필드 (rptCnt·moCnt·rcsBiCnt) ───────────────────────────────────────
# 로그의 %d 에만 쓴다 — 정수가 아니면 거부하지 않고 항목 수로 대신한다(포맷 오류가 원값을 stderr 에 쓴다).

_SMS_MO = {"moKey": "k1", "moNumber": "0212345678", "moCallback": "01012345678", "moMsg": "안녕"}


@pytest.mark.parametrize(
    "declared", ["01012345678 환불", "2", 2.0, float("nan"), True, None, {"n": 1}, [1, 2]],
)
def test_count_that_is_not_an_integer_falls_back_to_item_count(declared) -> None:
    assert MoWebhookPayload.from_dict({"moCnt": declared, "moLst": [_SMS_MO] * 3}).mo_cnt == 3
    assert MoWebhookPayload.from_dict({"rcsBiCnt": declared, "rcsBiLst": [{"msgKey": "k"}]}).mo_cnt == 1
    assert WebhookReport.from_dict({"rptCnt": declared, "rptLst": [{}, {}]}).rpt_cnt == 2


def test_integer_count_is_kept_even_if_it_differs_from_items() -> None:
    """msghub 가 적은 건수는 그대로 둔다 — 항목 수와 다르면 로그에서 스키마 변경을 알아챌 단서다."""
    assert MoWebhookPayload.from_dict({"moCnt": 5, "moLst": [_SMS_MO]}).mo_cnt == 5
    assert MoWebhookPayload.from_dict({"rcsBiCnt": 4, "rcsBiLst": [{"msgKey": "k"}]}).mo_cnt == 4
    assert WebhookReport.from_dict({"rptCnt": 7, "rptLst": [{}]}).rpt_cnt == 7
    # 빠진 건수는 예전 그대로다 — MO 는 항목 수, 리포트는 0.
    assert MoWebhookPayload.from_dict({"moLst": [_SMS_MO]}).mo_cnt == 1
    assert WebhookReport.from_dict({"rptLst": [{}]}).rpt_cnt == 0
