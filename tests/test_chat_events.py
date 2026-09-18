"""대화방 실시간 갱신(SSE) 이벤트 테스트.

- publish → 구독자 큐 전달, 구독 해제 후엔 미전달.
- 구독자 없어도/큐 가득 차도 publish 는 예외 없이 동작(webhook 보호).
- publish_throttled: 몰려온 변경도 창(window)당 1회 — 첫 변경은 즉시, 마지막 변경은 창 끝에.
- MO 웹훅은 새로 저장한 회신이 있을 때만, 커밋 뒤에 "message.new" 를 합쳐 발행한다(회신이
  새로고침 없이 뜨는 근거). 몰려온 회신도 창당 1회, 발행이 실패해도 msghub 에는 success.
- 리포트 웹훅·재조정은 발신 전달 상태가 바뀌었을 때만, 커밋 뒤에 "thread.updated" 를
  합쳐 발행한다(열린 대화방의 대기 라벨이 새로고침 없이 바뀌는 근거).
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import select

from app.models import Caller, Campaign, Message, MoMessage, MsghubRequest
from app.msghub.codes import SUCCESS_CODE
from app.routes.webhook import receive_mo, receive_report
from app.security.settings_store import SettingsStore
from app.services import events
from app.services.reconcile import reconcile_pending_messages
from app.services.report import awaiting_record


def _setup_token(db):
    SettingsStore(db).set(
        "msghub.webhook_token", "wtok", is_secret=True, updated_by="test"
    )
    db.commit()


def _json_request(body: dict):
    request = MagicMock()
    request.json = AsyncMock(return_value=body)
    request.client = MagicMock()
    request.client.host = "10.0.0.1"
    return request


def _mo_body(key="e1", *, number="01012345678", callback=None):
    item = {
        "moKey": key, "moNumber": number, "moMsg": "회신",
        "moRecvDt": "2026-01-01 10:00:00",
    }
    if callback is not None:
        item["moCallback"] = callback
    return {"moCnt": 1, "moLst": [item]}


def _record_commits_and_publishes(db, monkeypatch) -> list[str]:
    """커밋과 발행을 일어난 순서대로 기록한다 — "커밋 뒤에만 발행" 검증용.

    데이터 준비(커밋)가 끝난 뒤에 설치할 것.
    """
    calls: list[str] = []
    real_commit = db.commit

    def commit() -> None:
        real_commit()
        calls.append("commit")

    monkeypatch.setattr(db, "commit", commit)
    monkeypatch.setattr(events, "publish", lambda event: calls.append(event) or 0)
    return calls


# ── 이벤트 버스 ──────────────────────────────────────────────────────────────


def test_publish_delivers_to_subscriber():
    async def run():
        q = events.subscribe()
        try:
            delivered = events.publish("message.new")
            assert delivered == 1
            assert q.get_nowait() == "message.new"
        finally:
            events.unsubscribe(q)

    asyncio.run(run())


def test_unsubscribe_stops_delivery():
    async def run():
        q = events.subscribe()
        events.unsubscribe(q)
        delivered = events.publish("message.new")
        assert delivered == 0
        assert q.empty()

    asyncio.run(run())


def test_publish_without_subscribers_is_safe():
    """구독자 0명이어도 예외 없이 0 반환 (webhook 보호)."""
    assert events.publish("message.new") == 0


def test_publish_survives_full_queue():
    """큐가 가득 찬 느린 구독자가 있어도 예외 없이 진행(이벤트만 드롭)."""
    async def run():
        slow = events.subscribe()
        fast = events.subscribe()
        try:
            # slow 를 가득 채움
            for _ in range(64):
                try:
                    slow.put_nowait("x")
                except asyncio.QueueFull:
                    break
            delivered = events.publish("message.new")
            # fast 에는 전달, slow 는 드롭 — 예외 없이 진행
            assert delivered >= 1
            assert fast.get_nowait() == "message.new"
        finally:
            events.unsubscribe(slow)
            events.unsubscribe(fast)

    asyncio.run(run())


# ── 합쳐 발행 (publish_throttled) ────────────────────────────────────────────


class _ManualClock:
    """실행 중인 루프의 시계를 손으로 돌린다 — call_later 예약도 이 시계 기준으로 만료된다."""

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.now = 0.0
        loop.time = lambda: self.now

    async def advance(self, seconds: float) -> None:
        self.now += seconds
        for _ in range(3):  # 만료된 타이머 콜백이 실제로 돌 틈
            await asyncio.sleep(0)


def _record_publish_times(monkeypatch, clock: _ManualClock) -> list[float]:
    """publish 가 불린 (가짜) 시각 목록."""
    times: list[float] = []

    def spy(event: str) -> int:
        times.append(clock.now)
        return 0

    monkeypatch.setattr(events, "publish", spy)
    return times


def test_throttled_first_change_is_published_immediately():
    """조용하던 뒤 첫 변경은 기다리지 않는다 — 답장 1건의 리포트는 바로 반영."""
    async def run():
        q = events.subscribe()
        try:
            events.publish_throttled("thread.updated", window=5)
            assert q.get_nowait() == "thread.updated"
        finally:
            events.unsubscribe(q)

    asyncio.run(run())


def test_throttled_burst_publishes_once_per_window_including_last_change(monkeypatch):
    """대량 발송 리포트 20건이 10초 동안 몰려도 발행은 0·5·10초 3회.

    창 안의 변경은 버리지 않고 창 끝에 한 번 싣는다 — 9.5초의 마지막 변경도 10초에 나간다.
    """
    async def run():
        clock = _ManualClock(asyncio.get_running_loop())
        published = _record_publish_times(monkeypatch, clock)

        for _ in range(20):  # 0.5초 간격 리포트 웹훅
            events.publish_throttled("thread.updated", window=5)
            await clock.advance(0.5)
        await clock.advance(30)  # 조용해진 뒤엔 더 발행하지 않는다

        assert published == [0.0, 5.0, 10.0]

    asyncio.run(run())


def test_throttled_publishes_immediately_again_after_quiet_window(monkeypatch):
    async def run():
        clock = _ManualClock(asyncio.get_running_loop())
        published = _record_publish_times(monkeypatch, clock)

        events.publish_throttled("thread.updated", window=5)
        await clock.advance(5)
        events.publish_throttled("thread.updated", window=5)

        assert published == [0.0, 5.0]

    asyncio.run(run())


def test_throttled_windows_are_per_event_name():
    async def run():
        q = events.subscribe()
        try:
            events.publish_throttled("thread.updated", window=5)
            events.publish_throttled("other.event", window=5)
            assert [q.get_nowait(), q.get_nowait()] == ["thread.updated", "other.event"]
        finally:
            events.unsubscribe(q)

    asyncio.run(run())


def test_throttled_state_does_not_leak_across_event_loops():
    """닫힌 루프에 예약된 창 끝 발행(영영 안 도는 타이머)이 새 루프의 발행을 막지 않는다."""
    async def first():
        events.publish_throttled("thread.updated", window=60)
        events.publish_throttled("thread.updated", window=60)  # 창 끝 예약 후 루프 종료

    async def second():
        q = events.subscribe()
        try:
            events.publish_throttled("thread.updated", window=60)
            assert q.get_nowait() == "thread.updated"
        finally:
            events.unsubscribe(q)

    asyncio.run(first())
    asyncio.run(second())


def test_throttled_without_running_loop_publishes_directly(monkeypatch):
    """루프 밖에선 창 끝을 예약할 수 없어 바로 발행한다 — 예외로 호출측을 막지 않는다."""
    published: list[str] = []
    monkeypatch.setattr(events, "publish", lambda event: published.append(event) or 0)

    events.publish_throttled("thread.updated")

    assert published == ["thread.updated"]


# ── MO 수신 → 이벤트 발행 (통합) ─────────────────────────────────────────────


def test_receive_mo_publishes_event(db_session):
    """조용하던 뒤 첫 회신은 기다리지 않고 message.new 발행 → 브라우저가 바로 갱신."""
    _setup_token(db_session)

    async def run():
        q = events.subscribe()
        try:
            resp = await receive_mo("wtok", _json_request(_mo_body()), db_session)
            assert resp.status_code == 200
            assert q.get_nowait() == "message.new"
        finally:
            events.unsubscribe(q)

    asyncio.run(run())


def test_mo_burst_is_throttled(db_session, monkeypatch):
    """회신을 부르는 캠페인("YES 로 답장")에 MO 가 몰려도 창 안에선 바로 발행이 한 번뿐이다.

    나머지 회신은 버리지 않고 창 끝에 한 번 싣는다 — 마지막 회신도 창 길이 안에 화면에 뜬다.
    """
    _setup_token(db_session)
    calls = _record_commits_and_publishes(db_session, monkeypatch)

    async def run():
        clock = _ManualClock(asyncio.get_running_loop())
        for i in range(3):  # 1초 간격, 서로 다른 고객의 회신
            body = _mo_body(f"burst-{i}", number=f"0101234000{i}")
            resp = await receive_mo("wtok", _json_request(body), db_session)
            assert resp.status_code == 200
            await clock.advance(1)
        assert calls == ["commit", "message.new", "commit", "commit"]

        await clock.advance(events._THROTTLE_WINDOW_SECONDS - clock.now)  # 첫 발행의 창 끝
        assert calls == ["commit", "message.new", "commit", "commit", "message.new"]

    asyncio.run(run())


@pytest.mark.parametrize(
    "follow_up",
    [
        pytest.param(_mo_body("first"), id="duplicate-mo"),
        pytest.param(_mo_body("forged", callback="07099998888"), id="unregistered-callback"),
    ],
)
def test_mo_without_new_rows_does_not_publish(db_session, monkeypatch, follow_up):
    """저장한 회신이 없는 MO(재전송 중복·미등록 발신번호 거부)는 새로고침을 부르지 않는다.

    직전 회신의 창 안에 와도 창 끝 발행을 예약하지 않아야 한다. 합쳐 발행하면 잘못 부른
    발행도 창 끝까지 미뤄질 뿐이라, 창이 지난 뒤에 확인한다.
    """
    _setup_token(db_session)
    db_session.add(Caller(
        number="0212345678", label="발신", active=1, created_at="2026-01-01T00:00:00+00:00",
    ))
    db_session.commit()

    async def run():
        clock = _ManualClock(asyncio.get_running_loop())
        await receive_mo("wtok", _json_request(_mo_body("first")), db_session)  # 저장 + 발행
        calls = _record_commits_and_publishes(db_session, monkeypatch)

        resp = await receive_mo("wtok", _json_request(follow_up), db_session)
        await clock.advance(events._THROTTLE_WINDOW_SECONDS)

        assert resp.status_code == 200
        assert calls == ["commit"]

    asyncio.run(run())


def test_mo_publish_failure_does_not_block_success(db_session, monkeypatch):
    """발행이 예외로 끝나도 회신은 커밋되고 msghub 에는 success.

    success 를 못 받은 msghub 가 재전송하면 그 MO 는 중복이라, 대화방 갱신도 n8n 알림도
    다시는 나가지 않는다.
    """
    _setup_token(db_session)

    def broken_publish(event: str) -> int:
        raise RuntimeError("event bus down")

    monkeypatch.setattr(events, "publish", broken_publish)

    resp = asyncio.run(receive_mo("wtok", _json_request(_mo_body()), db_session))

    assert resp.status_code == 200
    assert json.loads(resp.body) == {"code": "10000", "message": "success"}
    assert db_session.execute(select(MoMessage.mo_key)).scalars().all() == ["e1"]


# ── 리포트 웹훅·재조정 → thread.updated (통합) ───────────────────────────────

_PHONE = "01099998888"
_CLI_KEY = "c1-0-0"
_REPORT_FAIL = "59999"


def _reply(
    db,
    sub,
    *,
    status="REG",
    result_code=None,
    cli_key=_CLI_KEY,
    rcs_messagebase_id="RPSSAXX001",
    sent_at="2026-09-01T00:00:00+00:00",
):
    """_PHONE 에게 보낸 답장 1건(리포트 대기 중)."""
    campaign = Campaign(
        created_by=sub, caller_number="0212345678", message_type="short",
        content="안내드립니다", total_count=1, pending_count=1, state="DISPATCHED",
        created_at=sent_at, rcs_messagebase_id=rcs_messagebase_id,
    )
    db.add(campaign)
    db.flush()
    req = MsghubRequest(campaign_id=campaign.id, chunk_index=0, sent_at=sent_at)
    db.add(req)
    db.flush()
    db.add(Message(
        campaign_id=campaign.id, msghub_request_id=req.id, to_number=_PHONE,
        to_number_raw=_PHONE, status=status, result_code=result_code, cli_key=cli_key,
    ))
    db.commit()


def _report_body(cli_key=_CLI_KEY, result_code=SUCCESS_CODE):
    return {"rptCnt": 1, "rptLst": [{
        "cliKey": cli_key, "msgKey": "mk-1", "ch": "RCS", "resultCode": result_code,
        "resultCodeDesc": "결과", "productCode": "SMS", "rptDt": "2026-09-01 09:00:05",
    }]}


def test_report_publishes_thread_updated_after_commit(db_session, sample_user, monkeypatch):
    """리포트로 대기 답장이 확정되면 커밋 뒤 thread.updated — 열린 대화방이 대기에서 바뀐다."""
    _setup_token(db_session)
    _reply(db_session, sample_user.sub)
    calls = _record_commits_and_publishes(db_session, monkeypatch)

    resp = asyncio.run(receive_report("wtok", _json_request(_report_body()), db_session))

    assert resp.status_code == 200
    assert calls == ["commit", "thread.updated"]


def test_report_burst_is_throttled(db_session, sample_user, monkeypatch):
    """대량 발송 리포트가 연달아 와도 창 안에선 즉시 발행이 한 번 — 나머지는 창 끝에 합친다."""
    _setup_token(db_session)
    _reply(db_session, sample_user.sub, cli_key="c1-0-0")
    _reply(db_session, sample_user.sub, cli_key="c1-0-1")
    calls = _record_commits_and_publishes(db_session, monkeypatch)

    async def run():
        for cli_key in ("c1-0-0", "c1-0-1"):
            resp = await receive_report("wtok", _json_request(_report_body(cli_key)), db_session)
            assert resp.status_code == 200

    asyncio.run(run())

    assert calls == ["commit", "thread.updated", "commit"]


@pytest.mark.parametrize(
    ("status", "report_cli_key"),
    [
        pytest.param("DONE", _CLI_KEY, id="duplicate-report-for-settled-message"),
        pytest.param("REG", "unknown-cli-key", id="unmatched-report"),
    ],
)
def test_report_without_changes_does_not_publish(
    db_session, sample_user, monkeypatch, status, report_cli_key
):
    """바뀐 행이 없는 리포트(이미 확정된 행의 재전송·매칭 실패)는 새로고침을 부르지 않는다."""
    _setup_token(db_session)
    _reply(db_session, sample_user.sub, status=status, result_code=SUCCESS_CODE)
    calls = _record_commits_and_publishes(db_session, monkeypatch)

    resp = asyncio.run(
        receive_report("wtok", _json_request(_report_body(report_cli_key)), db_session)
    )

    assert resp.status_code == 200
    assert calls == ["commit"]


def test_report_batch_asking_redelivery_still_publishes_applied_reports(
    db_session, sample_user, monkeypatch
):
    """행 기록 전 리포트가 섞여 400 으로 재전송을 받는 배치도 먼저 반영·커밋한 리포트는 알린다 — 재전송 때 그
    리포트는 이미 DONE 이라 건너뛰어, 여기서 알리지 않으면 열린 대화방이 대기로 남는다."""
    _setup_token(db_session)
    _reply(db_session, sample_user.sub)
    sending = Campaign(  # 청크 응답을 기다리는 중 — 행 기록 전
        created_by=sample_user.sub, caller_number="0212345678", message_type="short", content="안내",
        total_count=1, pending_count=1, state="DISPATCHING", created_at="2026-09-01T00:00:00+00:00",
    )
    db_session.add(sending)
    db_session.commit()
    calls = _record_commits_and_publishes(db_session, monkeypatch)
    [applied] = _report_body()["rptLst"]
    body = {"rptCnt": 2, "rptLst": [applied, {**applied, "cliKey": f"c{sending.id}-0-0", "msgKey": "mk-2"}]}

    with awaiting_record([sending.id]):
        resp = asyncio.run(receive_report("wtok", _json_request(body), db_session))

    assert (resp.status_code, json.loads(resp.body)) == (400, {"error": "report before record"})
    assert calls == ["commit", "thread.updated"]


def test_report_processing_failure_does_not_publish(db_session, sample_user, monkeypatch):
    """처리 실패는 롤백(msghub 재시도) — 커밋되지 않은 변경을 알리지 않는다."""
    _setup_token(db_session)
    _reply(db_session, sample_user.sub)
    calls = _record_commits_and_publishes(db_session, monkeypatch)

    def boom(db, items):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.routes.webhook.process_report", boom)

    resp = asyncio.run(receive_report("wtok", _json_request(_report_body()), db_session))

    assert resp.status_code == 400
    assert calls == []


def test_chat_report_failure_publishes_after_sms_fallback_commit(
    db_session, sample_user, monkeypatch
):
    """양방향 CHAT 실패 → SMS 대체 발송 → 커밋 뒤 발행. 말풍선이 SMS 대기로 바뀐다."""
    _setup_token(db_session)
    _reply(db_session, sample_user.sub, rcs_messagebase_id="RPCSAXX001")
    sms = AsyncMock()
    client = MagicMock(send_sms=sms)
    monkeypatch.setattr("app.main.get_msghub_client", lambda: client)
    calls = _record_commits_and_publishes(db_session, monkeypatch)

    resp = asyncio.run(
        receive_report(
            "wtok", _json_request(_report_body(result_code=_REPORT_FAIL)), db_session
        )
    )

    assert resp.status_code == 200
    sms.assert_awaited_once()
    assert calls == ["commit", "thread.updated"]
    msg = db_session.execute(select(Message)).scalar_one()
    assert (msg.status, msg.cli_key) == ("FB_PENDING", f"{_CLI_KEY}-fb")


class _QuerySentClient:
    """query_sent 만 흉내내는 msghub 클라이언트."""

    def __init__(self, result: list[dict]):
        self._result = result

    async def query_sent(self, cli_keys):
        return self._result


def test_reconcile_publishes_after_commit_when_messages_settle(
    db_session, sample_user, monkeypatch
):
    """웹훅 유실분을 재조정으로 확정해도 열린 대화방이 대기에서 바뀐다."""
    _reply(db_session, sample_user.sub)
    calls = _record_commits_and_publishes(db_session, monkeypatch)
    client = _QuerySentClient([{
        "cliKey": _CLI_KEY, "status": "DONE", "resultCode": SUCCESS_CODE,
        "ch": "RCS", "productCode": "SMS",
    }])

    total = asyncio.run(reconcile_pending_messages(db_session, client, older_than_minutes=10))

    assert total == 1
    assert calls == ["commit", "thread.updated"]


@pytest.mark.parametrize("recover_failure", [False, True])
def test_reconcile_publishes_committed_batches_when_a_later_batch_fails(
    db_session, sample_user, monkeypatch, recover_failure,
):
    """뒤 배치가 예외(DB 잠김 등)로 끊겨도 앞서 커밋된 확정분은 알린다.

    확정된 행은 DONE 이라 다음 재조정 주기엔 잡히지 않는다 — 여기서 알리지 않으면 열린
    대화방은 다른 이벤트가 올 때까지 대기로 남는다.
    """
    sent_at = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    for i in range(11):  # query_sent 10건 제약 → 배치 2개
        _reply(
            db_session, sample_user.sub, cli_key=f"c1-0-{i}", sent_at=sent_at,
            status="FAILED" if recover_failure else "REG",
        )
    if recover_failure:
        for request in db_session.execute(select(MsghubRequest)).scalars():
            request.error_body = "timeout"
        db_session.commit()
    calls = _record_commits_and_publishes(db_session, monkeypatch)

    class _AllDoneClient:
        async def query_sent(self, cli_keys):
            return [
                {"cliKey": key, "status": "ING" if recover_failure else "DONE", "resultCode": SUCCESS_CODE,
                 "ch": "RCS", "productCode": "SMS"}
                for key, _req_dt in cli_keys
            ]

    from app.services import reconcile

    real_process = reconcile.process_sent_query
    batches: list[int] = []

    def locked_on_second_batch(db, raw_items, **kwargs):
        batches.append(len(raw_items))
        if len(batches) == 2:
            raise RuntimeError("database is locked")
        return real_process(db, raw_items, **kwargs)

    monkeypatch.setattr(reconcile, "process_sent_query", locked_on_second_batch)

    with pytest.raises(RuntimeError, match="database is locked"):
        asyncio.run(
            reconcile_pending_messages(db_session, _AllDoneClient(), older_than_minutes=10)
        )

    assert batches == [10, 1]
    assert calls == ["commit", "thread.updated"]


def test_reconcile_without_settled_messages_does_not_publish(
    db_session, sample_user, monkeypatch
):
    """아직 진행 중(ING)이면 대기 라벨은 그대로라 발행하지 않는다."""
    _reply(db_session, sample_user.sub)
    calls = _record_commits_and_publishes(db_session, monkeypatch)
    client = _QuerySentClient([{"cliKey": _CLI_KEY, "status": "ING"}])

    total = asyncio.run(reconcile_pending_messages(db_session, client, older_than_minutes=10))

    assert total == 0
    assert calls == ["commit"]


@pytest.mark.parametrize("query_status", ["REG", "ING"])
def test_reconcile_publishes_recovered_failure_after_commit_without_done_results(
    db_session, sample_user, monkeypatch, query_status,
):
    """FAILED → 대기도 화면에 보이는 변경이다. 확정 건수가 0이어도 커밋 뒤 알린다."""
    sent_at = (datetime.now(UTC) - timedelta(minutes=30)).isoformat()
    _reply(db_session, sample_user.sub, status="FAILED", sent_at=sent_at)
    request = db_session.execute(select(MsghubRequest)).scalar_one()
    request.error_body = "timeout"
    db_session.commit()
    calls = _record_commits_and_publishes(db_session, monkeypatch)
    client = _QuerySentClient([{"cliKey": _CLI_KEY, "status": query_status}])

    total = asyncio.run(reconcile_pending_messages(db_session, client))

    assert total == 0
    assert calls == ["commit", "thread.updated"]
    assert db_session.execute(select(Message.status)).scalar_one() == query_status
