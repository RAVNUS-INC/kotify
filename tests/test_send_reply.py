"""대화방 답장(send_reply) — 전송 방식(send_channel)별 경로.

rcs: 24h 세션 안의 고객 MO reply_id 가 있으면 RCS 양방향(send_rcs_chat, RPCSAXX001,
8원)으로 응답하고, reply_id 가 없거나 세션이 지났거나 양방향 발송이 실패하면 단방향
RCS(dispatch_campaign)로 fallback 한다. 어느 경우든 답장은 전달되며, 양방향 실패 시
미커밋 Campaign 은 폐기되어 dangling 캠페인이 남지 않는다.
sms(일반): RCS 없이 직접 SMS 로 보낸다.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models import Campaign, Message, MoMessage
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import MsghubError, SendResponse, SendResultItem
from app.services.chat import send_reply
from app.util.time import KST

_CALLER = "0212345678"
_PHONE = "01099998888"


def _ago(**delta) -> datetime:
    return datetime.now(UTC) - timedelta(**delta)


def _make_mo(db, *, reply_id, mo_key="mo-r1", recv_dt=None, received_at=None):
    """고객 MO 1건. recv_dt 미지정 시 방금 받은 MO(세션 안)."""
    recv_dt = recv_dt or _ago(minutes=5).isoformat()
    db.add(MoMessage(
        mo_key=mo_key, mo_number=_PHONE, mo_callback=_CALLER,
        mo_type="message", mo_msg="문의드려요", reply_id=reply_id,
        mo_recv_dt=recv_dt, raw_payload="{}",
        received_at=received_at or recv_dt,
    ))
    db.commit()


class _ReplySpyClient:
    """send_rcs_chat(양방향) / send_rcs(단방향) / send_sms(일반) 호출 기록."""

    def __init__(self, chat_fails=False):
        self.chat_calls = 0
        self.rcs_calls = 0
        self.sms_calls = 0
        self.chat_reply_ids: list[str] = []
        self._chat_fails = chat_fails

    async def send_rcs_chat(self, *, description, phone, cli_key, reply_id="", **kw):
        self.chat_calls += 1
        self.chat_reply_ids.append(reply_id)
        if self._chat_fails:
            raise MsghubError("[29003] 양방향 응답 실패", code="29003")
        # 양방향 응답 data 에는 phone 이 없다(cliKey/msgKey/replyId 만).
        return SendResponse(
            code="10000", message="OK",
            items=[SendResultItem(cli_key=cli_key, msg_key="mk", phone="", code=SUCCESS_CODE, message="성공")],
        )

    async def send_rcs(self, **kw):
        self.rcs_calls += 1
        return _ok(kw["recv_list"])

    async def send_sms(self, *, callback, msg, recv_list, resv_yn=None, resv_req_dt=None):
        self.sms_calls += 1
        return _ok(recv_list)


def _ok(recv_list):
    return SendResponse(
        code="10000", message="OK",
        items=[
            SendResultItem(cli_key=r.cli_key, msg_key="mk", phone=r.phone, code=SUCCESS_CODE, message="성공")
            for r in recv_list
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


@pytest.mark.asyncio
async def test_reply_skips_chat_when_session_expired(db_session, sample_user, sample_caller):
    """마지막 MO 가 24h 세션 밖이면 오래된 reply_id 로 양방향을 시도하지 않고 바로 단방향 RCS.

    회귀: 며칠 전 MO 의 replyId 로 양방향을 보내면 리포트 단계 실패 시 webhook 이 단방향 RCS
    를 건너뛰고 일반 SMS 로 대체 발송해, RCS 로 대화하던 번호가 며칠 뒤 SMS 로 바뀌었다.
    """
    _make_mo(db_session, reply_id="rid-stale", recv_dt=_ago(hours=25).isoformat())
    client = _ReplySpyClient()

    campaign = await send_reply(db_session, client, sample_user, _CALLER, _PHONE, "안녕하세요")

    assert client.chat_calls == 0
    assert client.rcs_calls == 1
    assert client.sms_calls == 0
    assert campaign.rcs_messagebase_id == "RPSSAXX001"


@pytest.mark.asyncio
async def test_reply_session_uses_msghub_native_kst_timestamp(db_session, sample_user, sample_caller):
    """msghub moRecvDt(오프셋 없는 KST) 도 세션 판정에 쓰인다 — 1시간 전 MO 는 세션 안."""
    native_kst = _ago(hours=1).astimezone(KST).strftime("%Y%m%d%H%M%S")
    _make_mo(db_session, reply_id="rid-native", recv_dt=native_kst)
    client = _ReplySpyClient()

    await send_reply(db_session, client, sample_user, _CALLER, _PHONE, "네 확인했습니다")

    assert client.chat_reply_ids == ["rid-native"]


@pytest.mark.asyncio
async def test_reply_picks_latest_mo_by_time_not_string_order(db_session, sample_user, sample_caller):
    """포맷이 섞여도 실제 시각이 가장 최근인 MO 의 reply_id 를 쓴다.

    문자열 내림차순이면 '20260915…'(네이티브) 가 '2026-09-15T…'(ISO) 보다 커서 더 오래된
    네이티브 MO 를 골랐을 케이스.
    """
    older_native = _ago(hours=2).astimezone(KST).strftime("%Y%m%d%H%M%S")
    _make_mo(db_session, reply_id="rid-older", mo_key="mo-old", recv_dt=older_native)
    _make_mo(db_session, reply_id="rid-newer", mo_key="mo-new", recv_dt=_ago(hours=1).isoformat())
    client = _ReplySpyClient()

    await send_reply(db_session, client, sample_user, _CALLER, _PHONE, "네 확인했습니다")

    assert client.chat_reply_ids == ["rid-newer"]


@pytest.mark.asyncio
async def test_reply_sms_channel_sends_direct_sms(db_session, sample_user, sample_caller):
    """일반(sms) 선택 시 세션 안 reply_id 가 있어도 RCS 없이 직접 SMS 로 보낸다."""
    _make_mo(db_session, reply_id="rid-123")
    client = _ReplySpyClient()

    campaign = await send_reply(
        db_session, client, sample_user, _CALLER, _PHONE, "안녕하세요", send_channel="sms"
    )

    assert client.chat_calls == 0
    assert client.rcs_calls == 0
    assert client.sms_calls == 1
    assert campaign.rcs_messagebase_id is None  # 일반 모드는 RCS messagebase 없음


@pytest.mark.asyncio
async def test_reply_rejects_unknown_send_channel(db_session, sample_user, sample_caller):
    """알 수 없는 전송 방식은 발송 전에 거부한다(RCS 로 조용히 보내지 않음)."""
    client = _ReplySpyClient()

    with pytest.raises(ValueError, match="전송 방식"):
        await send_reply(
            db_session, client, sample_user, _CALLER, _PHONE, "안녕하세요", send_channel="kakao"
        )

    assert client.chat_calls == client.rcs_calls == client.sms_calls == 0
    assert _campaign_count(db_session) == 0
