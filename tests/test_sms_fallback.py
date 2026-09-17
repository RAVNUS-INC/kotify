"""양방향 CHAT 답장 실패 → SMS 대체 발송(webhook._send_sms_fallback) 상태 전이.

양방향(RPCSAXX001) 리포트가 실패면 process_report 가 FB_PENDING 으로 넘기고, 웹훅이
cliKey 를 {원본}-fb 로 바꿔 SMS 를 보낸다. 행의 결과는 그 -fb SMS 의 리포트가 정한다.

- 재전송된 양방향 실패 리포트가 msgKey 로 FB_PENDING 행을 DONE·실패로 덮고, 뒤이은
  대체 SMS 성공 리포트는 DONE 이라 버려져 고객이 받은 답장이 영구 실패로 남던 문제.
- 대체 SMS 가 접수되지 않았는데(수신자 거부, 클라이언트 없음) FB_PENDING 으로 남아
  리포트도 재조정도 없이 영영 대기로 보이던 문제.
- 대체 SMS 요청 예외로 실패 확정한 뒤 실제 전달 리포트가 오면 집계만 성공이 되고 캠페인
  state 는 실패로 남아 대시보드·알림에 "일부 실패 · 1/1 성공" 으로 보이던 문제.
- 요청 응답보다 리포트가 먼저 와(대체 SMS·양방향 답장 트랜잭션 커밋 전) 그 리포트가 200 으로
  버려지던 문제 — 대체 SMS 리포트는 같은 번호에 미완료 메시지가 또 있을 때, 양방향 답장 리포트는 늘.
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db import Base, create_db_engine
from app.models import Caller, Campaign, Message, MsghubRequest, User
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import SendResponse, SendResultItem
from app.routes.notifications import list_notifications, mark_all_read
from app.routes.webhook import receive_report
from app.security.settings_store import SettingsStore
from app.services.compose import dispatch_chat_reply
from app.services.report import awaiting_record

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


def _make_chat_reply(db, msg_key="mk-chat", phone=_PHONE):
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
        to_number=phone, to_number_raw=phone, cli_key=cli_key, msg_key=msg_key,
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


def _sms_success(cli_key):
    return {
        "msgKey": "mk-sms", "cliKey": cli_key, "ch": "SMS", "resultCode": SUCCESS_CODE,
        "resultCodeDesc": "성공", "productCode": "SMS", "phone": _PHONE,
        "rptDt": "20260915100005",
    }


def _report_request(*items):
    request = MagicMock()
    request.json = AsyncMock(return_value={"rptCnt": len(items), "rptLst": list(items)})
    request.client = MagicMock()
    request.client.host = "10.0.0.1"
    return request


def _post_report(db, *items):
    return asyncio.run(receive_report("wtok", _report_request(*items), db))


def _message(db, campaign_id):
    return db.execute(
        select(Message).where(Message.campaign_id == campaign_id)
    ).scalar_one()


def test_redelivered_chat_failure_does_not_undo_sms_fallback(db_session, sample_user, monkeypatch):
    """양방향 실패 리포트가 재전송돼도 FB_PENDING 을 유지하고, 대체 SMS 성공 리포트로 전달 확정."""
    _setup_token(db_session)
    client = _SmsClient()
    monkeypatch.setattr("app.main.get_msghub_client", lambda: client)
    campaign, cli_key = _make_chat_reply(db_session)

    _post_report(db_session, _chat_failure(cli_key))
    # 웹훅 응답이 유실·지연돼 msghub 가 같은 실패 리포트를 다시 보낸다
    resp = _post_report(db_session, _chat_failure(cli_key))

    assert resp.status_code == 200
    msg = _message(db_session, campaign.id)
    assert (msg.status, msg.cli_key) == ("FB_PENDING", f"{cli_key}-fb")
    assert client.cli_keys == [f"{cli_key}-fb"]  # 재전송으로 SMS 를 또 보내지 않는다

    _post_report(db_session, _sms_success(f"{cli_key}-fb"))

    msg = _message(db_session, campaign.id)
    assert (msg.status, msg.result_code, msg.channel, msg.cost) == ("DONE", SUCCESS_CODE, "SMS", 9)
    campaign = db_session.get(Campaign, campaign.id)
    assert (campaign.ok_count, campaign.fail_count, campaign.pending_count) == (1, 0, 0)
    assert campaign.state == "COMPLETED"


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
    assert campaign.state == "FAILED"  # 1건 중 1건 실패 — "일부 실패 · 0/1 성공" 이 아니다


class _TimeoutSmsClient:
    """msghub 는 접수했지만 응답을 못 받은 경우 — send_sms 가 예외를 던진다."""

    async def send_sms(self, *, callback, msg, recv_list):
        raise httpx.ReadTimeout("응답 대기 시간 초과")


def test_sms_sent_despite_request_error_is_settled_by_its_report(db_session, sample_user, monkeypatch):
    """대체 SMS 요청이 예외라 FAILED 로 뒀어도 실제로 발송됐다면, 양방향 실패 리포트가 재전송된
    뒤에도 -fb 리포트로 전달 성공이 확정된다 — 판정 기준이 FB_PENDING 상태가 아니라 -fb 키인 이유."""
    _setup_token(db_session)
    monkeypatch.setattr("app.main.get_msghub_client", lambda: _TimeoutSmsClient())
    campaign, cli_key = _make_chat_reply(db_session)

    _post_report(db_session, _chat_failure(cli_key))
    assert _message(db_session, campaign.id).status == "FAILED"

    _post_report(db_session, _chat_failure(cli_key))  # 재전송
    _post_report(db_session, _sms_success(f"{cli_key}-fb"))

    msg = _message(db_session, campaign.id)
    assert (msg.status, msg.result_code, msg.channel) == ("DONE", SUCCESS_CODE, "SMS")
    campaign = db_session.get(Campaign, campaign.id)
    assert (campaign.ok_count, campaign.fail_count, campaign.pending_count) == (1, 0, 0)


def test_campaign_state_follows_late_sms_fallback_report(db_session, sample_user, monkeypatch):
    """요청 예외로 실패 확정한 답장이 -fb 리포트로 전달되면 캠페인도 COMPLETED 로 따라간다.

    처음 확정 시각(completed_at)은 그대로라, 실패 알림을 읽은 사용자에게 같은 알림이 새 알림으로
    다시 뜨지 않고 내용만 "발송 완료" 로 바뀐다 — 알림센터는 캠페인 state 의 파생 뷰다.
    """
    _setup_token(db_session)
    monkeypatch.setattr("app.main.get_msghub_client", lambda: _TimeoutSmsClient())
    campaign, cli_key = _make_chat_reply(db_session)

    _post_report(db_session, _chat_failure(cli_key))
    completed_at = db_session.get(Campaign, campaign.id).completed_at
    assert completed_at is not None
    mark_all_read(user=sample_user, db=db_session)  # 실패 알림을 읽었다

    _post_report(db_session, _sms_success(f"{cli_key}-fb"))

    campaign = db_session.get(Campaign, campaign.id)
    assert (campaign.ok_count, campaign.fail_count, campaign.pending_count) == (1, 0, 0)
    assert (campaign.state, campaign.completed_at) == ("COMPLETED", completed_at)
    notifs = list_notifications(kind="send_result", user=sample_user, db=db_session)["data"]
    [notif] = [n for n in notifs if n["id"] == f"campaign-{campaign.id}"]
    assert (notif["title"], notif["subtitle"]) == ("답장입니다 발송 완료", "1/1 도달")
    assert "unread" not in notif


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


# ── 요청 응답보다 먼저 온 리포트 (트랜잭션 커밋 전) ──────────────────────────────


def test_batch_with_report_before_record_still_applies_keyed_reports(db_session, sample_user, monkeypatch):
    """행 기록 전 리포트가 섞인 배치도 cliKey 리포트는 바로 반영하고 400 으로 배치째 재전송을 받는다 — 재전송된
    cliKey 리포트는 같은 행을 찾아 건너뛴다. 배치째 미루면 같은 배치의 양방향 실패 답장이 행 기록 때까지 대체 SMS 를
    못 보내고, 그사이 재조정이 먼저 확정하면 끝내 안 보낸다. cliKey 없는 리포트는 같이 미룬다 — phone 보조매칭은
    재전송 때 그새 생긴 같은 번호의 다른 미완료 메시지에 붙을 수 있다."""
    _setup_token(db_session)
    client = _SmsClient()
    monkeypatch.setattr("app.main.get_msghub_client", lambda: client)
    reply, reply_key = _make_chat_reply(db_session)
    phone_only, _ = _make_chat_reply(db_session, msg_key="mk-other", phone="01055556666")
    sending = Campaign(  # 청크 응답을 기다리는 중 — 행 기록 전
        created_by="test-sub-001", caller_number="0212345678", message_type="short", content="안내",
        total_count=1, pending_count=1, state="DISPATCHING", created_at="2026-09-15T01:00:00+00:00",
    )
    db_session.add(sending)
    db_session.commit()
    sending_key = f"c{sending.id}-0-0"
    batch = [
        _chat_failure(reply_key),
        {**_sms_success(sending_key), "msgKey": "mk-sending", "phone": "01077778888"},
        {**_sms_success(""), "msgKey": "", "phone": "01055556666"},
    ]

    with awaiting_record([sending.id]):
        resp = _post_report(db_session, *batch)

    assert (resp.status_code, json.loads(resp.body)) == (400, {"error": "report before record"})
    assert client.cli_keys == [f"{reply_key}-fb"]
    assert (_message(db_session, reply.id).status, _message(db_session, phone_only.id).status) == (
        "FB_PENDING", "REG",
    )

    req = MsghubRequest(campaign_id=sending.id, chunk_index=0, sent_at="2026-09-15T01:00:00+00:00")
    db_session.add(req)
    db_session.flush()
    db_session.add(Message(
        campaign_id=sending.id, msghub_request_id=req.id, to_number="01077778888",
        to_number_raw="01077778888", cli_key=sending_key, msg_key="mk-sending", status="REG",
    ))
    db_session.commit()

    assert _post_report(db_session, *batch).status_code == 200  # msghub 재전송

    assert client.cli_keys == [f"{reply_key}-fb"]  # 이미 반영한 실패 리포트는 대체 전 시도로 건너뛴다
    statuses = [_message(db_session, c.id).status for c in (reply, sending, phone_only)]
    assert statuses == ["FB_PENDING", "DONE", "DONE"]


@pytest.fixture
def file_db(tmp_path):
    """요청이 겹치는 경합용 파일 DB 세션을 여는 함수 — 운영(app.db)처럼 세션마다 연결이 따로라 커밋 전 변경이 서로
    보이지 않고 쓰기 잠금도 같다. 인메모리 DB 는 스레드의 연결 하나를 세션끼리 나눠 써 경합이 재현되지 않는다."""
    engine = create_db_engine(f"sqlite:///{tmp_path / 'kotify.db'}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    sessions = []

    def open_session():
        sessions.append(factory())
        return sessions[-1]

    now = datetime.now(UTC).isoformat()
    setup = open_session()
    setup.add(User(
        sub="test-sub-001", email="test@example.com", name="테스트 사용자",
        roles=json.dumps(["sender"]), created_at=now, last_login_at=now,
    ))
    setup.add(Caller(number="0212345678", label="대표번호", active=1, is_default=1, created_at=now))
    setup.commit()
    _setup_token(setup)
    yield open_session
    for session in sessions:
        session.close()
    engine.dispose()


class _SmsClientReportingFirst(_SmsClient):
    """msghub 가 대체 SMS 를 접수하고 요청 응답보다 그 SMS 리포트를 먼저 보낸다 — 응답을 기다리는 사이 다른 웹훅
    요청(during_send)이 그 리포트를 처리한다."""

    def __init__(self, during_send):
        super().__init__()
        self.during_send = during_send

    async def send_sms(self, *, callback, msg, recv_list):
        resp = await super().send_sms(callback=callback, msg=msg, recv_list=recv_list)
        await self.during_send(recv_list)
        return resp


def test_sms_report_before_fallback_commit_is_redelivered_not_lost(file_db, monkeypatch):
    """대체 SMS 리포트가 대체 발송 트랜잭션 커밋 전에 오면 그 웹훅은 원래 키 행만 본다. 전엔 phone 보조매칭에 기대
    같은 번호에 미완료 메시지가 또 있으면 매칭 실패·200 으로 버려져, 전달된 답장이 재조정 전까지 대기로 남았다.
    이제 400 으로 msghub 재전송을 받고 커밋 뒤 재전송된 리포트가 -fb 행을 확정한다."""
    webhook, concurrent = file_db(), file_db()
    campaign, cli_key = _make_chat_reply(webhook)
    other, _ = _make_chat_reply(webhook, msg_key="mk-chat-2")  # 같은 고객에게 이어 보낸 답장 — 리포트 대기
    responses = []

    async def report_meanwhile(recv_list):
        request = _report_request(*[_sms_success(r.cli_key) for r in recv_list])
        responses.append(await receive_report("wtok", request, concurrent))

    client = _SmsClientReportingFirst(report_meanwhile)
    monkeypatch.setattr("app.main.get_msghub_client", lambda: client)

    assert _post_report(webhook, _chat_failure(cli_key)).status_code == 200
    assert [(r.status_code, json.loads(r.body)) for r in responses] == [(400, {"error": "report before record"})]
    assert client.cli_keys == [f"{cli_key}-fb"]

    assert _post_report(concurrent, _sms_success(f"{cli_key}-fb")).status_code == 200  # msghub 재전송

    check = file_db()
    msg = _message(check, campaign.id)
    assert (msg.status, msg.result_code, msg.channel, msg.cost) == ("DONE", SUCCESS_CODE, "SMS", 9)
    assert check.get(Campaign, campaign.id).state == "COMPLETED"
    assert _message(check, other.id).status == "REG"


class _ChatClientReportingFirst(_SmsClient):
    """msghub 가 양방향 답장을 접수하고 요청 응답보다 그 리포트를 먼저 보낸다."""

    def __init__(self, during_send):
        super().__init__()
        self.during_send = during_send

    async def send_rcs_chat(self, *, description, phone, cli_key, reply_id=""):
        await self.during_send(cli_key)
        return SendResponse(code=SUCCESS_CODE, message="OK", items=[
            SendResultItem(cli_key=cli_key, msg_key="mk-chat", phone="", code=SUCCESS_CODE, message="성공"),
        ])


def test_chat_reply_report_before_commit_is_redelivered_and_falls_back(file_db, monkeypatch):
    """양방향 답장 요청 응답을 기다리는 사이(답장 행 커밋 전) 실패 리포트가 오면 전엔 매칭할 행이 없어 200 으로
    버려졌고, 답장은 리포트 대기로 남아 대체 SMS 도 나가지 않았다. 이제 400 으로 재전송을 받고, 커밋 뒤 재전송된
    실패 리포트로 대체 SMS 를 보낸다."""
    webhook = file_db()
    responses = []

    async def report_meanwhile(cli_key):
        responses.append(await receive_report("wtok", _report_request(_chat_failure(cli_key)), webhook))

    client = _ChatClientReportingFirst(report_meanwhile)
    monkeypatch.setattr("app.main.get_msghub_client", lambda: client)

    campaign = asyncio.run(dispatch_chat_reply(
        db=file_db(), msghub_client=client, created_by="test-sub-001", caller_number="0212345678",
        content="답장입니다", phone=_PHONE, reply_id="rid-1",
    ))
    cli_key = f"c{campaign.id}-0-0"

    assert [(r.status_code, json.loads(r.body)) for r in responses] == [(400, {"error": "report before record"})]
    assert _post_report(webhook, _chat_failure(cli_key)).status_code == 200  # msghub 재전송

    assert client.cli_keys == [f"{cli_key}-fb"]
    msg = _message(file_db(), campaign.id)
    assert (msg.status, msg.cli_key) == ("FB_PENDING", f"{cli_key}-fb")
