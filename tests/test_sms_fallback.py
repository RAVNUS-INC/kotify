"""양방향 CHAT 답장 실패 → SMS 대체 발송(webhook._send_sms_fallback) 상태 전이.

양방향(RPCSAXX001) 리포트가 실패면 process_report 가 FB_PENDING 으로 넘기고, 웹훅이
cliKey 를 {원본}-fb 로 바꿔 SMS 를 보낸다. 행의 결과는 그 -fb SMS 의 리포트가 정한다.

- 대체 SMS 가 접수되지 않았는데(수신자 거부, 클라이언트 없음) FB_PENDING 으로 남아
  리포트도 재조정도 없이 영영 대기로 보이던 문제.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select

from app.models import Campaign, Message, MsghubRequest
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import SendResponse, SendResultItem
from app.routes.webhook import receive_report
from app.security.settings_store import SettingsStore

_PHONE = "01099998888"


class _SmsClient:
    """send_sms 만 흉내내는 msghub 클라이언트 — 요청은 성공(최상위 10000), 수신자 결과는 지정."""

    def __init__(self, code=SUCCESS_CODE, message="성공"):
        self.cli_keys: list[str] = []
        self._code = code
        self._message = message

    async def send_sms(self, *, callback, msg, recv_list):
        self.cli_keys += [r.cli_key for r in recv_list]
        return SendResponse(code=SUCCESS_CODE, message="OK", items=[
            SendResultItem(
                cli_key=r.cli_key, msg_key="mk-sms", phone=r.phone,
                code=self._code, message=self._message,
            )
            for r in recv_list
        ])


def _setup_token(db):
    SettingsStore(db).set("msghub.webhook_token", "wtok", is_secret=True, updated_by="test")
    db.commit()


def _make_chat_reply(db):
    """dispatch_chat_reply 가 남기는 접수(REG) 상태의 양방향 답장 1건. (campaign, cliKey) 반환."""
    campaign = Campaign(
        created_by="test-sub-001", caller_number="0212345678", message_type="short",
        content="답장입니다", total_count=1, pending_count=1, state="DISPATCHED",
        created_at="2026-09-15T01:00:00+00:00", rcs_messagebase_id="RPCSAXX001",
    )
    db.add(campaign)
    db.flush()
    req = MsghubRequest(
        campaign_id=campaign.id, chunk_index=0, sent_at="2026-09-15T01:00:00+00:00",
    )
    db.add(req)
    db.flush()
    cli_key = f"c{campaign.id}-0-0"
    db.add(Message(
        campaign_id=campaign.id, msghub_request_id=req.id,
        to_number=_PHONE, to_number_raw=_PHONE, cli_key=cli_key, msg_key="mk-chat",
        status="REG", result_code=SUCCESS_CODE, result_desc="성공",
    ))
    db.commit()
    return campaign, cli_key


def _chat_failure(cli_key):
    return {
        "msgKey": "mk-chat", "cliKey": cli_key, "ch": "RCS", "resultCode": "51004",
        "resultCodeDesc": "RCS 미지원 단말", "productCode": "CHAT", "phone": _PHONE,
        "rptDt": "20260915100001",
    }


def _post_report(db, *items):
    request = MagicMock()
    request.json = AsyncMock(return_value={"rptCnt": len(items), "rptLst": list(items)})
    request.client = MagicMock()
    request.client.host = "10.0.0.1"
    return asyncio.run(receive_report("wtok", request, db))


def _message(db, campaign_id):
    return db.execute(
        select(Message).where(Message.campaign_id == campaign_id)
    ).scalar_one()


def test_rejected_sms_fallback_is_failed_not_pending(db_session, sample_user, monkeypatch):
    """대체 SMS 가 수신자 단위로 거부되면(31101) 리포트가 오지 않으므로 사유와 함께 FAILED."""
    _setup_token(db_session)
    client = _SmsClient(code="31101", message="수신번호 에러")
    monkeypatch.setattr("app.main.get_msghub_client", lambda: client)
    campaign, cli_key = _make_chat_reply(db_session)

    resp = _post_report(db_session, _chat_failure(cli_key))

    assert resp.status_code == 200
    assert json.loads(resp.body)["fallback"] == 0  # 접수 0건
    msg = _message(db_session, campaign.id)
    assert (msg.status, msg.result_code) == ("FAILED", "31101")
    assert msg.result_desc == "수신번호 에러 (SMS fallback 거부)"
    # FB_PENDING(대기)으로 집계된 캠페인도 실패로 다시 집계돼 발송 중에 머물지 않는다
    campaign = db_session.get(Campaign, campaign.id)
    assert (campaign.ok_count, campaign.fail_count, campaign.pending_count) == (0, 1, 0)
    assert campaign.state == "PARTIAL_FAILED"


def test_sms_fallback_without_client_is_failed_not_pending(db_session, sample_user, monkeypatch):
    """msghub 클라이언트가 없으면 대체 SMS 를 못 보내므로 FB_PENDING 으로 남기지 않고 FAILED."""
    _setup_token(db_session)
    monkeypatch.setattr("app.main.get_msghub_client", lambda: None)
    campaign, cli_key = _make_chat_reply(db_session)

    resp = _post_report(db_session, _chat_failure(cli_key))

    assert resp.status_code == 200
    msg = _message(db_session, campaign.id)
    assert (msg.status, msg.result_code) == ("FAILED", "51004")
    assert msg.result_desc == "RCS 미지원 단말 (SMS fallback 실패)"
    campaign = db_session.get(Campaign, campaign.id)
    assert (campaign.fail_count, campaign.pending_count) == (1, 0)
