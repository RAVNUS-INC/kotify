"""PII 로그 마스킹 회귀 (PIPA — 전화번호 평문 노출 방지).

리포트 매칭 경로의 경고 로그가 전화번호를 평문으로 남기지 않고 mask_phone 으로
가리는지 caplog 로 고정한다. webhook.py 의 SMS fallback 실패 로그도 동일 헬퍼를
쓰며(코드 인스펙션 확인), 본 테스트는 트리거가 쉬운 report.py 경로 2건을 검증한다.
"""
from __future__ import annotations

import logging

from app.models import Campaign, Message, MsghubRequest
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import ReportItem
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
