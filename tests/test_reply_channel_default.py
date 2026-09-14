"""대화방 답장 전송 방식 — 번호별 기본값(최근 전달 성공 방식) + 리포트 전 채널 표시.

기본값은 그 번호로 가장 최근에 전달 성공한 발송의 "요청한 전송 방식"(RCS/일반)이다.
RCS 로 보냈다가 SMS 로 대체 도달한 건도 RCS 로 유지해, 일시적 대체 한 번에 기본값이
일반으로 굳지 않게 한다. 리포트가 오기 전(channel 비어 있음) 메시지는 요청한 전송 방식으로
표시한다 — 예전엔 무조건 SMS 로 보여 RCS 답장도 SMS 처럼 보였다.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.models import Campaign, Message, MsghubRequest
from app.msghub.codes import SUCCESS_CODE
from app.routes.threads import MessageCreateBody, api_get_thread
from app.services.chat import default_send_channel

_CALLER = "0212345678"
_PHONE = "01099998888"
_TID = f"{_CALLER}:{_PHONE}"

_RCS = "RPSSAXX001"   # 단방향 RCS
_CHAT = "RPCSAXX001"  # 양방향 CHAT


def _send(
    db,
    *,
    rcs_messagebase_id,
    status="DONE",
    result_code=SUCCESS_CODE,
    channel=None,
    phone=_PHONE,
    message_type="short",
    cli_key=None,
):
    """phone 에게 보낸 발송 1건(Campaign + Message). id 순서 = 발송 순서."""
    c = Campaign(
        created_by="test-sub-001", caller_number=_CALLER, message_type=message_type,
        content="안내드립니다", total_count=1, state="DISPATCHED",
        created_at="2026-09-01T00:00:00+00:00", rcs_messagebase_id=rcs_messagebase_id,
    )
    db.add(c)
    db.flush()
    req = MsghubRequest(campaign_id=c.id, chunk_index=0, sent_at="2026-09-01T00:00:00+00:00")
    db.add(req)
    db.flush()
    db.add(Message(
        campaign_id=c.id, msghub_request_id=req.id, to_number=phone, to_number_raw=phone,
        status=status, result_code=result_code, channel=channel, cli_key=cli_key,
    ))
    db.commit()


# ── default_send_channel ─────────────────────────────────────────────────────


def test_no_history_has_no_default(db_session, sample_user):
    assert default_send_channel(db_session, _PHONE) is None


def test_last_success_rcs_defaults_to_rcs(db_session, sample_user):
    _send(db_session, rcs_messagebase_id=_RCS, channel="RCS")
    assert default_send_channel(db_session, _PHONE) == "rcs"


def test_last_success_general_defaults_to_sms(db_session, sample_user):
    _send(db_session, rcs_messagebase_id=_RCS, channel="RCS")
    _send(db_session, rcs_messagebase_id=None, channel="SMS")  # 이후 일반으로 성공
    assert default_send_channel(db_session, _PHONE) == "sms"


def test_rcs_delivered_as_sms_fallback_stays_rcs(db_session, sample_user):
    """RCS 로 요청했으나 SMS 로 대체 도달 — 기본값은 요청 방식(RCS) 유지."""
    _send(db_session, rcs_messagebase_id=_RCS, channel="SMS")
    assert default_send_channel(db_session, _PHONE) == "rcs"


def test_chat_reply_with_webhook_sms_fallback_stays_rcs(db_session, sample_user):
    """양방향 CHAT 실패 → webhook SMS 대체 도달한 건도 RCS 로 본다."""
    _send(db_session, rcs_messagebase_id=_CHAT, channel="SMS")
    assert default_send_channel(db_session, _PHONE) == "rcs"


@pytest.mark.parametrize(
    ("status", "result_code"),
    [
        ("REG", None),         # 접수 — 리포트 대기
        ("FAILED", None),      # 요청 단계 실패
        ("DONE", "59999"),     # 리포트 실패 코드
    ],
)
def test_pending_or_failed_latest_is_skipped(db_session, sample_user, status, result_code):
    """최근 발송이 대기·실패면 건너뛰고 그 전의 전달 성공 방식을 쓴다."""
    _send(db_session, rcs_messagebase_id=_RCS, channel="RCS")
    _send(db_session, rcs_messagebase_id=None, status=status, result_code=result_code)
    assert default_send_channel(db_session, _PHONE) == "rcs"


def test_other_number_history_is_ignored(db_session, sample_user):
    _send(db_session, rcs_messagebase_id=None, channel="SMS", phone="01011112222")
    assert default_send_channel(db_session, _PHONE) is None


# ── api_get_thread: defaultSendChannel + 리포트 전 채널 표시 ──────────────────


def test_thread_detail_exposes_default_send_channel(db_session, sample_user):
    _send(db_session, rcs_messagebase_id=_RCS, channel="RCS")
    detail = api_get_thread(_TID, db=db_session)["data"]
    assert detail["defaultSendChannel"] == "rcs"


def test_thread_detail_omits_default_without_success(db_session, sample_user):
    _send(db_session, rcs_messagebase_id=_RCS, status="REG", result_code=None)
    detail = api_get_thread(_TID, db=db_session)["data"]
    assert "defaultSendChannel" not in detail


def test_unreported_rcs_message_is_labeled_rcs(db_session, sample_user):
    """리포트 전 RCS 답장은 SMS 가 아니라 RCS 로 표시(말풍선·스레드 채널 모두)."""
    _send(db_session, rcs_messagebase_id=_RCS, status="REG", result_code=None)
    detail = api_get_thread(_TID, db=db_session)["data"]
    assert detail["messages"][-1]["kind"] == "rcs"
    assert detail["channel"] == "rcs"


def test_unreported_general_long_message_is_labeled_lms(db_session, sample_user):
    _send(db_session, rcs_messagebase_id=None, status="REG", result_code=None, message_type="long")
    detail = api_get_thread(_TID, db=db_session)["data"]
    assert detail["messages"][-1]["kind"] == "lms"


def test_report_channel_wins_over_requested_method(db_session, sample_user):
    """리포트가 오면 실제 도달 채널로 표시 — RCS 요청이 SMS 로 대체 도달하면 SMS."""
    _send(db_session, rcs_messagebase_id=_RCS, channel="SMS")
    detail = api_get_thread(_TID, db=db_session)["data"]
    assert detail["messages"][-1]["kind"] == "sms"
    assert detail["channel"] == "sms"


def test_direct_fallback_before_report_is_labeled_direct(db_session, sample_user):
    """RCS 요청이 즉시 실패(29003 등)해 -fb 로 직접 SMS 발송된 건은 리포트 전에도 SMS."""
    _send(
        db_session, rcs_messagebase_id=_RCS, status="REG", result_code=SUCCESS_CODE,
        cli_key="c1-0-0-fb",
    )
    detail = api_get_thread(_TID, db=db_session)["data"]
    assert detail["messages"][-1]["kind"] == "sms"
    assert detail["channel"] == "sms"


def test_webhook_sms_fallback_pending_is_labeled_sms(db_session, sample_user):
    """양방향 리포트 실패 → webhook SMS 대체 발송 대기(FB_PENDING)는 실패한 RCS 가 아니라 SMS."""
    _send(
        db_session, rcs_messagebase_id=_CHAT, status="FB_PENDING", result_code="59999",
        channel="RCS", cli_key="c1-0-0-fb",
    )
    detail = api_get_thread(_TID, db=db_session)["data"]
    assert detail["messages"][-1]["kind"] == "sms"


def test_direct_fallback_after_report_uses_report_channel(db_session, sample_user):
    _send(db_session, rcs_messagebase_id=_RCS, channel="SMS", cli_key="c1-0-0-fb")
    detail = api_get_thread(_TID, db=db_session)["data"]
    assert detail["messages"][-1]["kind"] == "sms"


# ── POST body ────────────────────────────────────────────────────────────────


def test_message_body_send_channel_defaults_to_rcs_for_old_clients():
    assert MessageCreateBody(text="안녕하세요").sendChannel == "rcs"


def test_message_body_accepts_sms():
    assert MessageCreateBody(text="안녕하세요", sendChannel="sms").sendChannel == "sms"


def test_message_body_rejects_unknown_send_channel():
    with pytest.raises(ValidationError):
        MessageCreateBody(text="안녕하세요", sendChannel="kakao")


# ── POST /threads/{id}/messages: 고른 전송 방식 전달 ──────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("send_channel", ["rcs", "sms"])
async def test_post_message_passes_chosen_send_channel(
    db_session, sample_user, monkeypatch, send_channel
):
    """라우트가 body.sendChannel 을 send_reply 에 그대로 넘긴다(누락 시 조용히 rcs 가 됨)."""
    from app.routes.threads import api_post_message

    calls: list[dict] = []

    async def _spy_send_reply(**kw):
        calls.append(kw)
        return SimpleNamespace(id=42)

    monkeypatch.setattr("app.main.get_msghub_client", lambda: object())
    monkeypatch.setattr("app.services.chat.send_reply", _spy_send_reply)

    body = MessageCreateBody(text="안녕하세요", sendChannel=send_channel)
    resp = await api_post_message(_TID, body, user=sample_user, db=db_session)

    assert [c["send_channel"] for c in calls] == [send_channel]
    assert calls[0]["phone"] == _PHONE
    assert resp["data"]["message"]["kind"] == send_channel
