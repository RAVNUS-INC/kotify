"""수신번호 서버 정규화 — 숫자만 남긴 국내 번호로 dedupe·발송, 형식 오류는 400."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models import Campaign
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import SendResponse, SendResultItem
from app.routes.campaigns import (
    CampaignCreateBody,
    CampaignPreviewBody,
    create_campaign,
    preview_campaign,
)
from app.services.compose import InvalidRecipients, dispatch_campaign
from app.util.phone import normalize_recipient


@pytest.mark.parametrize("raw, expected", [
    ("010-1234-5678", "01012345678"),
    (" 010 1234 5678 ", "01012345678"),
    ("+82-10-1234-5678", "01012345678"),
    ("02-123-4567", "021234567"),
    ("031-1234-5678", "03112345678"),
    ("+82 2 1234 5678", "0212345678"),
    ("1588-1234", "15881234"),
    ("0505-1234-5678", "050512345678"),  # 050 안심번호 12자리 (M6)
    ("0507 123 45678", "050712345678"),
    ("홍길동", None),
    ("+1 415 555 0100", None),
    ("0101234", None),
    ("0101234567890123456789", None),
    ("", None),
])
def test_normalize_recipient(raw, expected):
    assert normalize_recipient(raw) == expected


class _SmsClient:
    def __init__(self):
        self.phones: list[str] = []

    async def send_sms(self, *, callback, msg, recv_list, resv_yn=None, resv_req_dt=None):
        self.phones += [r.phone for r in recv_list]
        return SendResponse(code="10000", message="OK", items=[
            SendResultItem(cli_key=r.cli_key, msg_key="mk", phone=r.phone, code=SUCCESS_CODE, message="성공")
            for r in recv_list
        ])


async def _dispatch(db, user, caller, client, recipients):
    return await dispatch_campaign(
        db=db, msghub_client=client, created_by=user.sub, caller_number=caller.number,
        content="안내", recipients=recipients, message_type="SMS", send_channel="sms",
    )


@pytest.mark.asyncio
async def test_dispatch_normalizes_and_dedupes(db_session, sample_user, sample_caller):
    """예전엔 입력 문자열 기준이라 하이픈 유무가 다른 같은 번호가 두 번 발송·과금됐다."""
    client = _SmsClient()
    campaign = await _dispatch(
        db_session, sample_user, sample_caller, client,
        ["010-1234-5678", "01012345678", "+82 10 1234 5678", "02-123-4567"],
    )
    assert client.phones == ["01012345678", "021234567"]
    assert campaign.total_count == 2


@pytest.mark.asyncio
async def test_dispatch_rejects_invalid_before_creating_campaign(db_session, sample_user, sample_caller):
    client = _SmsClient()
    with pytest.raises(InvalidRecipients) as info:
        await _dispatch(db_session, sample_user, sample_caller, client, ["01012345678", "홍길동", "12345"])
    assert info.value.invalid == ["홍길동", "12345"]
    assert client.phones == []
    assert db_session.scalar(select(func.count()).select_from(Campaign)) == 0


@pytest.mark.asyncio
async def test_create_route_returns_400_with_invalid_values(db_session, sample_user, sample_caller, monkeypatch):
    monkeypatch.setattr("app.main.get_msghub_client", lambda: _SmsClient())
    request = MagicMock()
    request.headers = {}
    body = CampaignCreateBody(
        sender=sample_caller.number, recipients=["01012345678", "김철수"], message="안내", sendChannel="sms",
    )
    with pytest.raises(HTTPException) as info:
        await create_campaign(body, request, sample_user, db_session)
    assert info.value.status_code == 400
    assert info.value.detail["code"] == "invalid_recipients"
    assert "김철수" in info.value.detail["message"]
    assert info.value.detail["fields"] == {"recipients": "김철수"}


def test_preview_reports_invalid_and_counts_normalized():
    data = preview_campaign(CampaignPreviewBody(
        message="안내", recipients=["010-1234-5678", "01012345678"], sendChannel="sms",
    ))["data"]
    assert (data["recipientCount"], data["valid"], data["costMin"]) == (1, True, 9)

    data = preview_campaign(CampaignPreviewBody(
        message="안내", recipients=["01012345678", "이름만"], sendChannel="sms",
    ))["data"]
    assert data["valid"] is False
    assert "이름만" in data["error"]


@pytest.mark.asyncio
async def test_chat_reply_to_stored_number_is_not_format_blocked(db_session, sample_user, sample_caller):
    """대화방 답장은 저장된 번호라 형식 검사로 막지 않는다(M6) — 숫자만 남겨 보낸다."""
    client = _SmsClient()
    campaign = await dispatch_campaign(
        db=db_session, msghub_client=client, created_by=sample_user.sub, caller_number=sample_caller.number,
        content="안내", recipients=["0303-1234-56789"], message_type="SMS", send_channel="sms",
        validate_recipients=False,
    )
    assert client.phones == ["0303123456789"]
    assert campaign.total_count == 1


@pytest.mark.asyncio
async def test_cancel_auth_error_message_hides_details(db_session, sample_user, sample_caller, monkeypatch):
    """토큰 발급 실패(AuthError) 문구엔 httpx 예외 내용이 섞일 수 있어 응답에 싣지 않는다."""
    from app.msghub.auth import AuthError
    from app.routes.campaigns import cancel_campaign
    from tests.test_reservation_chunks import _dispatch, _reserve_at, _ReservingMsghub

    client = _ReservingMsghub()
    campaign = await _dispatch(
        db_session, client, sample_user, sample_caller, reserve_time_local=_reserve_at(), send_channel="rcs",
    )

    async def _fail(web_req_id, reason=""):
        raise AuthError("NETWORK_ERROR", "msghub 인증 서버 연결 실패: ConnectError 10.0.0.9:443 내부 주소")
    monkeypatch.setattr(client, "cancel_reservation", _fail)
    monkeypatch.setattr("app.main.get_msghub_client", lambda: client)

    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)
    body = json.loads(resp.body)
    assert resp.status_code == 502
    assert "10.0.0.9" not in body["error"]["message"]
    assert "msghub 인증 오류" in body["error"]["message"]


@pytest.mark.asyncio
async def test_upload_auth_error_message_hides_details(db_session, sample_user, monkeypatch):
    from io import BytesIO

    from starlette.datastructures import UploadFile

    from app.msghub.auth import AuthError
    from app.routes.campaigns import upload_attachment

    class _Client:
        async def upload_file(self, **kwargs):
            raise AuthError("NETWORK_ERROR", "연결 실패: ConnectError 10.0.0.9:443")

    monkeypatch.setattr("app.main.get_msghub_client", lambda: _Client())
    monkeypatch.setattr("app.routes.campaigns.preprocess_mms_image", lambda raw: (b"jpeg", 100, 100))
    resp = await upload_attachment(
        file=UploadFile(filename="a.png", file=BytesIO(b"raw")), user=sample_user, db=db_session,
    )
    body = json.loads(resp.body)
    assert resp.status_code == 502
    assert "10.0.0.9" not in body["error"]["message"]
