"""리포트 매칭 (_find_message) 테스트 — phone 보조매칭 모호성 (H4).

cliKey/msgKey 없이 phone 만으로 도달한 delivery report 가, 동일 번호의 여러
미완료 메시지 중 엉뚱한 캠페인에 귀속되지 않도록 "정확히 1건일 때만 매칭"
정책을 검증한다.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import Campaign, Message, MsghubRequest
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import ReportItem
from app.services.report import process_report


def _make_campaign_message(db, *, phone, status, cli_key, sub="test-sub-001"):
    """캠페인 1개 + 메시지 1개를 만들어 (campaign, message) 반환."""
    campaign = Campaign(
        created_by=sub, caller_number="0212345678", message_type="short",
        content="x", total_count=1, pending_count=1, state="DISPATCHED",
        created_at="2026-01-01T00:00:00+00:00",
    )
    db.add(campaign)
    db.flush()
    req = MsghubRequest(
        campaign_id=campaign.id, chunk_index=0,
        sent_at="2026-01-01T00:00:00+00:00",
    )
    db.add(req)
    db.flush()
    msg = Message(
        campaign_id=campaign.id, msghub_request_id=req.id,
        to_number=phone, to_number_raw=phone,
        cli_key=cli_key, status=status,
    )
    db.add(msg)
    db.commit()
    return campaign, msg


def _phone_report(phone):
    """cliKey/msgKey 없이 phone 만 담긴 성공 리포트 (보조매칭 경로 강제)."""
    return ReportItem(
        msg_key="", cli_key="", ch="RCS",
        result_code=SUCCESS_CODE, result_code_desc="성공",
        product_code="SMS", phone=phone,
    )


def _status_of(db, cli_key):
    return db.execute(
        select(Message.status).where(Message.cli_key == cli_key)
    ).scalar_one()


def test_phone_match_skipped_when_ambiguous(db_session, sample_user):
    """동일 phone 이 2개 캠페인에 미완료 → phone-only 리포트는 매칭하지 않는다 (H4)."""
    _make_campaign_message(db_session, phone="01099998888", status="REG", cli_key="c-a-0")
    _make_campaign_message(db_session, phone="01099998888", status="REG", cli_key="c-b-0")

    processed, _ = process_report(db_session, [_phone_report("01099998888")])

    # 모호하므로 어느 쪽에도 귀속되지 않음 — 둘 다 REG 유지
    assert processed == 0
    assert _status_of(db_session, "c-a-0") == "REG"
    assert _status_of(db_session, "c-b-0") == "REG"


def test_phone_match_succeeds_when_unique(db_session, sample_user):
    """phone 미완료가 정확히 1건이면 정상 매칭한다 (정상 경로 회귀 가드)."""
    _make_campaign_message(db_session, phone="01077776666", status="REG", cli_key="c-u-0")

    processed, _ = process_report(db_session, [_phone_report("01077776666")])

    assert processed == 1
    assert _status_of(db_session, "c-u-0") == "DONE"


def test_phone_match_ignores_completed_messages(db_session, sample_user):
    """이미 DONE 인 동일번호 메시지는 모호성 판정에서 제외 — 남은 미완료 1건에 매칭."""
    _make_campaign_message(db_session, phone="01055554444", status="DONE", cli_key="c-d-0")
    _make_campaign_message(db_session, phone="01055554444", status="REG", cli_key="c-d-1")

    processed, _ = process_report(db_session, [_phone_report("01055554444")])

    # DONE 은 보조매칭 후보(PENDING/REG/ING/FB_PENDING)가 아니므로 후보는 REG 1건뿐
    assert processed == 1
    assert _status_of(db_session, "c-d-0") == "DONE"  # 기존 DONE 불변
    assert _status_of(db_session, "c-d-1") == "DONE"  # 미완료였던 건만 갱신
