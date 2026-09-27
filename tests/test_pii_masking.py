"""PII 로그 마스킹 회귀 (PIPA — 전화번호 평문 노출 방지).

리포트 매칭 경로의 경고 로그가 전화번호를 평문으로 남기지 않고 mask_phone 으로
가리는지 caplog 로 고정한다. SMS fallback 실패 로그(send_sms_fallback)도 동일 헬퍼를
쓰며(코드 인스펙션 확인), 본 테스트는 트리거가 쉬운 매칭 경로 2건을 검증한다.

웹훅 파싱 실패 로그는 원문 대신 실패 위치와 구조만 남기는지 모든 로거·레벨에서 확인한다.
"""
from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import Campaign, Message, MsghubRequest
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import MoWebhookPayload, ReportItem
from app.routes.webhook import receive_mo, receive_report
from app.security.settings_store import SettingsStore
from app.services.report import process_report


def _phone_report(phone, cli_key=""):
    """cliKey 없이 phone 만 담긴 리포트 (보조매칭/실패 경로 강제)."""
    return ReportItem(
        msg_key="", cli_key=cli_key, ch="RCS",
        result_code=SUCCESS_CODE, result_code_desc="성공",
        product_code="SMS", phone=phone,
    )


def test_match_failure_log_masks_phone(db_session, caplog):
    """매칭 실패(무매칭) 경고에 전화번호 평문이 없고 마스킹 형태로만 남는다."""
    phone = "01099998888"
    with caplog.at_level(logging.WARNING, logger="app.services.report"):
        process_report(db_session, [_phone_report(phone)])  # 매칭 대상 없음 → 실패 로그

    assert phone not in caplog.text       # 평문 전체 없음
    assert "9999" not in caplog.text      # 가운데 식별 자릿수 없음
    assert "010****8888" in caplog.text   # 마스킹 형태로 기록


def test_ambiguous_match_log_masks_phone(db_session, sample_user, caplog):
    """phone 보조매칭 보류(2건+) 경고에 전화번호 평문이 없고 마스킹된다 (H4 로그)."""
    phone = "01077776666"
    # 동일 phone 을 2개 캠페인에 미완료로 두어 보류 로그를 트리거
    for i in range(2):
        c = Campaign(
            created_by=sample_user.sub, caller_number="0212345678",
            message_type="short", content="x", total_count=1, pending_count=1,
            state="DISPATCHED", created_at="2026-01-01T00:00:00+00:00",
        )
        db_session.add(c)
        db_session.flush()
        req = MsghubRequest(campaign_id=c.id, chunk_index=0, sent_at="2026-01-01T00:00:00+00:00")
        db_session.add(req)
        db_session.flush()
        db_session.add(Message(
            campaign_id=c.id, msghub_request_id=req.id,
            to_number=phone, to_number_raw=phone,
            cli_key=f"amb-{c.id}-{i}", status="REG",
        ))
    db_session.commit()

    with caplog.at_level(logging.WARNING, logger="app.services.report"):
        process_report(db_session, [_phone_report(phone)])  # phone-only → 보류

    assert phone not in caplog.text
    assert "7777" not in caplog.text
    assert "010****6666" in caplog.text


# ── 웹훅 파싱 실패 로그 ──────────────────────────────────────────────────────
# JSON 은 정상이지만 스키마와 다른 페이로드도 원문을 남기지 않는다 — 리포트에는 수신 번호,
# MO 에는 고객 번호·회신 본문이 있다. 응답은 그대로고 로그에는 실패 위치와 구조만 남는다.

PHONE = "01047382915"
PHONE_DASHED = "010-4738-2915"
REPLY_TEXT = "환불 요청합니다 주소는 강남구 테헤란로"
_PII_FRAGMENTS = (PHONE, PHONE_DASHED, "4738", "2915", REPLY_TEXT, "환불", "테헤란로")

REPORT_FORMAT_ERROR = {"error": "invalid report format"}
MO_FORMAT_ERROR = {"code": "20003", "message": "invalid mo format"}


def _post(route, body, db):
    SettingsStore(db).set("msghub.webhook_token", "wtok", is_secret=True, updated_by="test")
    db.commit()
    request = MagicMock()
    request.json = AsyncMock(return_value=body)
    request.client = MagicMock()
    request.client.host = "10.0.0.1"
    return asyncio.run(route("wtok", request, db))


def _assert_no_pii(caplog):
    """모든 로거·레벨의 기록(예외 트레이스백 포함)에 번호·본문 조각이 없다."""
    for fragment in _PII_FRAGMENTS:
        assert fragment not in caplog.text


@pytest.mark.parametrize(
    ("body", "failure"),
    [
        pytest.param(
            {"rptCnt": 1, "rptLst": [PHONE]}, "rptLst[0]: object 자리에 string", id="item-string",
        ),
        pytest.param(
            {"rptCnt": 1, "rptLst": {"phone": PHONE_DASHED, "resultCodeDesc": REPLY_TEXT}},
            "rptLst: array 자리에 object", id="list-object",
        ),
        pytest.param(
            {"rptCnt": 1, "rptLst": [
                {"cliKey": "c1-0-0", "phone": PHONE, "fbReasonLst": {"fbResultDesc": REPLY_TEXT}},
            ]},
            "rptLst[0].fbReasonLst: array 자리에 object", id="fb-reason-object",
        ),
        pytest.param([{"phone": PHONE}], "body: object 자리에 array", id="body-array"),
    ],
)
def test_report_parse_failure_log_has_no_pii(db_session, caplog, body, failure):
    caplog.set_level(logging.DEBUG)

    resp = _post(receive_report, body, db_session)

    assert resp.status_code == 400
    assert json.loads(resp.body) == REPORT_FORMAT_ERROR
    _assert_no_pii(caplog)
    assert f"웹훅 리포트 파싱 실패: PayloadFormatError: {failure}" in caplog.text


@pytest.mark.parametrize(
    ("body", "failure"),
    [
        pytest.param(
            {"moCnt": 2, "moLst": [
                PHONE, {"moNumber": "0212345678", "moCallback": PHONE, "moMsg": REPLY_TEXT},
            ]},
            "moLst[0]: object 자리에 string", id="sms-item-string",
        ),
        pytest.param(
            {"moCnt": 1, "moLst": {"moCallback": PHONE_DASHED, "moMsg": REPLY_TEXT}},
            "moLst: array 자리에 object", id="sms-list-object",
        ),
        pytest.param(
            {"rcsBiCnt": 2, "rcsBiLst": [
                {"msgKey": "k1", "phone": PHONE, "contentInfo": {"textMessage": REPLY_TEXT}},
                [PHONE, REPLY_TEXT],
            ]},
            "rcsBiLst[1]: object 자리에 array", id="rcs-item-array",
        ),
        pytest.param(f"{PHONE} {REPLY_TEXT}", "body: object 자리에 string", id="body-string"),
    ],
)
def test_mo_parse_failure_log_has_no_pii(db_session, caplog, body, failure):
    caplog.set_level(logging.DEBUG)

    resp = _post(receive_mo, body, db_session)

    assert resp.status_code == 400
    assert json.loads(resp.body) == MO_FORMAT_ERROR
    _assert_no_pii(caplog)
    assert f"MO 페이로드 파싱 실패: PayloadFormatError: {failure}" in caplog.text


def test_parse_failure_log_keeps_shape_for_schema_drift(db_session, caplog):
    """스키마 변경 추적용으로 최상위 키 이름, 값의 타입·길이, 항목 수는 남는다."""
    caplog.set_level(logging.DEBUG)
    body = {"moCnt": 1, "moList": [{"moCallback": PHONE, "moMsg": REPLY_TEXT}], "moLst": REPLY_TEXT}

    resp = _post(receive_mo, body, db_session)

    assert json.loads(resp.body) == MO_FORMAT_ERROR
    _assert_no_pii(caplog)
    assert (
        "moLst: array 자리에 string — "
        f"구조 {{moCnt: number, moList: array(1), moLst: string({len(REPLY_TEXT)})}}"
    ) in caplog.text


def test_parse_failure_log_hides_keys_that_are_not_identifiers(db_session, caplog):
    """번호·문장이 키 자리에 오거나 영문 키에 섞여도 키 이름 대신 길이만 남긴다."""
    caplog.set_level(logging.DEBUG)
    phone_key, text_key = f"tel{PHONE}", f"memo {REPLY_TEXT}"
    body = {PHONE: REPLY_TEXT, REPLY_TEXT: [PHONE], phone_key: 1, text_key: None, "rptLst": 7}

    resp = _post(receive_report, body, db_session)

    assert json.loads(resp.body) == REPORT_FORMAT_ERROR
    _assert_no_pii(caplog)
    assert (
        f"구조 {{<키 {len(PHONE)}자>: string({len(REPLY_TEXT)}), "
        f"<키 {len(REPLY_TEXT)}자>: array(1), <키 {len(phone_key)}자>: number, "
        f"<키 {len(text_key)}자>: null, rptLst: number}}"
    ) in caplog.text


def test_unexpected_parse_error_logs_type_and_location_only(db_session, caplog, monkeypatch):
    """스키마 코드가 값이 든 예외를 던져도(int('010…') 의 ValueError 등) 메시지는 남기지 않는다."""

    def parse_with_value_in_error(data):
        return int(data["moLst"][0]["moCallback"] + REPLY_TEXT)

    monkeypatch.setattr(MoWebhookPayload, "from_dict", staticmethod(parse_with_value_in_error))
    caplog.set_level(logging.DEBUG)

    resp = _post(receive_mo, {"moCnt": 1, "moLst": [{"moCallback": PHONE}]}, db_session)

    assert resp.status_code == 400
    assert json.loads(resp.body) == MO_FORMAT_ERROR
    _assert_no_pii(caplog)
    assert "MO 페이로드 파싱 실패: ValueError (test_pii_masking.py:" in caplog.text
