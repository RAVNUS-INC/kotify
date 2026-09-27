"""대화 메시지의 date — 날짜 구분선은 KST 달력 날짜로 나뉘어야 한다.

저장 시각은 UTC ISO(campaign.created_at·received_at)와 오프셋 없는 KST(moRecvDt)가 섞여
있다. UTC 날짜로 자르면 KST 00:00~08:59 메시지가 전날로 묶인다.
"""
from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.models import Campaign, Message, MoMessage, MsghubRequest
from app.routes.threads import MessageCreateBody, api_get_thread, api_post_message

_CALLER = "0212345678"
_PHONE = "01099998888"


def _reply(db, author: str, created_at: str, *, complete_time: str | None = None) -> None:
    """답장 1건. 리포트 전(REG)이면 표시 시각은 campaign.created_at(UTC ISO)로 보완되고,
    리포트 후(DONE)면 msghub 원본 rptDt(오프셋 없는 KST)가 complete_time 에 남는다."""
    campaign = Campaign(
        created_by=author, caller_number=_CALLER, message_type="short",
        content="확인해 드렸습니다", total_count=1, state="DISPATCHED", created_at=created_at,
    )
    db.add(campaign)
    db.flush()
    req = MsghubRequest(campaign_id=campaign.id, chunk_index=0, sent_at=created_at)
    db.add(req)
    db.flush()
    db.add(Message(
        campaign_id=campaign.id, msghub_request_id=req.id, to_number=_PHONE,
        to_number_raw=_PHONE, status="DONE" if complete_time else "REG",
        cli_key=f"c{campaign.id}-0-0", result_code="10000",
        complete_time=complete_time, report_dt=complete_time,
    ))
    db.commit()


def _inbound(db, key: str, *, mo_recv_dt: str | None, received_at: str) -> None:
    db.add(MoMessage(
        mo_key=key, mo_number=_PHONE, mo_callback=_CALLER, mo_msg=f"회신 {key}",
        raw_payload="{}", mo_recv_dt=mo_recv_dt, received_at=received_at,
    ))
    db.commit()


def _messages(db) -> list[dict]:
    return api_get_thread(f"{_CALLER}:{_PHONE}", db=db)["data"]["messages"]


def test_message_date_follows_kst_midnight_across_mixed_formats(db_session, sample_user):
    # moRecvDt 원본(오프셋 없는 KST) — KST 9/26 23:59.
    _inbound(db_session, "before-midnight", mo_recv_dt="2026-09-26T23:59:40",
             received_at="2026-09-26T14:59:41+00:00")
    # 리포트 전 답장 — UTC 로는 아직 9/26 이지만 KST 로는 9/27 00:00.
    _reply(db_session, sample_user.sub, "2026-09-26T15:00:30+00:00")
    # moRecvDt 가 없어 received_at(UTC) 로 보완된 회신 — KST 9/27 10:10.
    _inbound(db_session, "morning", mo_recv_dt=None, received_at="2026-09-27T01:10:00+00:00")
    # 전달된 답장 — rptDt 원본 KST 20:00. UTC 로 잘못 읽으면 9/28 05:00 이 된다.
    _reply(db_session, sample_user.sub, "2026-09-27T10:59:50+00:00",
           complete_time="2026-09-27T20:00:03")

    assert [(m["side"], m["time"], m["date"]) for m in _messages(db_session)] == [
        ("them", "23:59", "2026-09-26"),
        ("us", "00:00", "2026-09-27"),
        ("them", "10:10", "2026-09-27"),
        ("us", "20:00", "2026-09-27"),
    ]


def test_unparseable_timestamp_leaves_date_empty(db_session):
    # 해석할 수 없는 시각은 time 처럼 빈 문자열 — 화면은 구분선을 만들지 않는다.
    _inbound(db_session, "garbled", mo_recv_dt="확인불가", received_at="2026-09-27T01:10:00+00:00")

    [message] = _messages(db_session)
    assert (message["time"], message["date"]) == ("", "")


@pytest.mark.asyncio
async def test_reply_response_carries_kst_date(db_session, sample_user, monkeypatch):
    class _AfterKstMidnight(datetime):
        @classmethod
        def now(cls, tz=None):
            # UTC 9/26 15:30 = KST 9/27 00:30.
            return datetime(2026, 9, 26, 15, 30, tzinfo=UTC).astimezone(tz)

    async def fake_send(**_kwargs):
        return SimpleNamespace(id=7)

    monkeypatch.setattr("app.routes.threads.datetime", _AfterKstMidnight)
    monkeypatch.setattr("app.main.get_msghub_client", lambda: object())
    monkeypatch.setattr("app.services.chat.send_reply", fake_send)
    response = await api_post_message(
        f"{_CALLER}:{_PHONE}", MessageCreateBody(text="안내", sendChannel="sms"),
        user=sample_user, db=db_session,
    )

    message = response["data"]["message"]
    assert (message["time"], message["date"]) == ("00:30", "2026-09-27")
