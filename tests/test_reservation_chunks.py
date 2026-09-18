"""예약 발송의 청크별 webReqId — 발송 저장, RCS 대체 발송의 예약 유지, 발송→취소, alembic 0018.

msghub 는 예약 요청(수신자 10명 청크)마다 webReqId 를 따로 발급하고 취소도 그 단위다. 발송
루프가 캠페인 한 칸에 덮어써 마지막 청크 ID 만 남던 문제와, RCS 요청이 거부된 청크의 직접
발송이 예약 파라미터 없이 즉시 나가던 문제를 고정한다.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Campaign, Message, MsghubRequest
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import (
    MsghubAuthError,
    MsghubBadRequest,
    MsghubRateLimited,
    MsghubServerError,
    ReportItem,
    ReserveResponse,
    SendResponse,
    SendResultItem,
)
from app.routes.campaigns import cancel_campaign, get_campaign
from app.services.compose import dispatch_campaign
from app.services.report import process_report

_ROOT = Path(__file__).resolve().parents[1]
_KST = ZoneInfo("Asia/Seoul")
_RECIPIENTS = [f"010{n:08d}" for n in range(25)]  # 청크 3개(10·10·5)


def _reserve_at() -> str:
    """dispatch 가 받아들이는 예약 시각(KST 'YYYY-MM-DD HH:MM', 최소 10분 뒤) — 하루 뒤."""
    return (datetime.now(_KST) + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")


class _ReservingMsghub:
    """예약 요청마다 webReqId 를 새로 발급한다. rcs_errors[n] 이면 n 번째 RCS 요청이 그 예외."""

    def __init__(self, rcs_errors=None):
        self.rcs_errors = rcs_errors or {}
        self.rcs_calls = 0
        self.issued: list[str] = []         # 발급한 webReqId, 요청 순서
        self.direct_calls: list[dict] = []  # 직접 발송(SMS/MMS) 요청
        self.cancelled: list[str] = []

    def _accept(self, channel, recv_list, resv_yn):
        if resv_yn == "Y":
            web_req_id = f"{channel}{len(self.issued)}"
            self.issued.append(web_req_id)
            return ReserveResponse(code=SUCCESS_CODE, message="성공", web_req_id=web_req_id)
        return SendResponse(code=SUCCESS_CODE, message="성공", items=[
            SendResultItem(
                cli_key=r.cli_key, msg_key=f"mk-{r.cli_key}", phone=r.phone,
                code=SUCCESS_CODE, message="성공",
            )
            for r in recv_list
        ])

    def _record_direct(self, recv_list, resv_yn, resv_req_dt):
        self.direct_calls.append({
            "cli_keys": [r.cli_key for r in recv_list],
            "resv_yn": resv_yn,
            "resv_req_dt": resv_req_dt,
        })

    async def send_rcs(self, *, recv_list, resv_yn=None, **_kwargs):
        n = self.rcs_calls
        self.rcs_calls += 1
        if n in self.rcs_errors:
            raise self.rcs_errors[n]
        return self._accept("RCS", recv_list, resv_yn)

    async def send_sms(self, *, callback, msg, recv_list, resv_yn=None, resv_req_dt=None):
        self._record_direct(recv_list, resv_yn, resv_req_dt)
        return self._accept("SMS", recv_list, resv_yn)

    async def send_mms(
        self, *, callback, title, msg, recv_list,
        file_id_lst=None, resv_yn=None, resv_req_dt=None,
    ):
        self._record_direct(recv_list, resv_yn, resv_req_dt)
        return self._accept("MMS", recv_list, resv_yn)

    async def cancel_reservation(self, web_req_id, reason=""):
        self.cancelled.append(web_req_id)


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    """29002 재시도 전 30초 대기를 건너뛴다."""
    async def _instant(_seconds):
        return None
    monkeypatch.setattr("app.services.compose.asyncio.sleep", _instant)


async def _dispatch(db, client, user, caller, **kwargs):
    return await dispatch_campaign(
        db=db, msghub_client=client, created_by=user.sub, caller_number=caller.number,
        content="9월 정기 점검 안내", recipients=list(_RECIPIENTS), message_type="SMS",
        **kwargs,
    )


def _requests(db, campaign):
    return db.execute(
        select(MsghubRequest)
        .where(MsghubRequest.campaign_id == campaign.id)
        .order_by(MsghubRequest.chunk_index)
    ).scalars().all()


# ── 발송 ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("send_channel", ["rcs", "sms"])
async def test_reserved_dispatch_stores_web_req_id_per_chunk(
    db_session, sample_user, sample_caller, send_channel
):
    """청크마다 받은 webReqId 를 그 청크(요청)에 저장한다 — 캠페인 한 칸에 덮어쓰지 않는다."""
    client = _ReservingMsghub()

    campaign = await _dispatch(
        db_session, client, sample_user, sample_caller,
        reserve_time_local=_reserve_at(), send_channel=send_channel,
    )

    assert len(client.issued) == 3
    assert [r.web_req_id for r in _requests(db_session, campaign)] == client.issued
    assert campaign.web_req_id is None  # 레거시 칸 — 새 발송은 쓰지 않는다
    assert campaign.state == "RESERVED"


@pytest.mark.asyncio
async def test_immediate_dispatch_stores_no_web_req_id(db_session, sample_user, sample_caller):
    """즉시 발송엔 예약이 없다 — 취소 라우트가 요청할 webReqId 를 남기지 않는다."""
    client = _ReservingMsghub()

    campaign = await _dispatch(db_session, client, sample_user, sample_caller, send_channel="rcs")

    assert client.issued == []
    assert [r.web_req_id for r in _requests(db_session, campaign)] == [None, None, None]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        MsghubRateLimited("[29002] CPS 초과", code="29002", status_code=400),
        MsghubBadRequest("[29003] RCS 설정 오류", code="29003", status_code=400),
    ],
)
async def test_rejected_rcs_chunk_falls_back_as_a_reservation(
    db_session, sample_user, sample_caller, error
):
    """RCS 요청이 거부된 청크의 직접 발송도 같은 예약 시각으로 접수한다 — 예전엔 예약 파라미터
    없이 그 청크만 즉시 발송됐다. 예약 응답엔 수신자 item 이 없어 행의 cliKey 를 다시 만드는데,
    보낸 -fb 키와 같아야 리포트가 붙는다."""
    reserve_at = _reserve_at()
    client = _ReservingMsghub(rcs_errors={1: error})

    campaign = await _dispatch(
        db_session, client, sample_user, sample_caller,
        reserve_time_local=reserve_at, send_channel="rcs",
    )

    assert [(c["resv_yn"], c["resv_req_dt"]) for c in client.direct_calls] == [("Y", reserve_at)]
    requests = _requests(db_session, campaign)
    assert [r.web_req_id for r in requests] == client.issued  # RCS0, SMS1, RCS2
    assert len({r.sent_at for r in requests}) == 1  # 대체 청크도 예약 시각(UTC)
    assert campaign.state == "RESERVED"

    fallback_rows = db_session.execute(
        select(Message).where(Message.msghub_request_id == requests[1].id).order_by(Message.id)
    ).scalars().all()
    assert [m.cli_key for m in fallback_rows] == client.direct_calls[0]["cli_keys"]
    assert all(m.cli_key.endswith("-fb") and m.status == "PENDING" for m in fallback_rows)

    processed, _ = process_report(db_session, [ReportItem(
        msg_key="mk-fb", cli_key=fallback_rows[0].cli_key, ch="SMS",
        result_code=SUCCESS_CODE, result_code_desc="성공", product_code="SMS",
    )])
    assert processed == 1
    assert fallback_rows[0].status == "DONE"


@pytest.mark.asyncio
async def test_cancel_waits_while_reservation_dispatch_is_in_flight(
    db_session, session_factory, sample_user, sample_caller, monkeypatch
):
    """접수(청크 발송) 도중의 취소는 409 — 이미 접수된 청크 행만 보고 전체 취소로 마무리하면 아직
    접수되지 않은 청크가 예약 시각에 발송되면서 캠페인은 취소로 보인다. 발송 요청이 프록시 시간
    제한을 넘어 오류로 보이고 멱등 재요청이 곧바로 '예약'을 돌려주면 사용자가 바로 취소할 수 있다.
    접수가 끝난 뒤엔 모든 청크를 취소한다."""
    in_flight = asyncio.Event()
    release = asyncio.Event()

    class _SlowSecondChunk(_ReservingMsghub):
        async def send_rcs(self, **kwargs):
            if self.rcs_calls == 1:
                in_flight.set()
                await release.wait()
            return await super().send_rcs(**kwargs)

    client = _SlowSecondChunk()
    monkeypatch.setattr("app.main.get_msghub_client", lambda: client)
    dispatch = asyncio.create_task(_dispatch(
        db_session, client, sample_user, sample_caller,
        reserve_time_local=_reserve_at(), send_channel="rcs",
    ))
    await asyncio.wait_for(in_flight.wait(), timeout=5)  # 회귀 시 멈추지 않고 실패하게

    cancel_db = session_factory()  # 다른 요청 — 첫 청크는 이미 커밋돼 보인다
    campaign_id = cancel_db.execute(select(Campaign.id)).scalar_one()
    resp = await cancel_campaign(str(campaign_id), user=sample_user, db=cancel_db)
    cancel_db.close()

    assert getattr(resp, "status_code", 200) == 409
    assert json.loads(resp.body)["error"]["code"] == "dispatch_in_progress"
    assert client.cancelled == []

    release.set()
    campaign = await asyncio.wait_for(dispatch, timeout=5)
    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert client.cancelled == client.issued
    assert len(client.issued) == 3
    assert resp["data"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_dispatch_aborted_by_auth_error_can_still_be_cancelled(
    db_session, sample_user, sample_caller, monkeypatch
):
    """인증 오류로 발송이 중단되면 뒤 청크는 행조차 없이 RESERVED 로 남는다 — 진행 중 표시는
    풀려야 하고, 접수된 청크만 취소하면 발송될 행이 없어 전체 취소로 마무리된다."""
    client = _ReservingMsghub(
        rcs_errors={1: MsghubAuthError("[20001] 인증 실패", code="20001", status_code=401)}
    )
    monkeypatch.setattr("app.main.get_msghub_client", lambda: client)
    with pytest.raises(MsghubAuthError):
        await _dispatch(
            db_session, client, sample_user, sample_caller,
            reserve_time_local=_reserve_at(), send_channel="rcs",
        )
    campaign = db_session.execute(select(Campaign)).scalar_one()
    assert campaign.state == "RESERVED"

    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert client.cancelled == ["RCS0"]  # 청크 1 은 실패 행, 청크 2 는 접수되지 않음
    assert resp["data"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_dispatched_reservation_cancels_every_chunk(
    db_session, sample_user, sample_caller, monkeypatch
):
    """발송→취소 전 구간: 대체 발송 청크가 섞인 25명 예약을 취소하면 발급된 webReqId 를 모두
    취소하고 모든 수신자가 취소로 남는다."""
    client = _ReservingMsghub(
        rcs_errors={1: MsghubBadRequest("[29003] RCS 설정 오류", code="29003", status_code=400)}
    )
    monkeypatch.setattr("app.main.get_msghub_client", lambda: client)
    campaign = await _dispatch(
        db_session, client, sample_user, sample_caller,
        reserve_time_local=_reserve_at(), send_channel="rcs",
    )

    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert client.cancelled == client.issued
    assert resp["data"]["status"] == "cancelled"
    statuses = db_session.execute(
        select(Message.status).where(Message.campaign_id == campaign.id)
    ).scalars().all()
    assert statuses == ["CANCELED"] * len(_RECIPIENTS)


# ── 일부 청크 요청 실패 후 예약 취소 ─────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(("failure", "uncertain"), [
    pytest.param(
        MsghubBadRequest("수신 요청 거부", code="29003", status_code=400),
        False, id="explicit-rejection",
    ),
    pytest.param(httpx.ReadTimeout("예약 접수 응답 유실"), True, id="timeout"),
    pytest.param(
        MsghubServerError("서버 오류", code="HTTP_ERROR", status_code=500),
        True, id="server-error",
    ),
    pytest.param(
        MsghubServerError("응답 파싱 오류", code="PARSE_ERROR", status_code=200),
        True, id="invalid-response",
    ),
])
async def test_partially_failed_reservation_can_cancel_accepted_chunks(
    db_session, sample_user, sample_caller, monkeypatch, failure, uncertain,
):
    """청크 하나가 실패해도 접수된 예약은 취소한다. 응답 유실은 전체 취소로 단정하지 않는다."""
    class _OneFailedChunk(_ReservingMsghub):
        calls = 0

        async def send_sms(self, **kwargs):
            chunk_index = self.calls
            self.calls += 1
            if chunk_index == 1:
                raise failure
            return await super().send_sms(**kwargs)

    client = _OneFailedChunk()
    monkeypatch.setattr("app.main.get_msghub_client", lambda: client)
    campaign = await _dispatch(
        db_session, client, sample_user, sample_caller,
        reserve_time_local=_reserve_at(), send_channel="sms",
    )
    assert campaign.state == "PARTIAL_FAILED"
    failed_request = _requests(db_session, campaign)[1]
    assert failed_request.response_code == (None if uncertain else "29003")
    before = get_campaign(str(campaign.id), db=db_session)["data"]

    response = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert client.cancelled == client.issued  # 기존엔 not_reserved 400, 취소 호출 0회
    assert len(client.cancelled) == 2
    assert before["canCancelReservation"] is True
    statuses = db_session.scalars(select(Message.status)).all()
    assert statuses.count("CANCELED") == 15
    assert statuses.count("FAILED") == 10
    after = get_campaign(str(campaign.id), db=db_session)["data"]
    assert after["canCancelReservation"] is False
    if uncertain:
        assert response["data"]["status"] != "cancelled"
        assert campaign.state == "RESERVED"
        assert campaign.completed_at is None
        assert "10명" in after["failureReason"]
        assert "msghub 웹 콘솔" in after["failureReason"]
        assert "10명" in response["data"]["message"]
        assert "msghub 웹 콘솔" in response["data"]["message"]
        retry = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)
        assert retry.status_code == 409
        assert json.loads(retry.body)["error"]["code"] == "unconfirmed_reservation"
        assert client.cancelled == client.issued  # 취소한 청크를 다시 요청하지 않는다
    else:
        assert response["data"]["status"] == "cancelled"
        assert campaign.state == "RESERVE_CANCELED"


@pytest.mark.asyncio
async def test_interrupted_reservation_does_not_hide_accepted_but_unconfirmed_chunk(
    db_session, sample_user, sample_caller, monkeypatch,
):
    """타임아웃 뒤 인증 오류로 중단돼 RESERVED 가 남아도, 불확실 청크는 취소 확정하지 않는다."""
    client = _ReservingMsghub(rcs_errors={
        1: httpx.ReadTimeout("예약 접수 응답 유실"),
        2: MsghubAuthError("인증 실패", code="20001", status_code=401),
    })
    monkeypatch.setattr("app.main.get_msghub_client", lambda: client)
    with pytest.raises(MsghubAuthError):
        await _dispatch(
            db_session, client, sample_user, sample_caller,
            reserve_time_local=_reserve_at(), send_channel="rcs",
        )
    campaign = db_session.scalar(select(Campaign))
    assert campaign.state == "RESERVED"

    response = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert client.cancelled == ["RCS0"]
    assert response["data"]["status"] != "cancelled"
    assert campaign.state != "RESERVE_CANCELED"
    assert "10명" in response["data"]["message"]
    assert "msghub 웹 콘솔" in response["data"]["message"]


# ── alembic 0018 ─────────────────────────────────────────────────────────────


def _alembic_scripts() -> ScriptDirectory:
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "alembic"))
    return ScriptDirectory.from_config(cfg)


def _run_0018(conn, step):
    module = _alembic_scripts().get_revision("0018").module
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, step)()


def _campaign_with_chunks(db, *, web_req_id, chunks):
    campaign = Campaign(
        created_by="u1", caller_number="0212345678", message_type="short", content="x",
        total_count=chunks, state="RESERVED", created_at="2026-05-31T00:00:00+00:00",
        web_req_id=web_req_id,
    )
    db.add(campaign)
    db.flush()
    for chunk_index in range(chunks):
        db.add(MsghubRequest(
            campaign_id=campaign.id, chunk_index=chunk_index,
            sent_at="2026-06-01T03:00:00+00:00",
        ))
    db.flush()
    return campaign.id


def _chunk_ids(conn, campaign_id):
    return list(conn.exec_driver_sql(
        "SELECT web_req_id FROM msghub_requests WHERE campaign_id = ? ORDER BY chunk_index",
        (campaign_id,),
    ).scalars())


def _campaign_id_value(conn, campaign_id):
    return conn.exec_driver_sql(
        "SELECT web_req_id FROM campaigns WHERE id = ?", (campaign_id,)
    ).scalar_one()


def test_migration_0018_follows_0017():
    scripts = _alembic_scripts()
    assert scripts.get_revision("0018").down_revision == "0017"


def test_migration_0018_moves_campaign_id_only_where_the_chunk_is_certain():
    """upgrade: 요청이 1개뿐인 캠페인만 캠페인 값을 그 청크로 옮긴다 — 여러 청크 캠페인은 값이
    어느 청크 것인지 확정할 수 없다. downgrade: 새 발송 캠페인엔 마지막 청크 ID 를 캠페인 칸에
    되돌리고(이전 코드의 표현) 청크 칸을 지운다."""
    # FK 검사를 켜지 않은 별도 엔진 — SQLite batch drop_column 은 테이블을 다시 만든다.
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        single = _campaign_with_chunks(db, web_req_id="wr-single", chunks=1)
        multi = _campaign_with_chunks(db, web_req_id="wr-last", chunks=3)
        immediate = _campaign_with_chunks(db, web_req_id=None, chunks=1)
        dispatched_after = _campaign_with_chunks(db, web_req_id=None, chunks=3)
        db.commit()

    with engine.begin() as conn:
        conn.exec_driver_sql("ALTER TABLE msghub_requests DROP COLUMN web_req_id")  # 0017 스키마

        _run_0018(conn, "upgrade")

        assert _chunk_ids(conn, single) == ["wr-single"]
        assert _chunk_ids(conn, multi) == [None, None, None]
        assert _chunk_ids(conn, immediate) == [None]

        # 0018 뒤 발송 — 청크마다 ID, 캠페인 칸은 비어 있다.
        conn.exec_driver_sql(
            "UPDATE msghub_requests SET web_req_id = 'wr-new-' || chunk_index "
            "WHERE campaign_id = ?",
            (dispatched_after,),
        )

        _run_0018(conn, "downgrade")

        assert _campaign_id_value(conn, dispatched_after) == "wr-new-2"
        assert _campaign_id_value(conn, single) == "wr-single"
        assert _campaign_id_value(conn, multi) == "wr-last"
        assert _campaign_id_value(conn, immediate) is None
        columns = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(msghub_requests)")]
        assert "web_req_id" not in columns
    engine.dispose()
