"""리포트 매칭 (_find_message) 테스트 — phone 보조매칭 모호성 (H4).

cliKey/msgKey 없이 phone 만으로 도달한 delivery report 가, 동일 번호의 여러
미완료 메시지 중 엉뚱한 캠페인에 귀속되지 않도록 "정확히 1건일 때만 매칭"
정책을 검증한다. 대체 발송(-fb)으로 cliKey 가 바뀐 행에 대체 전 시도의 리포트가
붙거나 적용되지 않는지도 검증한다. cliKey 가 있는데 그 행이 없는 리포트는 phone 으로
찾지 않는지도 검증한다.
"""
from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from app.models import Campaign, Message, MsghubRequest
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import ReportItem
from app.services.compose import _make_chat_reply_cli_key
from app.services.report import (
    ReportBeforeRecord,
    awaiting_record,
    process_report,
    split_unrecorded,
)


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


def _sms_report(*, cli_key, msg_key, phone, result_code=SUCCESS_CODE):
    return ReportItem(
        msg_key=msg_key, cli_key=cli_key, ch="SMS",
        result_code=result_code, result_code_desc="결과", product_code="SMS", phone=phone,
    )


@pytest.mark.parametrize("result_code", [SUCCESS_CODE, "59999"])
def test_fallback_report_settles_row_left_on_original_key(db_session, sample_user, result_code):
    """대체 SMS 를 보낸 뒤 cliKey 를 -fb 로 바꾼 트랜잭션이 커밋되지 못하면(웹훅 400) 행은 원래 키로 남지만 SMS 는
    나갔다. 그 -fb 리포트는 원래 키 행의 결과로 확정하고 행 키도 -fb 로 맞춘다 — 안 맞추면 대체 SMS 실패 리포트를
    양방향 실패로 보고 같은 -fb 키로 대체 SMS 를 또 요청한다. 전엔 같은 번호 미완료가 하나일 때만 phone 보조매칭이
    붙여 줬다."""
    campaign, msg = _make_campaign_message(
        db_session, phone="01044445555", status="REG", cli_key="c7-0-0", msg_key="mk-chat",
    )
    campaign.rcs_messagebase_id = "RPCSAXX001"  # 대화방 양방향 답장
    db_session.commit()

    processed, fallback = process_report(
        db_session, [_sms_report(cli_key="c7-0-0-fb", msg_key="mk-sms", phone="01044445555", result_code=result_code)],
    )

    assert (processed, fallback) == (1, [])
    assert (msg.cli_key, msg.status, msg.result_code, msg.channel, msg.msg_key) == (
        "c7-0-0-fb", "DONE", result_code, "SMS", "mk-sms",
    )


# ── cliKey 가 있는데 그 행이 없는 리포트 ─────────────────────────────────────────


def test_keyed_report_without_its_row_is_not_matched_by_phone(db_session, sample_user):
    """cliKey 는 메시지마다 고유하다 — 그 키의 행이 없는 리포트는 같은 번호의 다른 메시지가 아니라 기록하지 않은
    메시지(행 기록 전, 다른 시스템 발송, 롤백된 답장)의 것이다. 전엔 phone 으로 다른 캠페인의 미완료 메시지에 붙어
    그 메시지가 남의 결과(msgKey·채널·과금)로 확정되고, 제 리포트는 DONE 이라 버려졌다."""
    _, msg = _make_campaign_message(
        db_session, phone="01012345678", status="REG", cli_key="c1-0-0", msg_key="mk-a",
    )

    unrecorded = process_report(
        db_session, [_sms_report(cli_key="c999-0-0", msg_key="mk-other", phone="01012345678")],
    )

    assert unrecorded == (0, [])
    assert (msg.status, msg.msg_key, msg.channel) == ("REG", "mk-a", None)

    own = ReportItem(
        msg_key="mk-a", cli_key="c1-0-0", ch="RCS",
        result_code=SUCCESS_CODE, result_code_desc="성공", product_code="SMS", phone="01012345678",
    )
    assert process_report(db_session, [own]) == (1, [])
    assert (msg.status, msg.msg_key, msg.channel, msg.cost) == ("DONE", "mk-a", "RCS", 17)


def test_report_before_its_row_is_recorded_asks_for_redelivery(db_session, sample_user):
    """발송 응답·커밋을 기다리는 캠페인(awaiting_record)의 리포트인데 그 cliKey 행이 아직 없으면 process_report 는
    같은 배치의 다른 리포트까지 아무것도 반영하지 않고 ReportBeforeRecord 를 던진다 — 웹훅은 split_unrecorded 로 먼저
    나눈다(test_sms_fallback). 이미 기록된 행의 리포트는 표시 중에도 반영하고, 표시가 끝난 뒤에도 행이 없는 리포트는
    기록하지 않은 메시지의 것이라 버린다."""
    campaign, recorded = _make_campaign_message(
        db_session, phone="01012345678", status="REG", cli_key="c0-0-0",
    )
    recorded.cli_key = f"c{campaign.id}-0-0"  # 응답을 받아 기록한 앞 청크
    db_session.commit()
    waiting = _sms_report(cli_key=f"c{campaign.id}-1-0", msg_key="mk-1", phone="01012345678")
    _, other = _make_campaign_message(db_session, phone="01055556666", status="REG", cli_key="c-o-0")
    other_report = _sms_report(cli_key="c-o-0", msg_key="mk-o", phone="01055556666")

    with awaiting_record([campaign.id]):
        recorded_report = _sms_report(cli_key=recorded.cli_key, msg_key="mk-0", phone="01012345678")
        assert process_report(db_session, [recorded_report]) == (1, [])

        with awaiting_record([campaign.id]):
            pass  # 겹친 표시 하나가 끝나도 나머지 표시는 남는다
        with pytest.raises(ReportBeforeRecord) as asked:
            process_report(db_session, [other_report, waiting])

        assert asked.value.cli_key == waiting.cli_key
        assert other.status == "REG"

    assert process_report(db_session, [waiting]) == (0, [])


def test_chat_reply_attempt_key_is_recognized_as_its_campaign(db_session):
    """양방향 답장 cliKey 는 시도마다 토큰이 붙는다(compose._make_chat_reply_cli_key) — 행 기록 전 표시(awaiting_record)가 그
    키와 대체 SMS(-fb) 키를 제 캠페인 것으로 알아봐야 답장 요청 중·대체 SMS 커밋 전 리포트를 재전송으로 받는다. 양방향
    cliKey 는 최대 20자(공식 문서)라 캠페인 id 8자리까지 들어가야 하고, 운영에서 받아 준 문자(영소문자·숫자·-)만 쓴다."""
    key = _make_chat_reply_cli_key(12345678)
    assert re.fullmatch(r"c12345678-0-0-[0-9a-f]{6}", key) and len(key) <= 20
    assert _make_chat_reply_cli_key(12345678) != key  # 롤백된 id 를 다시 받은 다음 시도와 겹치지 않는다

    reports = [_sms_report(cli_key=k, msg_key="mk", phone="01012345678") for k in (key, f"{key}-fb")]
    with awaiting_record([12345678]):
        assert split_unrecorded(db_session, reports) == ([], reports)
    assert split_unrecorded(db_session, reports) == (reports, [])
