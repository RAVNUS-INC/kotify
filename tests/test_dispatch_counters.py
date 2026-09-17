"""dispatch_campaign 카운터 정합성 테스트 — item 단위 실패 즉시 반영 (H1).

msghub 가 HTTP 200 으로 응답하면서 응답 본문 item 단위로 일부 수신자를 실패
처리하는 경우, 웹훅(배달 리포트) 도착 전에도 campaign.fail_count/pending_count
가 정확해야 한다. 기존에는 청크 전체 실패만 집계해 item 실패가 누락되어
fail_count=0 으로 오표시되었다.

청크 요청이 예외(응답 타임아웃 등)여도 msghub 는 실제로 접수했을 수 있다. 실패로 기록한
행에도 리포트가 오면 캠페인 state 가 그 결과를 따라야 한다. 행을 기록하기 전에 온 리포트는
웹훅이 400 으로 재전송을 받고, 재전송이 끝내 오지 않으면 재조정 조회가 대신한다.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from sqlalchemy import func, select, update

from app.models import Campaign, Message, MsghubRequest
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import (
    MsghubBadRequest,
    MsghubRateLimited,
    ReportItem,
    ReserveResponse,
    SendResponse,
    SendResultItem,
)
from app.routes.webhook import receive_report
from app.security.settings_store import SettingsStore
from app.services.compose import _create_messages_from_response, dispatch_campaign
from app.services.reconcile import reconcile_pending_messages
from app.services.report import ReportBeforeRecord, process_report


class _FakeRcsClient:
    """send_rcs 만 흉내내는 테스트 클라이언트 (덕 타이핑).

    fail_phones 에 든 번호는 item 단위 실패 코드(29002)로, 나머지는 성공(10000)
    으로 응답한다 — HTTP 200 부분 실패 시나리오를 재현한다.
    timeout_chunks 에 든 청크(0부터)는 msghub 가 접수했지만 응답을 못 받은 경우처럼
    예외를 던진다 — dispatch 는 청크 전체를 실패(_record_failed_chunk)로 기록한다.
    on_chunk(청크 번호)는 그 청크의 응답을 기다리는 사이 일어나는 일(웹훅 처리 등)을 흉내낸다.
    """

    def __init__(
        self,
        fail_phones: set[str] | None = None,
        timeout_chunks: set[int] | None = None,
        on_chunk: Callable[[int], None] | None = None,
    ):
        self.fail_phones = set(fail_phones or [])
        self.timeout_chunks = set(timeout_chunks or [])
        self.on_chunk = on_chunk
        self.send_calls = 0

    async def send_rcs(
        self, *, messagebase_id, callback, recv_list, fb_info_lst,
        resv_yn=None, resv_req_dt=None,
    ):
        chunk_idx = self.send_calls
        self.send_calls += 1
        if self.on_chunk is not None:
            self.on_chunk(chunk_idx)
        if chunk_idx in self.timeout_chunks:
            raise httpx.ReadTimeout("응답 대기 시간 초과")
        items = [
            SendResultItem(
                cli_key=recv.cli_key,
                msg_key=(f"mk-{recv.cli_key}" if recv.phone not in self.fail_phones else ""),
                phone=recv.phone,
                code=(SUCCESS_CODE if recv.phone not in self.fail_phones else "29002"),
                message=("성공" if recv.phone not in self.fail_phones else "수신거부 번호"),
            )
            for recv in recv_list
        ]
        return SendResponse(code="10000", message="OK", items=items)


def _status_counts(db, campaign_id) -> dict[str, int]:
    rows = db.execute(
        select(Message.status, func.count())
        .where(Message.campaign_id == campaign_id)
        .group_by(Message.status)
    ).all()
    return dict(rows)


# ── dispatch_campaign 통합 (H1) ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dispatch_item_failures_reflected_immediately(db_session, sample_user, sample_caller):
    """HTTP 200 응답 내 item 실패 2건이 dispatch 직후 fail_count/pending_count 에 반영."""
    recipients = ["01000000001", "01000000002", "01000000003", "01000000004"]
    client = _FakeRcsClient(fail_phones={"01000000002", "01000000004"})

    campaign = await dispatch_campaign(
        db=db_session,
        msghub_client=client,
        created_by=sample_user.sub,
        caller_number=sample_caller.number,
        content="안내 메시지입니다",
        recipients=recipients,
        message_type="SMS",
    )

    # 웹훅 도착 전인데도 item 실패 2건이 즉시 집계됨
    assert campaign.fail_count == 2
    assert campaign.pending_count == 2
    assert campaign.state == "PARTIAL_FAILED"

    counts = _status_counts(db_session, campaign.id)
    assert counts.get("FAILED") == 2
    assert counts.get("REG") == 2


@pytest.mark.asyncio
async def test_dispatch_all_success_pending_until_webhook(db_session, sample_user, sample_caller):
    """전건 접수 성공 → fail_count=0, 전건 pending(배달 리포트 대기), DISPATCHED."""
    recipients = ["01000000001", "01000000002", "01000000003"]
    client = _FakeRcsClient()  # 실패 없음

    campaign = await dispatch_campaign(
        db=db_session,
        msghub_client=client,
        created_by=sample_user.sub,
        caller_number=sample_caller.number,
        content="안내 메시지입니다",
        recipients=recipients,
        message_type="SMS",
    )

    assert campaign.fail_count == 0
    assert campaign.pending_count == 3
    assert campaign.state == "DISPATCHED"  # REG 는 아직 성공 아님 — pending


@pytest.mark.asyncio
async def test_dispatch_all_items_fail(db_session, sample_user, sample_caller):
    """전건 item 실패 → fail_count=전체, pending=0, FAILED."""
    recipients = ["01000000001", "01000000002"]
    client = _FakeRcsClient(fail_phones=set(recipients))

    campaign = await dispatch_campaign(
        db=db_session,
        msghub_client=client,
        created_by=sample_user.sub,
        caller_number=sample_caller.number,
        content="안내 메시지입니다",
        recipients=recipients,
        message_type="SMS",
    )

    assert campaign.fail_count == 2
    assert campaign.pending_count == 0
    assert campaign.state == "FAILED"


# ── 요청 예외로 실패 기록한 청크에 늦게 온 리포트 ─────────────────────────────


def _report(cli_key, phone, result_code=SUCCESS_CODE, ch="RCS"):
    return ReportItem(
        msg_key=f"mk-{cli_key}", cli_key=cli_key, ch=ch,
        result_code=result_code, result_code_desc="결과", product_code="SMS", phone=phone,
    )


@pytest.mark.asyncio
async def test_failed_dispatch_follows_late_reports(db_session, sample_user, sample_caller):
    """전건 요청 예외로 FAILED 인 캠페인도 리포트대로 따라간다 — 성공이 오면 PARTIAL_FAILED.

    전달 실패 리포트만 온 동안은 성공이 0 이라 FAILED 그대로다("일부 실패" 가 아니다).
    completed_at 은 발송 때 정해진 시각을 유지한다 — 새로 찍으면 읽은 "발송 실패" 알림이 다시 뜬다.
    """
    recipients = ["01000000001", "01000000002"]
    campaign = await dispatch_campaign(
        db=db_session,
        msghub_client=_FakeRcsClient(timeout_chunks={0}),
        created_by=sample_user.sub,
        caller_number=sample_caller.number,
        content="안내 메시지입니다",
        recipients=recipients,
        message_type="SMS",
    )
    assert (campaign.state, campaign.fail_count, campaign.pending_count) == ("FAILED", 2, 0)
    completed_at = campaign.completed_at
    assert completed_at is not None

    process_report(db_session, [_report(f"c{campaign.id}-0-0", recipients[0], result_code="51004")])
    assert (campaign.state, campaign.ok_count, campaign.fail_count) == ("FAILED", 0, 2)

    process_report(db_session, [_report(f"c{campaign.id}-0-1", recipients[1])])
    assert (campaign.state, campaign.ok_count, campaign.fail_count) == ("PARTIAL_FAILED", 1, 1)
    assert campaign.completed_at == completed_at


@pytest.mark.asyncio
async def test_reports_processed_between_chunks_survive_dispatch_result(
    db_session, sample_user, sample_caller,
):
    """앞 청크 리포트가 뒤 청크 응답을 기다리는 사이 처리되면, 발송 끝의 판정(발송 결과만 셈)이
    그 집계를 덮지 않는다 — 뒤이어 올 리포트가 없어 FAILED·집계 불일치(ok 10, fail 11)로 남았다."""
    recipients = [f"010000000{i:02d}" for i in range(11)]  # 청크 0: 10명, 청크 1: 1명 — 둘 다 요청 예외

    def webhook_meanwhile(chunk_idx):
        if chunk_idx == 1:  # msghub 는 청크 0 을 접수했다 — 그 리포트를 웹훅이 처리·커밋
            rows = db_session.execute(select(Message)).scalars().all()
            process_report(db_session, [_report(m.cli_key, m.to_number) for m in rows])
            db_session.commit()

    campaign = await dispatch_campaign(
        db=db_session,
        msghub_client=_FakeRcsClient(timeout_chunks={0, 1}, on_chunk=webhook_meanwhile),
        created_by=sample_user.sub,
        caller_number=sample_caller.number,
        content="안내 메시지입니다",
        recipients=recipients,
        message_type="SMS",
    )

    assert (campaign.ok_count, campaign.fail_count, campaign.pending_count) == (10, 1, 0)
    assert campaign.state == "PARTIAL_FAILED"
    assert campaign.completed_at is not None


class _RcsRejectedThenTimeoutClient:
    """RCS 요청이 거부돼 직접 SMS 로 다시 보냈는데, 그 요청을 msghub 는 접수했지만 응답을 못 받았다."""

    def __init__(self, rcs_error):
        self.rcs_error = rcs_error
        self.sms_cli_keys: list[str] = []

    async def send_rcs(self, **kwargs):
        raise self.rcs_error

    async def send_sms(self, *, callback, msg, recv_list, resv_yn=None, resv_req_dt=None):
        self.sms_cli_keys += [r.cli_key for r in recv_list]
        raise httpx.ReadTimeout("응답 대기 시간 초과")


@pytest.mark.asyncio
@pytest.mark.parametrize("rcs_error", [
    MsghubBadRequest("[29003] RCS 설정 오류", code="29003", status_code=400),
    MsghubRateLimited("[29002] CPS 초과", code="29002", status_code=400),
])
async def test_failed_direct_retry_is_settled_by_its_reports(
    db_session, sample_user, sample_caller, monkeypatch, rcs_error,
):
    """직접 재발송 요청이 예외라 실패로 기록한 행도 그 요청의 -fb cliKey 를 가져, 실제로 발송된
    SMS 의 리포트가 매칭되고 state 가 따라간다 — 원래 키로 기록하면 리포트가 어디에도 붙지 않았다."""
    async def _instant_sleep(_seconds):
        return None
    monkeypatch.setattr("app.services.compose.asyncio.sleep", _instant_sleep)  # 29002 백오프

    recipients = ["01000000001", "01000000002"]
    client = _RcsRejectedThenTimeoutClient(rcs_error)
    campaign = await dispatch_campaign(
        db=db_session,
        msghub_client=client,
        created_by=sample_user.sub,
        caller_number=sample_caller.number,
        content="안내 메시지입니다",
        recipients=recipients,
        message_type="SMS",
    )
    assert (campaign.state, campaign.fail_count) == ("FAILED", 2)

    process_report(db_session, [
        _report(key, phone, ch="SMS") for key, phone in zip(client.sms_cli_keys, recipients, strict=True)
    ])

    assert (campaign.state, campaign.ok_count, campaign.fail_count) == ("COMPLETED", 2, 0)


@pytest.mark.asyncio
async def test_partially_failed_dispatch_follows_reports(db_session, sample_user, sample_caller):
    """청크 일부가 요청 예외라 발송 때 PARTIAL_FAILED 로 정한 캠페인도 리포트로 결과가 다 정해지면
    완료 시각이 찍히고, 실패로 기록한 청크가 실제로 전달됐다는 리포트가 오면 COMPLETED 가 된다."""
    recipients = [f"010000000{i:02d}" for i in range(11)]  # 청크 0: 10명, 청크 1: 1명
    campaign = await dispatch_campaign(
        db=db_session,
        msghub_client=_FakeRcsClient(timeout_chunks={1}),
        created_by=sample_user.sub,
        caller_number=sample_caller.number,
        content="안내 메시지입니다",
        recipients=recipients,
        message_type="SMS",
    )
    assert (campaign.state, campaign.fail_count, campaign.pending_count) == ("PARTIAL_FAILED", 1, 10)

    process_report(db_session, [_report(f"c{campaign.id}-0-{i}", recipients[i]) for i in range(10)])
    assert (campaign.state, campaign.ok_count, campaign.pending_count) == ("PARTIAL_FAILED", 10, 0)
    completed_at = campaign.completed_at
    assert completed_at is not None

    process_report(db_session, [_report(f"c{campaign.id}-1-0", recipients[10])])
    assert (campaign.state, campaign.ok_count, campaign.fail_count) == ("COMPLETED", 11, 0)
    assert campaign.completed_at == completed_at


class _ReportingBeforeResponseClient(_FakeRcsClient):
    """msghub 가 청크를 접수하고 요청 응답보다 리포트를 먼저 보낸다 — 응답을 기다리는 사이 웹훅(during_send)이 온다."""

    def __init__(self, during_send):
        super().__init__()
        self.during_send = during_send

    async def send_rcs(self, *, recv_list, **kwargs):
        await self.during_send(recv_list)
        return await super().send_rcs(recv_list=recv_list, **kwargs)


async def _post_report(db, *items):
    request = MagicMock()
    request.json = AsyncMock(return_value={"rptCnt": len(items), "rptLst": list(items)})
    request.client = MagicMock()
    request.client.host = "10.0.0.1"
    return await receive_report("wtok", request, db)


def _delivered(cli_key, phone):
    return {
        "msgKey": f"mk-{cli_key}", "cliKey": cli_key, "ch": "RCS", "resultCode": SUCCESS_CODE,
        "resultCodeDesc": "성공", "productCode": "SMS", "phone": phone,
    }


@pytest.mark.asyncio
async def test_report_while_chunk_request_waits_is_redelivered_not_matched_by_phone(
    db_session, sample_user, sample_caller,
):
    """청크 요청 응답을 기다리는 사이(행 기록 전) 온 리포트는 400 으로 msghub 재전송을 받고, 행을 기록한 뒤 재전송되면
    제 행에 붙는다. 전엔 같은 번호의 다른 캠페인 미완료 메시지에 phone 으로 붙어(200) 그 메시지가 이 발송의 결과로
    확정되고, 이 발송의 행은 리포트를 영영 못 받았다."""
    SettingsStore(db_session).set("msghub.webhook_token", "wtok", is_secret=True, updated_by="test")
    db_session.commit()
    phone = "01000000001"
    earlier = await dispatch_campaign(
        db=db_session, msghub_client=_FakeRcsClient(), created_by=sample_user.sub,
        caller_number=sample_caller.number, content="먼저 보낸 안내", recipients=[phone], message_type="SMS",
    )
    responses = []

    async def webhook_meanwhile(recv_list):
        responses.append(await _post_report(db_session, *[_delivered(r.cli_key, r.phone) for r in recv_list]))

    campaign = await dispatch_campaign(
        db=db_session, msghub_client=_ReportingBeforeResponseClient(webhook_meanwhile), created_by=sample_user.sub,
        caller_number=sample_caller.number, content="안내 메시지입니다", recipients=[phone], message_type="SMS",
    )

    assert [(r.status_code, json.loads(r.body)) for r in responses] == [(400, {"error": "report before record"})]
    assert (campaign.state, campaign.pending_count) == ("DISPATCHED", 1)

    resp = await _post_report(db_session, _delivered(f"c{campaign.id}-0-0", phone))  # msghub 재전송

    assert resp.status_code == 200
    assert (campaign.state, campaign.ok_count, campaign.total_cost) == ("COMPLETED", 1, 17)
    assert (earlier.state, earlier.ok_count, earlier.pending_count) == ("DISPATCHED", 0, 1)
    assert _status_counts(db_session, earlier.id) == {"REG": 1}


class _AcceptedButTimedOutClient(_FakeRcsClient):
    """msghub 는 요청 예외 청크까지 모두 접수해 전달했다 — query_sent 는 접수한 키의 전달 결과를, 모르는
    키엔 INVALID_KEY 를 돌려준다."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.accepted: set[str] = set()

    async def send_rcs(self, *, recv_list, **kwargs):
        self.accepted.update(r.cli_key for r in recv_list)
        return await super().send_rcs(recv_list=recv_list, **kwargs)

    async def query_sent(self, cli_keys):
        return [
            {"cliKey": key, "status": "DONE", "resultCode": SUCCESS_CODE, "ch": "RCS", "productCode": "SMS"}
            if key in self.accepted else {"cliKey": key, "status": "INVALID_KEY"}
            for key, _req_dt in cli_keys
        ]


@pytest.mark.asyncio
async def test_request_failure_is_recovered_by_reconcile_when_report_is_not_redelivered(
    db_session, sample_user, sample_caller,
):
    """청크 요청 응답을 기다리는 사이 온 리포트는 행이 없어 반영하지 않고 재전송을 받는데(웹훅 400), 요청은 결국
    예외라 실패로 기록되고 재전송은 끝내 오지 않을 수 있다(msghub 재시도 횟수·중단 조건은 문서에 없다). 재조정이
    그 행을 msghub 에 조회해 실제 전달 결과로 확정한다 — 완료 시각은 발송 때 정한 대로 둔다."""
    recipients = ["01000000001", "01000000002"]
    redelivery_asked: list[str] = []

    def webhook_before_rows_exist(chunk_idx):
        cid = db_session.execute(select(func.max(Campaign.id))).scalar_one()
        with pytest.raises(ReportBeforeRecord) as asked:
            process_report(db_session, [
                _report(f"c{cid}-{chunk_idx}-{i}", phone) for i, phone in enumerate(recipients)
            ])
        db_session.rollback()
        redelivery_asked.append(asked.value.cli_key)

    client = _AcceptedButTimedOutClient(timeout_chunks={0}, on_chunk=webhook_before_rows_exist)
    campaign = await dispatch_campaign(
        db=db_session,
        msghub_client=client,
        created_by=sample_user.sub,
        caller_number=sample_caller.number,
        content="안내 메시지입니다",
        recipients=recipients,
        message_type="SMS",
    )
    assert redelivery_asked == [f"c{campaign.id}-0-0"]
    assert (campaign.state, campaign.fail_count) == ("FAILED", 2)
    completed_at = campaign.completed_at

    # 웹훅 도착 시간(재조정 cutoff 10분)이 지났다
    db_session.execute(
        update(MsghubRequest)
        .where(MsghubRequest.campaign_id == campaign.id)
        .values(sent_at=(datetime.now(UTC) - timedelta(minutes=11)).isoformat())
    )
    db_session.commit()

    n = await reconcile_pending_messages(db_session, client)

    assert n == 2
    assert (campaign.state, campaign.ok_count, campaign.fail_count, campaign.pending_count) == (
        "COMPLETED", 2, 0, 0,
    )
    assert campaign.completed_at == completed_at


# ── _create_messages_from_response 반환 계약 (H1) ─────────────────────────────


def _make_campaign_req(db, sub):
    campaign = Campaign(
        created_by=sub, caller_number="0212345678", message_type="short",
        content="x", total_count=3, pending_count=3, state="DISPATCHING",
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
    return campaign, req


def test_create_messages_returns_accepted_and_failed(db_session, sample_user):
    """SendResponse 의 item 성공/실패를 (accepted, failed) 로 정확히 반환한다."""
    campaign, req = _make_campaign_req(db_session, sample_user.sub)
    resp = SendResponse(code="10000", message="OK", items=[
        SendResultItem(cli_key="c1-0-0", msg_key="m0", phone="01000000001", code=SUCCESS_CODE, message="ok"),
        SendResultItem(cli_key="c1-0-1", msg_key="", phone="01000000002", code="29002", message="blocked"),
        SendResultItem(cli_key="c1-0-2", msg_key="m2", phone="01000000003", code=SUCCESS_CODE, message="ok"),
    ])

    accepted, failed = _create_messages_from_response(
        db_session, campaign.id, req.id, resp,
        ["01000000001", "01000000002", "01000000003"], 0,
    )

    assert (accepted, failed) == (2, 1)


def test_create_messages_reserve_branch_all_accepted(db_session, sample_user):
    """ReserveResponse(예약)는 전건 PENDING 으로 accepted, 실패 0 — 예약 오집계 방지."""
    campaign, req = _make_campaign_req(db_session, sample_user.sub)
    resp = ReserveResponse(code="10000", message="OK", web_req_id="W1")

    accepted, failed = _create_messages_from_response(
        db_session, campaign.id, req.id, resp,
        ["01000000001", "01000000002"], 0,
    )

    assert (accepted, failed) == (2, 0)
