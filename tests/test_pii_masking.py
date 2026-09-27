"""PII 로그 마스킹 회귀 (PIPA — 전화번호 평문 노출 방지).

리포트 매칭 경로의 경고 로그가 전화번호를 평문으로 남기지 않고 mask_phone 으로
가리는지 caplog 로 고정한다. SMS fallback 실패 로그(send_sms_fallback)도 동일 헬퍼를
쓰며(코드 인스펙션 확인), 본 테스트는 트리거가 쉬운 매칭 경로 2건을 검증한다.

웹훅 파싱 실패 로그는 원문 대신 실패 위치와 구조만 남기는지 모든 로거·레벨에서 확인한다.
파서를 통과한 뒤의 저장·처리 실패 로그(SQL 바인딩 값), 건수 필드의 %d 포맷, MO 거부 경고도
번호·본문을 남기지 않는지 확인한다.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.db import Base, create_db_engine
from app.db import engine as app_engine
from app.models import Caller, Campaign, Message, MsghubRequest
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


def _set_webhook_token(db):
    SettingsStore(db).set("msghub.webhook_token", "wtok", is_secret=True, updated_by="test")
    db.commit()


def _call(route, body, db):
    request = MagicMock()
    request.json = AsyncMock(return_value=body)
    request.client = MagicMock()
    request.client.host = "10.0.0.1"
    return asyncio.run(route("wtok", request, db))


def _post(route, body, db):
    _set_webhook_token(db)
    return _call(route, body, db)


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


# ── 웹훅 저장·처리 실패 로그 ─────────────────────────────────────────────────
# 파서를 통과한 페이로드가 저장·처리에서 실패하면 log.exception 이 SQLAlchemy 예외를 남긴다. 예외 문구의
# `[parameters: …]` 에 바인딩 값(번호·본문·원문 JSON)이 들어가지 않게 앱 엔진은 hide_parameters=True 다.
# conftest 엔진에는 그 설정이 없어서 운영 엔진 팩토리(create_db_engine)로 연 파일 DB 에서 확인한다.

MO_SUCCESS = {"code": "10000", "message": "success"}
MO_STORAGE_FAILED = {"code": "20004", "message": "storage failed"}
PARAMETERS_HIDDEN = "[SQL parameters hidden due to hide_parameters=True]"
_MO_ITEM = {"moKey": "k1", "moNumber": "0212345678", "moCallback": PHONE, "moMsg": REPLY_TEXT}


@pytest.fixture
def app_db(tmp_path):
    """운영 엔진 설정(app.db.create_db_engine)으로 연 파일 DB 세션 — 발신번호 0212345678 이 등록돼 있다."""
    engine = create_db_engine(f"sqlite:///{tmp_path / 'kotify.db'}")

    @event.listens_for(engine, "connect")
    def _no_busy_wait(dbapi_conn, _record):
        # 쓰기 잠금 케이스가 busy timeout(5초)을 기다리지 않고 바로 실패하게 한다 — 로그 내용과는 무관하다.
        dbapi_conn.execute("PRAGMA busy_timeout = 0")

    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    session.add(Caller(
        number="0212345678", label="대표번호", active=1, is_default=1,
        created_at=datetime.now(UTC).isoformat(),
    ))
    session.commit()
    yield session
    session.close()
    engine.dispose()


def test_app_engine_hides_sql_parameters(tmp_path, caplog):
    """앱 엔진과 그 팩토리는 예외 문구와 SQL 로그에 바인딩 값을 넣지 않는다 — SQL 문과 DB 오류는 남는다."""
    assert app_engine.hide_parameters is True  # 앱이 실제로 쓰는 엔진(app.db.engine)

    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.DEBUG, logger="sqlalchemy")  # SQL 로그를 켜도 값은 나오지 않는다
    engine = create_db_engine(f"sqlite:///{tmp_path / 'kotify.db'}")
    try:
        with engine.connect() as conn, pytest.raises(OperationalError) as excinfo:
            conn.execute(
                text("SELECT :phone, :reply FROM no_such_table"), {"phone": PHONE, "reply": REPLY_TEXT},
            )
    finally:
        engine.dispose()

    message = str(excinfo.value)
    assert "no such table: no_such_table" in message
    assert "SELECT ?, ? FROM no_such_table" in message
    assert PARAMETERS_HIDDEN in message
    for fragment in _PII_FRAGMENTS:
        assert fragment not in message
    _assert_no_pii(caplog)
    assert PARAMETERS_HIDDEN in caplog.text


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(
            {"moCnt": 1, "moLst": [{**_MO_ITEM, "moMsg": {"text": REPLY_TEXT}}]}, id="sms-moMsg-object",
        ),
        pytest.param(
            {"rcsBiCnt": 1, "rcsBiLst": [{
                "msgKey": "r1", "phone": PHONE, "chatbotId": "0212345678",
                "contentInfo": {"textMessage": REPLY_TEXT}, "postbackData": {"data": REPLY_TEXT},
            }]},
            id="rcs-postbackData-object",
        ),
    ],
)
def test_mo_storage_failure_log_has_no_pii(app_db, caplog, body):
    """파서는 통과하지만 값이 객체라 INSERT 바인딩이 실패한다 — 응답은 그대로 20004, 로그에 값은 없다."""
    caplog.set_level(logging.DEBUG)

    resp = _post(receive_mo, body, app_db)

    assert resp.status_code == 400
    assert json.loads(resp.body) == MO_STORAGE_FAILED
    _assert_no_pii(caplog)
    assert "MO 저장 실패" in caplog.text
    assert "Error binding parameter" in caplog.text  # DB 오류와 SQL 문은 진단용으로 남는다
    assert "INSERT INTO mo_messages" in caplog.text
    assert PARAMETERS_HIDDEN in caplog.text


def test_mo_storage_failure_on_write_lock_log_has_no_pii(app_db, caplog, tmp_path):
    """정상 MO 도 다른 연결이 쓰기 잠금을 쥐고 있으면 저장에 실패한다(database is locked) — 로그에 값은 없다."""
    _set_webhook_token(app_db)
    holder = sqlite3.connect(tmp_path / "kotify.db", isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    caplog.set_level(logging.DEBUG)
    try:
        resp = _call(receive_mo, {"moCnt": 1, "moLst": [_MO_ITEM]}, app_db)
    finally:
        holder.execute("ROLLBACK")
        holder.close()

    assert resp.status_code == 400
    assert json.loads(resp.body) == MO_STORAGE_FAILED
    _assert_no_pii(caplog)
    assert "database is locked" in caplog.text
    assert PARAMETERS_HIDDEN in caplog.text


def test_report_processing_failure_log_has_no_pii(app_db, caplog):
    """리포트 phone 이 객체면 phone 보조매칭 조회의 바인딩이 실패한다 — 응답은 그대로 400, 로그에 번호는 없다."""
    caplog.set_level(logging.DEBUG)
    body = {"rptCnt": 1, "rptLst": [
        {"cliKey": "", "msgKey": "", "phone": {"number": PHONE}, "resultCode": SUCCESS_CODE},
    ]}

    resp = _post(receive_report, body, app_db)

    assert resp.status_code == 400
    assert json.loads(resp.body) == {"error": "processing failed"}
    _assert_no_pii(caplog)
    assert "웹훅 리포트 처리 실패" in caplog.text
    assert PARAMETERS_HIDDEN in caplog.text


# ── 건수 필드(rptCnt·moCnt·rcsBiCnt) ─────────────────────────────────────────
# 건수는 로그의 %d 에만 쓴다. 문자열이 그대로 가면 logging 이 포맷에 실패하고, 운영(핸들러 없음 →
# last-resort)에서는 handleError 가 원값이 든 `Arguments: (…)` 를 stderr 에 쓴다 — caplog 에는 안 남는다.
# 파서가 정수가 아닌 건수를 항목 수로 바꾼다. 받아들이는 페이로드와 응답은 그대로다.


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"moCnt": f"{PHONE} 환불", "moLst": [_MO_ITEM]}, id="sms-moCnt-string"),
        pytest.param(
            {"rcsBiCnt": {"phone": PHONE}, "rcsBiLst": [{
                "msgKey": "r1", "phone": PHONE, "chatbotId": "0212345678",
                "contentInfo": {"textMessage": REPLY_TEXT},
            }]},
            id="rcs-rcsBiCnt-object",
        ),
    ],
)
def test_mo_count_that_is_not_an_integer_is_logged_as_item_count(db_session, sample_caller, caplog, body):
    caplog.set_level(logging.DEBUG)

    resp = _post(receive_mo, body, db_session)

    assert json.loads(resp.body) == MO_SUCCESS
    _assert_no_pii(caplog)
    assert "MO 수신: 저장 1건, 중복 0건, 거부 0건, 페이로드 1건" in caplog.text


def test_mo_summary_does_not_dump_count_to_stderr(db_session, sample_caller, capsys, monkeypatch):
    """운영처럼 핸들러 없이 기록해도(logging.lastResort → stderr) logging 오류 덤프가 없다."""
    # 루트의 pytest 캡처 핸들러까지 가지 않게 끊으면 운영과 같이 last-resort 핸들러가 stderr 로 쓴다.
    monkeypatch.setattr(logging.getLogger("app.routes.webhook"), "propagate", False)

    resp = _post(receive_mo, {"moCnt": f"{PHONE} 환불", "moLst": [_MO_ITEM]}, db_session)

    err = capsys.readouterr().err
    assert json.loads(resp.body) == MO_SUCCESS
    assert "Logging error" not in err
    assert "MO 수신: 저장 1건, 중복 0건, 거부 0건, 페이로드 1건" in err
    for fragment in _PII_FRAGMENTS:
        assert fragment not in err


def test_report_count_that_is_not_an_integer_is_logged_as_item_count(db_session, caplog):
    caplog.set_level(logging.DEBUG)
    body = {"rptCnt": f"{PHONE} 환불", "rptLst": [
        {"cliKey": "c999-0-0", "msgKey": "mk-1", "resultCode": SUCCESS_CODE},
    ]}

    resp = _post(receive_report, body, db_session)

    assert json.loads(resp.body) == {"status": "ok", "processed": 0, "fallback": 0}
    _assert_no_pii(caplog)
    assert "웹훅 리포트 처리: 0/1건" in caplog.text


# ── MO 거부 경고의 수신번호 ──────────────────────────────────────────────────
# 거부 경고는 공식 MO 수신번호(보통 우리 번호)를 남긴다. 구형 반대 표기(두 번호 모두 010)에서는 고객 번호,
# RCS 는 숫자 없는 chatbotId 를 그대로 쓰므로 그 자리에 온 문장일 수 있다.


def test_rejected_mo_log_masks_number(db_session, sample_caller, caplog):
    caplog.set_level(logging.DEBUG)
    other = "01099998888"
    body = {"moCnt": 1, "moLst": [
        {"moKey": "k1", "moNumber": PHONE, "moCallback": other, "moMsg": REPLY_TEXT},
    ]}

    resp = _post(receive_mo, body, db_session)

    assert json.loads(resp.body) == MO_SUCCESS
    for fragment in (PHONE, "4738", other, "9999", REPLY_TEXT, "환불"):
        assert fragment not in caplog.text
    assert "MO 수신번호 미등록 — 거부(위변조 의심): 010****2915" in caplog.text
    assert "MO 수신: 저장 0건, 중복 0건, 거부 1건, 페이로드 1건" in caplog.text


def test_rejected_rcs_mo_log_does_not_echo_text_chatbot_id(db_session, sample_caller, caplog):
    """숫자 없는 chatbotId 는 길이만 남긴다 — mask_phone 의 앞 3·뒤 4자도 본문 조각이다."""
    caplog.set_level(logging.DEBUG)
    body = {"rcsBiCnt": 1, "rcsBiLst": [{
        "msgKey": "r1", "phone": PHONE, "chatbotId": REPLY_TEXT,
        "contentInfo": {"textMessage": REPLY_TEXT},
    }]}

    resp = _post(receive_mo, body, db_session)

    assert json.loads(resp.body) == MO_SUCCESS
    _assert_no_pii(caplog)
    assert f"MO 수신번호 미등록 — 거부(위변조 의심): <숫자 아닌 값 {len(REPLY_TEXT)}자>" in caplog.text
