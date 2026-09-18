"""전송 방식 선택(send_channel) 라우팅 테스트.

send_channel="rcs" → RCS 우선(send_rcs), "sms" → 일반 직접(send_sms/send_mms).
하위 유형(short/long/image)은 content·첨부로 자동 분류된다.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.models import Attachment, Message
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import SendResponse, SendResultItem
from app.services.compose import dispatch_campaign


def _ok(recv_list):
    return SendResponse(
        code="10000", message="OK",
        items=[
            SendResultItem(
                cli_key=r.cli_key, msg_key=f"mk-{r.cli_key}",
                phone=r.phone, code=SUCCESS_CODE, message="성공",
            )
            for r in recv_list
        ],
    )


class _ChannelSpyClient:
    """어떤 발송 메서드가 호출됐는지 기록하는 테스트 클라이언트."""

    def __init__(self):
        self.rcs_calls = 0
        self.sms_calls = 0
        self.mms_calls = 0
        self.last_rcs = None
        self.last_mms = None

    async def send_rcs(self, **kw):
        self.rcs_calls += 1
        self.last_rcs = kw
        return _ok(kw["recv_list"])

    async def send_sms(self, *, callback, msg, recv_list, resv_yn=None, resv_req_dt=None):
        self.sms_calls += 1
        return _ok(recv_list)

    async def send_mms(
        self, *, callback, title, msg, recv_list,
        file_id_lst=None, resv_yn=None, resv_req_dt=None,
    ):
        self.mms_calls += 1
        self.last_mms = {
            "file_id_lst": file_id_lst, "recv_list": recv_list,
        }
        return _ok(recv_list)


def _msg_count(db, campaign_id):
    return db.execute(
        select(func.count()).select_from(Message).where(Message.campaign_id == campaign_id)
    ).scalar()


def _attachment(db, user_sub, *, mms_expiry=None, rcs_expiry=None):
    now = datetime.now(UTC)
    att = Attachment(
        msghub_file_id="mms-file", msghub_rcs_file_id="rcs-file",
        original_filename="notice.jpg", stored_filename="notice.jpg",
        content_blob=b"jpeg", file_size_bytes=4, width=100, height=100,
        uploaded_by=user_sub, uploaded_at=now.isoformat(),
        file_expires_at=mms_expiry or (now + timedelta(days=10)).isoformat(),
        rcs_file_expires_at=rcs_expiry or (now + timedelta(days=10)).isoformat(),
        channel="mms+rcs",
    )
    db.add(att)
    db.commit()
    return att


@pytest.mark.asyncio
async def test_sms_channel_uses_direct_send(db_session, sample_user, sample_caller):
    """send_channel='sms' 단문 → send_sms 직접 발송, RCS 미사용."""
    client = _ChannelSpyClient()
    campaign = await dispatch_campaign(
        db=db_session, msghub_client=client,
        created_by=sample_user.sub, caller_number=sample_caller.number,
        content="안녕하세요", recipients=["01000000001", "01000000002"],
        message_type="SMS", send_channel="sms",
    )
    assert client.sms_calls == 1
    assert client.rcs_calls == 0
    assert campaign.rcs_messagebase_id is None  # 일반 모드는 RCS messagebase 없음
    assert campaign.state == "DISPATCHED"
    assert campaign.pending_count == 2
    assert _msg_count(db_session, campaign.id) == 2


@pytest.mark.asyncio
async def test_rcs_channel_uses_rcs_send(db_session, sample_user, sample_caller):
    """send_channel='rcs'(기본) 단문 → send_rcs(RPSSAXX001)."""
    client = _ChannelSpyClient()
    campaign = await dispatch_campaign(
        db=db_session, msghub_client=client,
        created_by=sample_user.sub, caller_number=sample_caller.number,
        content="안녕하세요", recipients=["01000000001"],
        message_type="SMS", send_channel="rcs",
    )
    assert client.rcs_calls == 1
    assert client.sms_calls == 0
    assert campaign.rcs_messagebase_id == "RPSSAXX001"


@pytest.mark.asyncio
async def test_sms_channel_long_uses_mms_endpoint(db_session, sample_user, sample_caller):
    """send_channel='sms' 장문(>90B) → send_mms(파일 없음 = LMS)."""
    client = _ChannelSpyClient()
    long_text = "가" * 60  # 충분히 긴 본문
    campaign = await dispatch_campaign(
        db=db_session, msghub_client=client,
        created_by=sample_user.sub, caller_number=sample_caller.number,
        content=long_text, recipients=["01000000001"],
        message_type="SMS", send_channel="sms",
    )
    assert client.mms_calls == 1
    assert client.sms_calls == 0
    assert client.rcs_calls == 0
    assert campaign.rcs_messagebase_id is None


@pytest.mark.asyncio
async def test_rcs_image_uses_channel_specific_file_ids(db_session, sample_user, sample_caller):
    """RCS 본문은 RCS ID, MMS fallback은 MMS ID만 사용한다."""
    attachment = _attachment(db_session, sample_user.sub)
    client = _ChannelSpyClient()
    await dispatch_campaign(
        db=db_session, msghub_client=client,
        created_by=sample_user.sub, caller_number=sample_caller.number,
        content="이미지 안내", recipients=["01000000001"], subject="안내",
        message_type="MMS", send_channel="rcs", attachment_id=attachment.id,
    )
    recv = client.last_rcs["recv_list"][0]
    fallback = client.last_rcs["fb_info_lst"][0]
    assert recv.merge_data["media"] == "maapfile://rcs-file"
    assert fallback.file_id_lst == ["mms-file"]


@pytest.mark.asyncio
async def test_attachment_expired_before_reserved_send_is_rejected(
    db_session, sample_user, sample_caller,
):
    """현재는 유효해도 예약 시각 전에 만료되는 파일은 접수하지 않는다."""
    now = datetime.now(UTC)
    attachment = _attachment(
        db_session, sample_user.sub,
        mms_expiry=(now + timedelta(days=1)).isoformat(),
        rcs_expiry=(now + timedelta(days=1)).isoformat(),
    )
    reserve_kst = (now + timedelta(days=2, hours=9)).strftime("%Y-%m-%d %H:%M")
    with pytest.raises(ValueError, match="발송 시각 전에 만료"):
        await dispatch_campaign(
            db=db_session, msghub_client=_ChannelSpyClient(),
            created_by=sample_user.sub, caller_number=sample_caller.number,
            content="이미지 안내", recipients=["01000000001"], subject="안내",
            message_type="MMS", send_channel="rcs", attachment_id=attachment.id,
            reserve_time_local=reserve_kst,
        )
