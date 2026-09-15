"""양방향 답장 리포트 실패 → webhook 대체 발송 (receive_report + dispatch_chat_fallback).

대화방에서 RCS 로 고른 답장이 양방향(CHAT)으로 접수된 뒤 리포트에서 실패하면, 일반 SMS 가
아니라 즉시 실패 경로와 같은 단방향 RCS(RPSSAXX001 + fbInfoLst SMS, cliKey "-rcs-fb")로
다시 보낸다. RCS 요청이 거부되면 직접 SMS("-fb")로 보낸다. 웹훅은 리포트 처리와 대체 발송을
한 트랜잭션으로 커밋해, 커밋이 실패해 msghub 가 리포트를 재전송해도 이중 발송하지 않는다.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.models import Campaign, Message
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import (
    FbInfo,
    MsghubBadRequest,
    MsghubRateLimited,
    MsghubServerError,
    SendResponse,
    SendResultItem,
)
from app.routes.campaigns import _message_to_recipient
from app.routes.threads import api_get_thread
from app.routes.webhook import receive_report
from app.security.settings_store import SettingsStore
from app.services.compose import dispatch_chat_reply

_CALLER = "0212345678"
_PHONE = "01099998888"
_CONTENT = "네 안내드릴게요"


class _FallbackClient:
    """양방향 답장(send_rcs_chat)은 접수하고, 대체 발송 요청(send_rcs/send_sms)을 기록한다.

    rcs/sms: None 이면 접수 성공, 예외 인스턴스면 raise, 문자열이면 HTTP 200 + 그 item 코드.
    msgKey 는 msghub 처럼 발송마다 다르게 준다(cliKey 에서 파생).
    """

    def __init__(self, *, rcs=None, sms=None):
        self.rcs = rcs
        self.sms = sms
        self.rcs_requests: list[dict] = []
        self.sms_requests: list[dict] = []

    async def send_rcs_chat(self, *, description, phone, cli_key, reply_id="", **kw):
        return SendResponse(
            code=SUCCESS_CODE, message="OK",
            items=[SendResultItem(cli_key=cli_key, msg_key=f"mk-{cli_key}", phone="", code=SUCCESS_CODE, message="성공")],
        )

    async def send_rcs(self, **kw):
        self.rcs_requests.append(kw)
        return _outcome(self.rcs, kw["recv_list"])

    async def send_sms(self, *, callback, msg, recv_list, **kw):
        self.sms_requests.append({"callback": callback, "msg": msg, "recv_list": recv_list})
        return _outcome(self.sms, recv_list)


def _outcome(spec, recv_list):
    if isinstance(spec, Exception):
        raise spec
    code = spec or SUCCESS_CODE
    return SendResponse(
        code=SUCCESS_CODE, message="OK",
        items=[
            SendResultItem(cli_key=r.cli_key, msg_key=f"mk-{r.cli_key}", phone=r.phone, code=code, message="결과")
            for r in recv_list
        ],
    )


@pytest.fixture
def client(db_session, sample_user, sample_caller, monkeypatch):
    SettingsStore(db_session).set("msghub.webhook_token", "wtok", is_secret=True, updated_by="test")
    db_session.commit()
    fake = _FallbackClient()
    monkeypatch.setattr("app.main.get_msghub_client", lambda: fake)
    return fake


async def _chat_reply(db, client) -> Campaign:
    """양방향으로 접수된 대화방 답장 1건 (Campaign RPCSAXX001 + Message REG)."""
    return await dispatch_chat_reply(
        db=db, msghub_client=client, created_by="test-sub-001",
        caller_number=_CALLER, content=_CONTENT, phone=_PHONE, reply_id="rid-1",
    )


def _message(db, campaign) -> Message:
    return db.execute(select(Message).where(Message.campaign_id == campaign.id)).scalar_one()


async def _report(db, cli_key, *, code, product="CHAT", desc="결과"):
    """cli_key 발송의 리포트 1건을 웹훅으로 받는다 (msgKey 는 그 발송의 것)."""
    item = {
        "isBi": product == "CHAT", "msgKey": f"mk-{cli_key}", "cliKey": cli_key, "ch": "RCS",
        "resultCode": code, "resultCodeDesc": desc, "productCode": product,
        "phone": _PHONE, "rptDt": "2026-09-15T10:00:00",
    }
    request = MagicMock()
    request.json = AsyncMock(return_value={"rptCnt": 1, "rptLst": [item]})
    request.client = MagicMock(host="10.0.0.1")
    return await receive_report("wtok", request, db)


def _fail_next_commit(db, monkeypatch):
    """다음 커밋 1회를 실패시킨다 — 대체 발송이 접수된 뒤 DB 커밋이 깨진 상황."""
    real_commit = db.commit
    failures = iter([RuntimeError("database is locked")])

    def flaky_commit():
        err = next(failures, None)
        if err is not None:
            raise err
        real_commit()

    monkeypatch.setattr(db, "commit", flaky_commit)


def _kind(db) -> str:
    return api_get_thread(f"{_CALLER}:{_PHONE}", db=db)["data"]["messages"][-1]["kind"]


# ── 단방향 RCS 대체 발송 ──────────────────────────────────────────────────────


async def test_failed_chat_reply_is_resent_as_oneway_rcs(db_session, client):
    """양방향 리포트 실패 → SMS 가 아니라 단방향 RCS(+fbInfoLst SMS)로 다시 보낸다."""
    campaign = await _chat_reply(db_session, client)
    key = _message(db_session, campaign).cli_key

    resp = await _report(db_session, key, code="55715")  # replyId 없음

    assert resp.status_code == 200
    assert b'"fallback":1' in resp.body
    assert client.sms_requests == []
    [req] = client.rcs_requests
    assert req["messagebase_id"] == "RPSSAXX001"
    assert req["callback"] == _CALLER
    [recv] = req["recv_list"]
    assert (recv.cli_key, recv.phone) == (f"{key}-rcs-fb", _PHONE)
    assert recv.merge_data == {"description": _CONTENT}
    assert req["fb_info_lst"] == [FbInfo(ch="SMS", msg=_CONTENT)]

    msg = _message(db_session, campaign)
    assert (msg.status, msg.cli_key) == ("FB_PENDING", f"{key}-rcs-fb")
    # 대체 발송 리포트 대기 — 원본 실패로 캠페인을 마감하지 않는다
    assert (campaign.state, campaign.pending_count, campaign.fail_count) == ("DISPATCHED", 1, 0)
    # 리포트 전: 실패한 양방향 채널이 아니라 대체 발송 채널(RCS)로 표시
    assert _kind(db_session) == "rcs"


async def test_rcs_fallback_report_completes_reply(db_session, client):
    """대체 발송 리포트 성공 → 완료, 단방향 RCS 단가, 추가 발송 없음."""
    campaign = await _chat_reply(db_session, client)
    key = _message(db_session, campaign).cli_key
    await _report(db_session, key, code="55715")

    resp = await _report(db_session, f"{key}-rcs-fb", code=SUCCESS_CODE, product="SMS")

    assert resp.status_code == 200
    assert len(client.rcs_requests) == 1 and client.sms_requests == []
    msg = _message(db_session, campaign)
    assert (msg.status, msg.channel, msg.cost) == ("DONE", "RCS", 17)
    assert (campaign.state, campaign.rcs_count, campaign.total_cost) == ("COMPLETED", 1, 17)
    assert _kind(db_session) == "rcs"


async def test_failed_rcs_fallback_report_is_not_resent(db_session, client):
    """대체 발송("-rcs-fb")이 리포트에서 또 실패해도 다시 대체 발송하지 않는다(루프 방지)."""
    campaign = await _chat_reply(db_session, client)
    key = _message(db_session, campaign).cli_key
    await _report(db_session, key, code="55715")

    await _report(db_session, f"{key}-rcs-fb", code="59999", product="SMS")

    assert len(client.rcs_requests) == 1 and client.sms_requests == []
    msg = _message(db_session, campaign)
    assert (msg.status, msg.result_code) == ("DONE", "59999")
    assert (campaign.pending_count, campaign.fail_count) == (0, 1)


# ── RCS 요청 거부 → 직접 SMS ─────────────────────────────────────────────────


async def test_rejected_rcs_fallback_switches_to_direct_sms(db_session, client):
    """RCS 요청이 거부되면(MsghubBadRequest) _dispatch_rcs_chunks 처럼 직접 SMS("-fb")로 보낸다."""
    campaign = await _chat_reply(db_session, client)
    key = _message(db_session, campaign).cli_key
    client.rcs = MsghubBadRequest("[29003] 기타 오류", code="29003")

    resp = await _report(db_session, key, code="55715")

    assert b'"fallback":1' in resp.body
    assert len(client.rcs_requests) == 1  # RCS 를 먼저 시도했다가 거부됨
    [sms] = client.sms_requests
    assert (sms["callback"], sms["msg"]) == (_CALLER, _CONTENT)
    assert [(r.cli_key, r.phone) for r in sms["recv_list"]] == [(f"{key}-fb", _PHONE)]
    msg = _message(db_session, campaign)
    assert (msg.status, msg.cli_key) == ("FB_PENDING", f"{key}-fb")
    assert _kind(db_session) == "sms"


async def test_direct_sms_failure_marks_failed_and_settles_campaign(db_session, client):
    """RCS 거부 + 직접 SMS 도 실패 → FAILED. 리포트가 더 오지 않으므로 캠페인 집계를 마감한다."""
    campaign = await _chat_reply(db_session, client)
    key = _message(db_session, campaign).cli_key
    client.rcs = MsghubBadRequest("[29003] 기타 오류", code="29003")
    client.sms = MsghubServerError("[29012] 서버오류", code="29012")

    resp = await _report(db_session, key, code="55715")

    assert resp.status_code == 200 and b'"fallback":0' in resp.body
    msg = _message(db_session, campaign)
    assert (msg.status, msg.cli_key) == ("FAILED", f"{key}-fb")
    assert "대체 발송 실패" in msg.result_desc and "29012" in msg.result_desc
    assert (campaign.pending_count, campaign.fail_count) == (0, 1)
    assert campaign.state != "DISPATCHED"


async def test_rcs_fallback_server_error_marks_failed_without_sms(db_session, client):
    """거부가 아닌 발송 오류는 접수 여부를 알 수 없어 직접 SMS 로 넘기지 않고 FAILED(이중 발송 방지)."""
    campaign = await _chat_reply(db_session, client)
    key = _message(db_session, campaign).cli_key
    client.rcs = MsghubServerError("HTTP 503 서버 오류", code="HTTP_ERROR")

    await _report(db_session, key, code="55715")

    assert client.sms_requests == []
    msg = _message(db_session, campaign)
    assert (msg.status, msg.cli_key) == ("FAILED", f"{key}-rcs-fb")
    assert (campaign.pending_count, campaign.fail_count) == (0, 1)


async def test_item_level_rejection_marks_failed(db_session, client):
    """HTTP 200 이어도 수신자(item) 코드가 실패면 FAILED — 리포트가 오지 않아 영구 대기하지 않게 (H1).

    실패한 양방향 결과 설명은 남기고 대체 발송 오류를 덧붙인다.
    """
    campaign = await _chat_reply(db_session, client)
    key = _message(db_session, campaign).cli_key
    client.rcs = "29001"

    await _report(db_session, key, code="55715", desc="replyId 없음")

    msg = _message(db_session, campaign)
    assert (msg.status, msg.result_code) == ("FAILED", "29001")
    assert msg.result_desc.startswith("replyId 없음") and "29001" in msg.result_desc
    assert campaign.pending_count == 0


async def test_late_success_after_fallback_timeout_completes_campaign(db_session, client):
    """타임아웃이라 FAILED 로 둔 대체 발송이 실제론 접수돼 성공 리포트가 오면 캠페인도 완료로 고친다.

    FAILED 로 마감하면 PARTIAL_FAILED(대시보드 '실패')가 되는데, 늦은 성공으로 실패가 0건이 되면
    COMPLETED 로 보정한다.
    """
    campaign = await _chat_reply(db_session, client)
    key = _message(db_session, campaign).cli_key
    client.rcs = MsghubServerError("요청 타임아웃", code="HTTP_ERROR")
    await _report(db_session, key, code="55715")
    assert campaign.state == "PARTIAL_FAILED"

    await _report(db_session, f"{key}-rcs-fb", code=SUCCESS_CODE, product="SMS")

    msg = _message(db_session, campaign)
    assert (msg.status, msg.channel) == ("DONE", "RCS")
    assert (campaign.state, campaign.ok_count, campaign.fail_count) == ("COMPLETED", 1, 0)


# ── 재전송·중복·롤백 — msghub 는 400·응답 지연 시 리포트를 다시 보낸다 ────────────


async def test_redelivered_report_after_commit_failure_does_not_double_send(
    db_session, client, monkeypatch
):
    """RCS 대체 발송 접수 뒤 커밋이 실패하면 롤백·400 → msghub 가 리포트를 재전송한다.

    재처리 때 같은 cliKey 는 중복(29005)으로 거부되는데, 이미 접수된 것이므로 직접 SMS 로
    넘어가지 않고 FB_PENDING 으로 그 리포트를 기다린다.
    """
    campaign = await _chat_reply(db_session, client)
    key = _message(db_session, campaign).cli_key
    _fail_next_commit(db_session, monkeypatch)

    first = await _report(db_session, key, code="55715")

    assert first.status_code == 400
    msg = _message(db_session, campaign)
    assert (msg.status, msg.cli_key) == ("REG", key)  # 롤백 — 재전송 시 다시 매칭된다

    client.rcs = MsghubBadRequest("[29005] 중복발송 오류", code="29005")
    second = await _report(db_session, key, code="55715")

    assert second.status_code == 200
    assert len(client.rcs_requests) == 2 and client.sms_requests == []
    msg = _message(db_session, campaign)
    assert (msg.status, msg.cli_key) == ("FB_PENDING", f"{key}-rcs-fb")


async def test_duplicate_direct_fallback_waits_for_report(db_session, client):
    """RCS 거부 뒤 직접 SMS 가 중복(29005)이면 이미 접수된 것 — FAILED 가 아니라 리포트 대기."""
    campaign = await _chat_reply(db_session, client)
    key = _message(db_session, campaign).cli_key
    client.rcs = MsghubBadRequest("[29003] 기타 오류", code="29003")
    client.sms = MsghubBadRequest("[29005] 중복발송 오류", code="29005")

    resp = await _report(db_session, key, code="55715")

    assert b'"fallback":1' in resp.body
    msg = _message(db_session, campaign)
    assert (msg.status, msg.cli_key) == ("FB_PENDING", f"{key}-fb")


@pytest.mark.parametrize("rcs_outcome", [None, "29005"], ids=["accepted", "already-accepted"])
async def test_redelivered_original_report_keeps_fallback(db_session, client, rcs_outcome):
    """대체 발송을 커밋한 뒤 원본 실패 리포트가 다시 와도(웹훅 응답 지연 등) 대체 발송을 덮어쓰지 않는다.

    msgKey 가 대체 발송 것으로 바뀐 경우(accepted)와, item 중복 코드로 접수만 확인해 원본
    msgKey 가 남은 경우(already-accepted) 모두 원본 리포트는 건너뛰고 대체 발송 리포트로 완료된다.
    """
    campaign = await _chat_reply(db_session, client)
    key = _message(db_session, campaign).cli_key
    client.rcs = rcs_outcome
    await _report(db_session, key, code="55715")

    resp = await _report(db_session, key, code="55715")  # 같은 리포트 재전송

    assert resp.status_code == 200
    assert len(client.rcs_requests) == 1 and client.sms_requests == []
    msg = _message(db_session, campaign)
    assert (msg.status, msg.cli_key) == ("FB_PENDING", f"{key}-rcs-fb")

    await _report(db_session, f"{key}-rcs-fb", code=SUCCESS_CODE, product="SMS")
    assert (_message(db_session, campaign).status, campaign.state) == ("DONE", "COMPLETED")


async def test_stale_report_is_not_attributed_to_another_reply(db_session, client):
    """원본 리포트 재전송이 같은 번호로 새로 보낸 다른 답장에 붙지 않는다.

    cliKey 가 있는데 맞는 행이 없는 리포트는 phone 보조매칭을 하지 않는다 — 대기 중인 답장이
    1건뿐이면 그 답장이 원본 실패로 처리돼 엉뚱한 대체 발송이 나갔다.
    """
    first = await _chat_reply(db_session, client)
    key = _message(db_session, first).cli_key
    await _report(db_session, key, code="55715")
    await _report(db_session, f"{key}-rcs-fb", code=SUCCESS_CODE, product="SMS")
    second = await _chat_reply(db_session, client)  # 같은 번호로 새 답장 — 리포트 대기

    await _report(db_session, key, code="55715")  # 첫 답장 원본 리포트 재전송

    assert _message(db_session, second).status == "REG"
    assert len(client.rcs_requests) == 1


@pytest.mark.parametrize(
    ("fb_code", "state"),
    [(SUCCESS_CODE, "COMPLETED"), ("59999", "PARTIAL_FAILED")],
    ids=["delivered", "failed"],
)
async def test_fallback_report_in_rollback_gap_matches_original_row(
    db_session, client, monkeypatch, fb_code, state
):
    """대체 발송 접수 뒤 커밋이 롤백된 사이에 그 대체 발송 리포트가 먼저 와도 버리지 않는다.

    행은 아직 원본 키라 cliKey 가 안 맞고, 같은 번호에 대기 중인 답장이 또 있어 phone 매칭도
    안 된다. 원본 키 행에 반영하고 키를 대체 발송 키로 맞춰, 실패 리포트여도 다시 대체 발송하지
    않고 뒤이은 원본 리포트 재전송도 건너뛴다.
    """
    first = await _chat_reply(db_session, client)
    await _chat_reply(db_session, client)  # 같은 번호 대기 답장
    key = _message(db_session, first).cli_key
    _fail_next_commit(db_session, monkeypatch)
    assert (await _report(db_session, key, code="55715")).status_code == 400

    await _report(db_session, f"{key}-rcs-fb", code=fb_code, product="SMS")  # 대체 발송 리포트 먼저
    await _report(db_session, key, code="55715")  # 원본 리포트 재전송

    assert len(client.rcs_requests) == 1 and client.sms_requests == []
    msg = _message(db_session, first)
    assert (msg.status, msg.result_code, msg.cli_key) == ("DONE", fb_code, f"{key}-rcs-fb")
    assert first.state == state


@pytest.mark.parametrize(
    ("rcs", "sms", "final_key_suffix"),
    [
        (MsghubRateLimited("[29002] CPS 초과", code="29002"), None, "-rcs-fb"),
        (MsghubBadRequest("[29003] 기타 오류", code="29003"),
         MsghubRateLimited("[29002] CPS 초과", code="29002"), "-fb"),
    ],
    ids=["rcs-rate-limited", "direct-rate-limited"],
)
async def test_rate_limited_fallback_is_retried_by_redelivery(
    db_session, client, rcs, sms, final_key_suffix
):
    """29002(CPS 초과)는 요청 전체 거부라 접수 0 — FAILED 로 버리지 않고 롤백·400, 재전송 때 다시 보낸다."""
    campaign = await _chat_reply(db_session, client)
    key = _message(db_session, campaign).cli_key
    client.rcs, client.sms = rcs, sms

    first = await _report(db_session, key, code="55715")

    assert first.status_code == 400
    msg = _message(db_session, campaign)
    assert (msg.status, msg.cli_key) == ("REG", key)

    if isinstance(client.rcs, MsghubRateLimited):
        client.rcs = None
    client.sms = None
    second = await _report(db_session, key, code="55715")

    assert second.status_code == 200
    msg = _message(db_session, campaign)
    assert (msg.status, msg.cli_key) == ("FB_PENDING", f"{key}{final_key_suffix}")


async def test_missing_client_rolls_back_instead_of_stranding(db_session, client, monkeypatch):
    """msghub 클라이언트가 없으면 보낸 것 없이 FB_PENDING 으로 커밋하지 않고 400 — 재전송 때 다시 처리."""
    campaign = await _chat_reply(db_session, client)
    key = _message(db_session, campaign).cli_key
    monkeypatch.setattr("app.main.get_msghub_client", lambda: None)

    resp = await _report(db_session, key, code="55715")

    assert resp.status_code == 400
    msg = _message(db_session, campaign)
    assert (msg.status, msg.cli_key) == ("REG", key)


async def test_oneway_campaign_failure_is_not_resent(db_session, client):
    """단방향 RCS 캠페인 실패는 msghub 가 fbInfoLst 로 이미 대체 발송하므로 webhook 이 보내지 않는다."""
    campaign = await _chat_reply(db_session, client)
    campaign.rcs_messagebase_id = "RPSSAXX001"
    db_session.commit()
    key = _message(db_session, campaign).cli_key

    await _report(db_session, key, code="59999", product="SMS")

    assert client.rcs_requests == [] and client.sms_requests == []
    assert _message(db_session, campaign).status == "DONE"


# ── 캠페인 상세 수신자 상태 ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("cli_key", "status"),
    [
        ("c1-0-0-rcs-fb", "queued"),     # 단방향 RCS 로 다시 보내는 중 — SMS 대체 아님
        ("c1-0-0-fb", "fallback_sms"),   # 직접 SMS 대체 발송 대기
    ],
)
def test_pending_fallback_recipient_status(cli_key, status):
    m = Message(id=1, to_number=_PHONE, to_number_raw=_PHONE, status="FB_PENDING", cli_key=cli_key)
    assert _message_to_recipient(m)["status"] == status
