"""대화방 답장(send_reply) — 양방향(8원) 우선 + 단방향(17원) fallback.

고객 MO 의 reply_id 가 있으면 RCS 양방향(send_rcs_chat, RPCSAXX001, 8원)으로
응답하고, reply_id 가 없거나 양방향 발송이 실패하면 단방향 RCS(dispatch_campaign)
로 fallback 한다. 어느 경우든 답장은 전달되며, 양방향 실패 시 미커밋 Campaign 은
폐기되어 dangling 캠페인이 남지 않는다.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import Campaign, Message, MoMessage
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import MsghubError, SendResponse, SendResultItem
from app.services.chat import send_reply

_CALLER = "0212345678"
_PHONE = "01099998888"


def _make_mo(db, *, reply_id, mo_key="mo-r1"):
    db.add(MoMessage(
        mo_key=mo_key, mo_number=_PHONE, mo_callback=_CALLER,
        mo_type="message", mo_msg="문의드려요", reply_id=reply_id,
        mo_recv_dt="2026-05-30T12:00:00+00:00", raw_payload="{}",
        received_at="2026-05-30T12:00:00+00:00",
    ))
    db.commit()


class _ReplySpyClient:
    """send_rcs_chat(양방향) / send_rcs(단방향 fallback) 호출 기록."""

    def __init__(self, chat_fails=False):
        self.chat_calls = 0
        self.rcs_calls = 0
        self._chat_fails = chat_fails

    async def send_rcs_chat(self, *, description, phone, cli_key, reply_id="", **kw):
        self.chat_calls += 1
        if self._chat_fails:
            raise MsghubError("[29003] 양방향 응답 실패", code="29003")
        # 양방향 응답 data 에는 phone 이 없다(cliKey/msgKey/replyId 만).
        return SendResponse(
            code="10000", message="OK",
            items=[SendResultItem(cli_key=cli_key, msg_key="mk", phone="", code=SUCCESS_CODE, message="성공")],
        )

    async def send_rcs(self, **kw):
        self.rcs_calls += 1
        return SendResponse(
            code="10000", message="OK",
            items=[
                SendResultItem(cli_key=r.cli_key, msg_key="mk", phone=r.phone, code=SUCCESS_CODE, message="성공")
                for r in kw["recv_list"]
            ],
        )


def _campaign_count(db):
    return db.execute(select(func.count()).select_from(Campaign)).scalar()


@pytest.mark.asyncio
async def test_reply_uses_chat_when_reply_id_present(db_session, sample_user, sample_caller):
    """reply_id 있으면 양방향(send_rcs_chat, RPCSAXX001)으로 응답."""
    _make_mo(db_session, reply_id="rid-123")
    client = _ReplySpyClient()

    campaign = await send_reply(db_session, client, sample_user, _CALLER, _PHONE, "네 안내드릴게요")

    assert client.chat_calls == 1
    assert client.rcs_calls == 0
    assert campaign.rcs_messagebase_id == "RPCSAXX001"  # 양방향 CHAT
    # 아는 phone 으로 Message 생성됨
    msg = db_session.execute(
        select(Message).where(Message.campaign_id == campaign.id)
    ).scalar_one()
    assert msg.to_number == _PHONE


@pytest.mark.asyncio
async def test_reply_falls_back_to_oneway_without_reply_id(db_session, sample_user, sample_caller):
    """reply_id 없으면 단방향 RCS(dispatch_campaign)로 fallback."""
    client = _ReplySpyClient()  # MO 없음 → reply_id None

    campaign = await send_reply(db_session, client, sample_user, _CALLER, _PHONE, "안녕하세요")

    assert client.chat_calls == 0
    assert client.rcs_calls == 1
    assert campaign.rcs_messagebase_id == "RPSSAXX001"  # 단방향 SMS형


@pytest.mark.asyncio
async def test_reply_falls_back_when_chat_fails_no_dangling(db_session, sample_user, sample_caller):
    """양방향 발송 실패 → 단방향 fallback, dangling 캠페인 없음(미커밋 폐기)."""
    _make_mo(db_session, reply_id="rid-expired")
    client = _ReplySpyClient(chat_fails=True)

    campaign = await send_reply(db_session, client, sample_user, _CALLER, _PHONE, "안녕하세요")

    assert client.chat_calls == 1  # 양방향 시도
    assert client.rcs_calls == 1   # 단방향 fallback
    assert campaign.rcs_messagebase_id == "RPSSAXX001"  # 최종은 단방향
    # 캠페인은 fallback 1건만 — 양방향 실패분은 rollback 으로 폐기됨
    assert _campaign_count(db_session) == 1
