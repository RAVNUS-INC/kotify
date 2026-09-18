"""웹훅 재조정 (C5) 테스트.

reconcile_pending_messages 가 미완료 메시지를 msghub query_sent 로 조회해 상태를
보정하는지, cutoff(최근 건 제외)·idempotency(DONE 제외)가 동작하는지 검증한다.
양방향 실패 후 대체 SMS(-fb) 대기(FB_PENDING)의 확정과 조회 중 대체 발송 경합도 다룬다.
청크 요청 예외로 실패 기록한 메시지(compose._record_failed_chunk)를 한 번 조회해 확정하는
경로와, 그 조회가 미완료 조회를 밀어내지 않는지도 다룬다.
재조정이 양방향 답장 실패를 웹훅보다 먼저 확정했을 때의 대체 발송도 다룬다.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models import Campaign, Message, MsghubRequest
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import SendResponse, SendResultItem
from app.services.reconcile import _req_dt_kst, reconcile_pending_messages


class _FakeClient:
    """query_sent·send_sms 만 흉내내는 테스트용 msghub 클라이언트 (덕 타이핑).

    during_query: 조회 응답을 기다리는 사이 다른 요청(웹훅)이 DB 를 바꾸는 경합 재현용.
    sms_result: 대체 SMS 요청(최상위 10000)의 수신자 단위 결과 (코드, 메시지).
    """

    def __init__(self, result: list[dict], during_query=None, sms_result=(SUCCESS_CODE, "성공")):
        self._result = result
        self._during_query = during_query
        self._sms_result = sms_result
        self.calls: list = []
        self.sms: list = []

    async def query_sent(self, cli_keys):
        self.calls.append(cli_keys)
        if self._during_query:
            self._during_query()
        return self._result

    async def send_sms(self, *, callback, msg, recv_list):
        self.sms += [(r.cli_key, r.phone, callback, msg) for r in recv_list]
        code, message = self._sms_result
        return SendResponse(code=SUCCESS_CODE, message="OK", items=[
            SendResultItem(cli_key=r.cli_key, msg_key="mk-sms", phone=r.phone, code=code, message=message)
            for r in recv_list
        ])


def _make_pending(
    db, sub, sent_at, *, status="REG", cli_key="c1-0-0", msg_key=None, report_dt=None,
    rcs_messagebase_id=None,
):
    campaign = Campaign(
        created_by=sub, caller_number="0212345678", message_type="short",
        content="x", total_count=1, pending_count=1, state="DISPATCHED",
        created_at=sent_at, rcs_messagebase_id=rcs_messagebase_id,
    )
    db.add(campaign)
    db.flush()
    req = MsghubRequest(campaign_id=campaign.id, chunk_index=0, sent_at=sent_at)
    db.add(req)
    db.flush()
    msg = Message(
        campaign_id=campaign.id, msghub_request_id=req.id,
        to_number="01011112222", to_number_raw="01011112222",
        cli_key=cli_key, msg_key=msg_key, status=status, report_dt=report_dt,
    )
    db.add(msg)
    db.commit()
    return campaign, msg


def test_req_dt_kst_utc_to_kst_date():
    # 15:30 UTC = 익일 00:30 KST → 날짜가 하루 넘어감
    assert _req_dt_kst("2026-01-01T15:30:00+00:00") == "2026-01-02"
    # 00:00 UTC = 09:00 KST → 같은 날
    assert _req_dt_kst("2026-01-01T00:00:00+00:00") == "2026-01-01"


def test_reconcile_updates_pending_to_done(db_session, sample_user):
    """오래된 미완료(REG) 메시지가 query_sent 결과로 DONE 보정된다."""
    _make_pending(db_session, sample_user.sub, "2026-01-01T00:00:00+00:00", cli_key="c-r-0")
    client = _FakeClient([{
        "cliKey": "c-r-0", "status": "DONE", "resultCode": "10000",
        "ch": "RCS", "productCode": "SMS",
    }])

    n = asyncio.run(reconcile_pending_messages(db_session, client, older_than_minutes=10))

    assert n == 1
    msg = db_session.execute(
        select(Message).where(Message.cli_key == "c-r-0")
    ).scalar_one()
    assert msg.status == "DONE"
    assert msg.cost == 17  # (RCS, SMS) = 17 — C4 단가와 일치


def test_reconcile_skips_recent_messages(db_session, sample_user):
    """cutoff 이내(방금 발송) 메시지는 조회하지 않는다 (웹훅 도착 시간 확보)."""
    recent = datetime.now(UTC).isoformat()
    _make_pending(db_session, sample_user.sub, recent, cli_key="c-r-1")
    client = _FakeClient([])

    n = asyncio.run(reconcile_pending_messages(db_session, client, older_than_minutes=10))

    assert n == 0
    assert client.calls == []  # query_sent 미호출


def test_reconcile_skips_done_messages(db_session, sample_user):
    """이미 DONE 인 메시지는 재조정 대상이 아니다."""
    _make_pending(
        db_session, sample_user.sub, "2026-01-01T00:00:00+00:00",
        status="DONE", cli_key="c-r-2",
    )
    client = _FakeClient([])

    n = asyncio.run(reconcile_pending_messages(db_session, client, older_than_minutes=10))

    assert n == 0
    assert client.calls == []  # DONE 은 조회 대상 아님


def _status_of(db, cli_key):
    return db.execute(select(Message.status).where(Message.cli_key == cli_key)).scalar_one()


def test_reconcile_ignores_result_for_key_renamed_by_fallback(db_session, sample_user):
    """조회하는 사이 웹훅이 양방향 실패로 대체 SMS 를 보내 cliKey 를 -fb 로 바꾸면, 원래 키의
    조회 결과(양방향 실패)로 FB_PENDING 을 덮지 않는다 — 덮으면 대체 SMS 리포트가 버려진다."""
    _, msg = _make_pending(
        db_session, sample_user.sub, "2026-01-01T00:00:00+00:00",
        cli_key="c-r-3", msg_key="mk-r-3",
    )

    def webhook_falls_back():
        msg.cli_key, msg.status = "c-r-3-fb", "FB_PENDING"
        db_session.commit()

    client = _FakeClient([{
        "cliKey": "c-r-3", "msgKey": "mk-r-3", "status": "DONE",
        "resultCode": "51004", "ch": "RCS", "productCode": "CHAT",
    }], during_query=webhook_falls_back)

    n = asyncio.run(reconcile_pending_messages(db_session, client, older_than_minutes=10))

    assert n == 0
    assert _status_of(db_session, "c-r-3-fb") == "FB_PENDING"


def test_reconcile_settles_fallback_pending_by_fb_key_on_sms_request_date(db_session, sample_user):
    """대체 SMS 리포트 웹훅이 유실된 FB_PENDING 은 -fb cliKey 로 조회해 확정한다. reqDt 는 원래
    발송일이 아니라 대체 SMS 를 보낸 날(대체 발송이 report_dt 에 남긴 요청 시각)이다."""
    # 1일 23:50 KST 발송, 양방향 실패를 받아 대체 SMS 를 보낸 건 자정을 넘긴 2일 00:10 KST
    _make_pending(
        db_session, sample_user.sub, "2026-01-01T14:50:00+00:00",
        status="FB_PENDING", cli_key="c-r-4-fb", report_dt="20260102001000",
    )
    client = _FakeClient([{
        "cliKey": "c-r-4-fb", "status": "DONE", "resultCode": "10000",
        "ch": "SMS", "productCode": "SMS",
    }])

    n = asyncio.run(reconcile_pending_messages(db_session, client, older_than_minutes=10))

    assert client.calls == [[("c-r-4-fb", "2026-01-02")]]
    assert n == 1
    msg = db_session.execute(
        select(Message).where(Message.cli_key == "c-r-4-fb")
    ).scalar_one()
    assert (msg.status, msg.channel, msg.cost) == ("DONE", "SMS", 9)


def test_reconcile_keeps_fallback_pending_while_sms_in_flight(db_session, sample_user):
    """-fb 대체 SMS 가 아직 처리 중(ING)이면 FB_PENDING 을 ING 로 덮지 않는다 (수신자 배지 fallback_sms)."""
    _make_pending(
        db_session, sample_user.sub, "2026-01-01T00:00:00+00:00",
        status="FB_PENDING", cli_key="c-r-5-fb", report_dt="20260101091000",
    )
    client = _FakeClient([{"cliKey": "c-r-5-fb", "status": "ING"}])

    n = asyncio.run(reconcile_pending_messages(db_session, client, older_than_minutes=10))

    assert n == 0
    assert _status_of(db_session, "c-r-5-fb") == "FB_PENDING"


# ── 요청 예외로 실패 기록한 메시지 ──────────────────────────────────────────────


def _ago(**delta) -> str:
    return (datetime.now(UTC) - timedelta(**delta)).isoformat()


def _make_request_failure(
    db, sub, *, cli_keys, sent_at, result_code=None, response_code=None, error_body="응답 대기 시간 초과",
):
    """청크 요청이 예외라 실패로 기록한 캠페인 (compose._record_failed_chunk) — 요청엔 응답 코드 없이 오류만,
    행은 FAILED·result_code 없음. result_code·response_code 를 주면 수신자 단위 거부 행이 된다."""
    campaign = Campaign(
        created_by=sub, caller_number="0212345678", message_type="short", content="x",
        total_count=len(cli_keys), fail_count=len(cli_keys), pending_count=0,
        state="FAILED", created_at=sent_at, completed_at=sent_at,
    )
    db.add(campaign)
    db.flush()
    req = MsghubRequest(
        campaign_id=campaign.id, chunk_index=0, sent_at=sent_at,
        response_code=response_code, response_message="fail", error_body=error_body,
    )
    db.add(req)
    db.flush()
    for i, cli_key in enumerate(cli_keys):
        db.add(Message(
            campaign_id=campaign.id, msghub_request_id=req.id,
            to_number=f"0102222{i:04d}", to_number_raw=f"0102222{i:04d}",
            cli_key=cli_key, status="FAILED", result_code=result_code, result_desc=error_body,
        ))
    db.commit()
    return campaign


def _message(db, cli_key):
    return db.execute(select(Message).where(Message.cli_key == cli_key)).scalar_one()


def test_reconcile_settles_request_failure_that_msghub_accepted(db_session, sample_user):
    """청크 요청이 예외(응답 타임아웃)라 실패로 기록했어도 msghub 가 접수해 전달했으면 조회 결과로 확정한다 —
    그 리포트는 행을 기록하기 전에 와서 버려졌을 수 있다. 캠페인 state 와 비용도 결과를 따른다."""
    sent_at = _ago(hours=1)
    campaign = _make_request_failure(
        db_session, sample_user.sub, cli_keys=["c-x-0-0", "c-x-0-1"], sent_at=sent_at,
    )
    client = _FakeClient([
        {"cliKey": "c-x-0-0", "status": "DONE", "resultCode": "10000", "ch": "RCS", "productCode": "SMS"},
        {"cliKey": "c-x-0-1", "status": "DONE", "resultCode": "10000", "ch": "SMS", "productCode": "SMS"},
    ])

    n = asyncio.run(reconcile_pending_messages(db_session, client, older_than_minutes=10))

    req_dt = _req_dt_kst(sent_at)
    assert client.calls == [[("c-x-0-0", req_dt), ("c-x-0-1", req_dt)]]
    assert n == 2
    assert (campaign.state, campaign.ok_count, campaign.fail_count, campaign.total_cost) == (
        "COMPLETED", 2, 0, 26,
    )


@pytest.mark.parametrize("query_status", ["REG", "ING"])
@pytest.mark.parametrize("initial_state", ["FAILED", "RESERVE_FAILED"])
def test_reconcile_moves_request_failure_back_to_pending_while_msghub_processes_it(
    db_session, sample_user, query_status, initial_state,
):
    """조회 결과가 접수·처리 중(ING)이면 실패가 아니라 대기다 — 집계를 실패에서 대기로 옮기고, 그 뒤엔
    미완료 행으로 조회돼 결과가 확정된다."""
    campaign = _make_request_failure(db_session, sample_user.sub, cli_keys=["c-y-0-0"], sent_at=_ago(minutes=30))
    campaign.state = initial_state
    if initial_state == "RESERVE_FAILED":
        # 예약 시각이 지난 뒤 조회되는 실패한 예약 요청도 현재 처리 중이면 발송 중이다.
        campaign.reserve_time = "2026-01-01 09:00"
    db_session.commit()
    original_completed_at = campaign.completed_at

    total = asyncio.run(reconcile_pending_messages(
        db_session, _FakeClient([{"cliKey": "c-y-0-0", "status": query_status}]),
    ))

    assert total == 0  # 확정(DONE) 건수 API는 실패 → 처리 중 복구와 구분한다.
    assert _status_of(db_session, "c-y-0-0") == query_status
    assert (campaign.fail_count, campaign.pending_count) == (0, 1)
    assert campaign.state == "DISPATCHING"
    assert campaign.completed_at == original_completed_at

    from app.routes.campaigns import _campaign_to_dict
    from app.routes.notifications import _campaign_notif

    assert _campaign_to_dict(campaign)["status"] == "sending"
    notification = _campaign_notif(campaign)
    assert notification["level"] == "info"
    assert notification["title"].endswith("발송 중")
    assert notification["_ts_iso"] == original_completed_at

    done = _FakeClient([{
        "cliKey": "c-y-0-0", "status": "DONE", "resultCode": "10000", "ch": "RCS", "productCode": "SMS",
    }])
    asyncio.run(reconcile_pending_messages(db_session, done))

    assert (campaign.state, campaign.ok_count, campaign.pending_count) == ("COMPLETED", 1, 0)
    # 첫 결과 시각을 유지해 읽은 알림이 복구/최종 확정 때 새 알림으로 다시 뜨지 않는다.
    assert campaign.completed_at == original_completed_at


@pytest.mark.parametrize("no_result", ["INVALID_KEY", "OVER_DATE"])
def test_reconcile_queries_request_failure_without_result_only_once(db_session, sample_user, no_result):
    """조회가 결과를 주지 않으면(INVALID_KEY 키 오류 — 접수되지 않은 요청, OVER_DATE 조회기간 초과) 실패로
    남기고 그 상태를 result_code 에 남겨 다음 주기엔 다시 조회하지 않는다 — 조회 호출이 매 주기 쌓이지 않게."""
    campaign = _make_request_failure(db_session, sample_user.sub, cli_keys=["c-z-0-0-fb"], sent_at=_ago(hours=2))
    client = _FakeClient([{"cliKey": "c-z-0-0-fb", "status": no_result}])

    asyncio.run(reconcile_pending_messages(db_session, client))
    asyncio.run(reconcile_pending_messages(db_session, client))

    assert len(client.calls) == 1
    msg = _message(db_session, "c-z-0-0-fb")
    expected_desc = (
        "리포트 조회 가능 기간을 초과했습니다."
        if no_result == "OVER_DATE"
        else "공급자에서 cliKey를 찾을 수 없습니다."
    )
    assert (msg.status, msg.result_code, msg.result_desc) == ("FAILED", no_result, expected_desc)
    assert (campaign.state, campaign.fail_count) == ("FAILED", 1)


@pytest.mark.parametrize("case", ["item_rejected", "past_query_window", "reservation_not_yet_run"])
def test_reconcile_does_not_query_failures_without_expected_result(db_session, sample_user, case):
    """조회하지 않는 실패 — 수신자 단위 거부(msghub 가 접수하지 않아 리포트가 없다), 조회 기간(24시간)이
    지난 요청 예외, 예약 시각이 아직 오지 않은 예약 요청 예외(요청의 sent_at 은 예약 시각)."""
    if case == "item_rejected":
        _make_request_failure(
            db_session, sample_user.sub, cli_keys=["c-n-0-0"], sent_at=_ago(hours=1),
            result_code="31101", response_code="10000", error_body=None,
        )
    elif case == "past_query_window":
        _make_request_failure(db_session, sample_user.sub, cli_keys=["c-n-0-0"], sent_at=_ago(hours=25))
    else:
        _make_request_failure(db_session, sample_user.sub, cli_keys=["c-n-0-0"], sent_at=_ago(hours=-3))
    client = _FakeClient([])

    n = asyncio.run(reconcile_pending_messages(db_session, client))

    assert n == 0
    assert client.calls == []


def test_reconcile_queries_request_failures_apart_from_pending(db_session, sample_user):
    """요청 예외 실패는 미완료 행의 1회 상한을 나눠 쓰지 않고 같은 조회 요청에 섞이지 않는다 — 실패 행이
    미완료 확정을 밀어내거나, msghub 가 접수하지 않은 키 때문에 거부된 조회가 미완료 확정까지 막으면 안 된다."""
    failed_keys = [f"c-f-0-{i}" for i in range(10)]
    sent_at = _ago(hours=1)
    _make_request_failure(db_session, sample_user.sub, cli_keys=failed_keys, sent_at=sent_at)  # id 가 앞선다
    _make_pending(db_session, sample_user.sub, "2026-01-01T00:00:00+00:00", cli_key="c-p-0")
    client = _FakeClient([])

    asyncio.run(reconcile_pending_messages(db_session, client, max_messages=1))

    assert client.calls == [
        [("c-p-0", "2026-01-01")],
        [(key, _req_dt_kst(sent_at)) for key in failed_keys],
    ]


def test_reconcile_closes_pending_message_with_invalid_key(db_session, sample_user):
    """미완료 행의 INVALID_KEY도 종료해 재조정 큐를 점유하지 않는다."""
    campaign, _ = _make_pending(
        db_session, sample_user.sub, "2026-01-01T00:00:00+00:00", cli_key="c-q-0"
    )
    client = _FakeClient([{"cliKey": "c-q-0", "status": "INVALID_KEY"}])

    assert asyncio.run(reconcile_pending_messages(db_session, client)) == 1

    msg = _message(db_session, "c-q-0")
    assert (msg.status, msg.result_code) == ("FAILED", "INVALID_KEY")
    assert (campaign.state, campaign.fail_count, campaign.pending_count) == ("FAILED", 1, 0)


# ── 양방향 답장(CHAT) 실패를 재조정이 먼저 확정 ─────────────────────────────────────

_CHAT = "RPCSAXX001"


def _chat_failure(cli_key, rpt_dt="2026-01-01T09:00:05"):
    """양방향 답장의 RCS 실패 조회 결과."""
    return {
        "cliKey": cli_key, "msgKey": f"mk-{cli_key}", "status": "DONE", "resultCode": "51004",
        "resultCodeDesc": "RCS 미지원 단말", "ch": "RCS", "productCode": "CHAT", "rptDt": rpt_dt,
    }


def _message_of(db, campaign_id):
    return db.execute(select(Message).where(Message.campaign_id == campaign_id)).scalar_one()


def test_reconcile_falls_back_to_sms_for_chat_reply_failure(db_session, sample_user):
    """리포트 웹훅이 10분 넘게 늦어 재조정이 양방향 답장 실패를 먼저 확정해도 웹훅처럼 대체 SMS 를
    보낸다. 실패로 확정만 하면 뒤늦게 온 실패 리포트는 확정된 행이라 버려져 답장이 끝내 안 갔다."""
    campaign, _ = _make_pending(
        db_session, sample_user.sub, "2026-01-01T00:00:00+00:00",
        cli_key="c-r-6", rcs_messagebase_id=_CHAT,
    )
    client = _FakeClient([_chat_failure("c-r-6")])

    n = asyncio.run(reconcile_pending_messages(db_session, client, older_than_minutes=10))
    db_session.rollback()  # 재조정 루프는 끝나면 세션을 닫는다 — 커밋되지 않은 상태는 사라진다

    assert n == 1
    assert client.sms == [("c-r-6-fb", "01011112222", "0212345678", "x")]
    msg = _message_of(db_session, campaign.id)
    assert (msg.status, msg.cli_key, msg.result_code) == ("FB_PENDING", "c-r-6-fb", "51004")
    # 대체 SMS 리포트를 기다리는 동안 캠페인은 발송 중으로 집계된다
    campaign = db_session.get(Campaign, campaign.id)
    assert (campaign.fail_count, campaign.pending_count, campaign.state) == (0, 1, "DISPATCHED")


def test_reconcile_rejected_chat_fallback_is_failed_not_pending(db_session, sample_user):
    """재조정이 보낸 대체 SMS 가 수신자 단위로 거부되면(31101) 웹훅 경로처럼 사유와 함께 FAILED 로
    확정하고 캠페인을 다시 집계한다 — 리포트가 오지 않으니 FB_PENDING 으로 두면 영영 대기다."""
    campaign, _ = _make_pending(
        db_session, sample_user.sub, "2026-01-01T00:00:00+00:00",
        cli_key="c-r-7", rcs_messagebase_id=_CHAT,
    )
    client = _FakeClient([_chat_failure("c-r-7")], sms_result=("31101", "수신번호 에러"))

    asyncio.run(reconcile_pending_messages(db_session, client, older_than_minutes=10))

    msg = _message_of(db_session, campaign.id)
    assert (msg.status, msg.result_code) == ("FAILED", "31101")
    assert msg.result_desc == "수신번호 에러 (SMS fallback 거부)"
    campaign = db_session.get(Campaign, campaign.id)
    assert (campaign.fail_count, campaign.pending_count, campaign.state) == (1, 0, "FAILED")


def test_reconcile_does_not_fall_back_a_failed_fallback_sms_again(db_session, sample_user):
    """대체 SMS(-fb) 가 실패로 확정돼도 다시 대체 발송하지 않는다 — 답장 하나에 대체 SMS 는 한 번.
    같은 배치에서 재조정이 처음 확정한 양방향 실패만 대체 발송한다."""
    # 웹훅이 이미 대체 발송한 답장 — 그 SMS 는 실패했고 리포트 웹훅은 유실됐다
    _make_pending(
        db_session, sample_user.sub, "2026-01-01T00:00:00+00:00",
        status="FB_PENDING", cli_key="c-r-8-fb", report_dt="20260101091000",
        rcs_messagebase_id=_CHAT,
    )
    _make_pending(
        db_session, sample_user.sub, "2026-01-01T00:00:00+00:00",
        cli_key="c-r-9", rcs_messagebase_id=_CHAT,
    )
    client = _FakeClient([
        {"cliKey": "c-r-8-fb", "status": "DONE", "resultCode": "30101",
         "resultCodeDesc": "단말기 메시지 FULL", "ch": "SMS", "productCode": "SMS"},
        _chat_failure("c-r-9"),
    ])

    n = asyncio.run(reconcile_pending_messages(db_session, client, older_than_minutes=10))

    assert n == 2
    assert [cli_key for cli_key, *_ in client.sms] == ["c-r-9-fb"]
    assert _status_of(db_session, "c-r-8-fb") == "DONE"
    assert _status_of(db_session, "c-r-9-fb") == "FB_PENDING"


def test_reconcile_queries_its_fallback_sms_on_the_date_it_was_sent(db_session, sample_user, monkeypatch):
    """재조정이 보낸 대체 SMS 는 요청한 날짜로 조회한다(reqDt 는 발송일자) — 양방향 실패 리포트 시각이
    아니다. 실패는 1일 23:55 KST 인데 재조정은 자정을 넘긴 2일 00:05 KST 에 확정·대체 발송했다."""
    campaign, _ = _make_pending(
        db_session, sample_user.sub, "2026-01-01T14:50:00+00:00",  # 1일 23:50 KST
        cli_key="c-r-10", rcs_messagebase_id=_CHAT,
    )
    monkeypatch.setattr("app.services.report._now_iso", lambda: "2026-01-01T15:05:00+00:00")
    asyncio.run(reconcile_pending_messages(
        db_session, _FakeClient([_chat_failure("c-r-10", rpt_dt="2026-01-01T23:55:00")]),
        older_than_minutes=10,
    ))

    # 대체 SMS 리포트 웹훅도 유실 — 다음 재조정이 -fb cliKey 로 확정한다
    client = _FakeClient([{
        "cliKey": "c-r-10-fb", "status": "DONE", "resultCode": SUCCESS_CODE,
        "ch": "SMS", "productCode": "SMS",
    }])
    n = asyncio.run(reconcile_pending_messages(db_session, client, older_than_minutes=10))

    assert client.calls == [[("c-r-10-fb", "2026-01-02")]]
    assert n == 1
    msg = _message_of(db_session, campaign.id)
    assert (msg.status, msg.channel, msg.cost) == ("DONE", "SMS", 9)
