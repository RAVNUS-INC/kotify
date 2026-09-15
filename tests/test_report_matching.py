"""리포트 매칭 (_find_message) 테스트 — phone 보조매칭 모호성 (H4).

cliKey/msgKey 없이 phone 만으로 도달한 delivery report 가, 동일 번호의 여러
미완료 메시지 중 엉뚱한 캠페인에 귀속되지 않도록 "정확히 1건일 때만 매칭"
정책을 검증한다. 대체 발송(-fb)으로 cliKey 가 바뀐 행에 대체 전 시도의 리포트가
붙거나 적용되지 않는지도 검증한다.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import Campaign, Message, MsghubRequest
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import ReportItem
from app.services.report import process_report


def _make_campaign_message(db, *, phone, status, cli_key, msg_key=None, sub="test-sub-001"):
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
        cli_key=cli_key, msg_key=msg_key, status=status,
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


# ── 대체 발송(-fb)으로 cliKey 가 바뀐 행 ─────────────────────────────────────────


def _chat_failure(*, cli_key, msg_key, phone):
    """양방향 답장(CHAT) 실패 리포트."""
    return ReportItem(
        msg_key=msg_key, cli_key=cli_key, ch="RCS",
        result_code="51004", result_code_desc="RCS 미지원 단말",
        product_code="CHAT", phone=phone,
    )


def test_stale_report_for_renamed_fallback_key_not_matched_by_phone(db_session, sample_user):
    """대체 SMS 로 확정된 뒤 원래 cliKey 의 실패 리포트가 재전송돼도 같은 번호의 다른 미완료
    메시지에 phone 으로 붙지 않는다 — {cliKey}-fb 행으로 찾아 버린다."""
    # 대체 SMS 성공 리포트까지 받은 답장 — msg_key 도 SMS 의 것으로 바뀌어 원래 msgKey 로는 못 찾는다
    _make_campaign_message(
        db_session, phone="01033332222", status="DONE", cli_key="c-f-0-fb", msg_key="mk-sms",
    )
    # 같은 고객에게 이어 보낸 답장 — 아직 리포트 대기
    _make_campaign_message(db_session, phone="01033332222", status="REG", cli_key="c-g-0")

    processed, fallback = process_report(
        db_session, [_chat_failure(cli_key="c-f-0", msg_key="mk-chat", phone="01033332222")],
    )

    assert (processed, fallback) == (0, [])
    assert _status_of(db_session, "c-g-0") == "REG"


def test_report_without_fb_cli_key_does_not_settle_fallback_row(db_session, sample_user):
    """-fb 행은 그 cliKey 로 온 리포트만 확정한다 — cliKey 없이 msgKey 로 매칭된 리포트는
    대체 전 시도(양방향)의 것이다. (cliKey 없는 대체 SMS 리포트는 재조정이 -fb 로 확정)"""
    _make_campaign_message(
        db_session, phone="01044443333", status="FB_PENDING", cli_key="c-h-0-fb", msg_key="mk-chat",
    )

    processed, _ = process_report(
        db_session, [_chat_failure(cli_key="", msg_key="mk-chat", phone="01044443333")],
    )

    assert processed == 0
    assert _status_of(db_session, "c-h-0-fb") == "FB_PENDING"
