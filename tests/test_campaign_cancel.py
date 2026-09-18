"""예약 취소 상태 정합성 테스트 (H6).

msghub 가 취소를 거부(이미 발송/취소)하면 로컬 상태를 RESERVE_CANCELED 로
오표기하지 않고 유지해야 한다. 정상 취소만 RESERVE_CANCELED 로 전이한다.
정상 취소는 예약 접수로 대기(PENDING) 중인 메시지도 CANCELED 로 바꾼다.

예약 webReqId 는 수신자 10명 청크(요청)마다 따로라 취소도 청크마다 한다. 일부 청크만
취소되면 캠페인은 RESERVED 로 남고(나머지는 발송될 수 있음) 취소된 청크의 메시지만
CANCELED 가 된다. 청크별 webReqId 이전(alembic 0018)의 여러 청크 예약은 앱에서 취소하지 않는다.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from sqlalchemy import select

from app.models import AuditLog, Campaign, Message, MsghubRequest
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import (
    MsghubBadRequest,
    MsghubError,
    MsghubServerError,
    ReportItem,
)
from app.routes.campaigns import cancel_campaign, get_campaign
from app.services.report import process_report, process_sent_query

_RESERVED_AT = "2026-06-01T03:00:00+00:00"  # 예약 발송은 예약 시각(UTC)을 sent_at 으로 저장


def _reserved_campaign(db, sub, created_at, *, total_count=1, legacy_web_req_id=None):
    """RESERVED 캠페인. legacy_web_req_id 는 청크별 저장(alembic 0018) 이전 발송의 캠페인 값."""
    campaign = Campaign(
        created_by=sub, caller_number="0212345678", message_type="short",
        content="x", total_count=total_count, pending_count=total_count, state="RESERVED",
        created_at=created_at, web_req_id=legacy_web_req_id,
    )
    db.add(campaign)
    db.commit()
    return campaign


def _web_req_id(campaign, chunk_index):
    return f"wr-{campaign.id}-{chunk_index}"


def _add_chunk(db, campaign, chunk_index, statuses, phone_prefix="0101234", *, reserved=True):
    """캠페인에 청크 1개(MsghubRequest) + 상태별 메시지를 붙인다. 반환: cli_key 목록.

    예약 접수된 청크엔 webReqId 가 있다. 요청 단계에서 실패한(FAILED) 청크와 청크별 저장
    이전 발송(reserved=False)은 없다.
    """
    failed_request = "FAILED" in statuses
    req = MsghubRequest(
        campaign_id=campaign.id, chunk_index=chunk_index, sent_at=_RESERVED_AT,
        response_message="fail" if failed_request else None,
        web_req_id=(
            _web_req_id(campaign, chunk_index) if reserved and not failed_request else None
        ),
    )
    db.add(req)
    db.flush()
    keys = []
    for i, status in enumerate(statuses):
        key = f"c{campaign.id}-{chunk_index}-{i}"
        phone = f"{phone_prefix}{chunk_index}{i:03d}"
        db.add(Message(
            campaign_id=campaign.id, msghub_request_id=req.id, to_number=phone,
            to_number_raw=phone, cli_key=key, status=status,
        ))
        keys.append(key)
    db.commit()
    return keys


def _chunked_campaign(db, sub, created_at, sizes=(10, 10, 5)):
    """수신자 25명 = 청크 3개(10·10·5) 예약. 반환: (campaign, 청크별 cli_key 목록)."""
    campaign = _reserved_campaign(db, sub, created_at, total_count=sum(sizes))
    chunks = [_add_chunk(db, campaign, i, ["PENDING"] * n) for i, n in enumerate(sizes)]
    return campaign, chunks


def _statuses(db, campaign):
    return dict(db.execute(
        select(Message.cli_key, Message.status).where(Message.campaign_id == campaign.id)
    ).all())


class _Msghub:
    """cancel_reservation 을 webReqId 별로 흉내낸다 — errors 에 있는 ID 는 그 예외를 던진다."""

    def __init__(self, errors=None):
        self.errors = errors or {}
        self.requested: list[str] = []

    async def cancel_reservation(self, web_req_id, reason=""):
        self.requested.append(web_req_id)
        if web_req_id in self.errors:
            raise self.errors[web_req_id]


def _use_msghub(monkeypatch, errors=None):
    client = _Msghub(errors)
    monkeypatch.setattr("app.main.get_msghub_client", lambda: client)
    return client


@pytest.mark.asyncio
async def test_cancel_rejected_preserves_state(db_session, sample_user, monkeypatch):
    """msghub 가 취소 거부(이미 발송) 시 상태를 RESERVED 로 유지하고 409 반환."""
    campaign = _reserved_campaign(db_session, sample_user.sub, "2026-01-01T00:00:00+00:00")
    _add_chunk(db_session, campaign, 0, ["PENDING"])
    msghub = _use_msghub(
        monkeypatch, {_web_req_id(campaign, 0): MsghubBadRequest("이미 발송됨")}
    )

    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert resp.status_code == 409
    assert msghub.requested == [_web_req_id(campaign, 0)]  # msghub 가 실제로 거부한 경로
    db_session.refresh(campaign)
    assert campaign.state == "RESERVED"  # 취소 오표기 안 됨


@pytest.mark.asyncio
async def test_cancel_success_marks_canceled(db_session, sample_user, monkeypatch):
    """정상 취소는 RESERVE_CANCELED 로 전이한다."""
    campaign = _reserved_campaign(db_session, sample_user.sub, "2026-01-01T00:00:01+00:00")
    _add_chunk(db_session, campaign, 0, ["PENDING"])
    _use_msghub(monkeypatch)

    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    db_session.refresh(campaign)
    assert campaign.state == "RESERVE_CANCELED"
    assert resp["data"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_success_marks_pending_messages_canceled(
    db_session, sample_user, monkeypatch
):
    """정상 취소는 그 캠페인의 대기(PENDING) 메시지만 CANCELED 로 — 발송되지 않을 메시지가
    대화방·수신자 배지에 영영 대기로 보이지 않게. 청크 요청 실패(FAILED)와 다른 예약은 그대로.
    """
    campaign = _reserved_campaign(db_session, sample_user.sub, "2026-01-01T00:00:02+00:00")
    accepted = _add_chunk(db_session, campaign, 0, ["PENDING", "PENDING"])
    failed = _add_chunk(db_session, campaign, 1, ["FAILED"])
    # 같은 번호에 걸린 다른 예약 — 취소 대상이 아니다.
    other = _reserved_campaign(db_session, sample_user.sub, "2026-01-01T00:00:03+00:00")
    other_keys = _add_chunk(db_session, other, 0, ["PENDING"])
    msghub = _use_msghub(monkeypatch)

    await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert msghub.requested == [_web_req_id(campaign, 0)]  # 실패 청크엔 예약이 없다
    assert _statuses(db_session, campaign) == {
        accepted[0]: "CANCELED",
        accepted[1]: "CANCELED",
        failed[0]: "FAILED",
    }
    assert _statuses(db_session, other) == {other_keys[0]: "PENDING"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (MsghubBadRequest("이미 발송됨"), 409),  # 발송됐을 수 있다 — 리포트가 결과를 확정
        (MsghubError("timeout"), 502),
        (httpx.ConnectError("connection refused"), 502),  # 전송 계층 오류도 500 이 아니다
    ],
)
async def test_cancel_failure_keeps_messages_pending(
    db_session, sample_user, monkeypatch, error, status_code
):
    """취소가 거부·실패하면 메시지도 PENDING 그대로 — 재조정·리포트가 계속 결과를 받는다."""
    campaign = _reserved_campaign(db_session, sample_user.sub, "2026-01-01T00:00:04+00:00")
    keys = _add_chunk(db_session, campaign, 0, ["PENDING"])
    _use_msghub(monkeypatch, {_web_req_id(campaign, 0): error})

    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert resp.status_code == status_code
    assert _statuses(db_session, campaign) == {keys[0]: "PENDING"}


# ── 여러 청크 예약 ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multi_chunk_cancel_requests_every_chunk(db_session, sample_user, monkeypatch):
    """25명 예약은 청크 3개의 webReqId 를 모두 취소한다 — 예전엔 마지막 청크(5명)만 취소되고
    앞 20명은 화면에 취소로 보이면서 예약 시각에 발송될 수 있었다."""
    campaign, _ = _chunked_campaign(db_session, sample_user.sub, "2026-01-01T00:00:10+00:00")
    msghub = _use_msghub(monkeypatch)

    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert msghub.requested == [_web_req_id(campaign, i) for i in range(3)]
    assert set(_statuses(db_session, campaign).values()) == {"CANCELED"}
    db_session.refresh(campaign)
    assert campaign.state == "RESERVE_CANCELED"
    assert campaign.pending_count == 0  # 취소는 대기로 세지 않는다
    assert resp["data"] == {
        "id": str(campaign.id), "status": "cancelled", "message": "예약이 취소되었습니다",
    }


@pytest.mark.asyncio
async def test_partial_rejection_keeps_reserved_and_summarizes(
    db_session, sample_user, monkeypatch
):
    """한 청크만 거부(발송 시작) — 거부는 그 청크 사정이라 뒤 청크도 계속 요청하고, 받아들여진
    청크만 취소한다. 캠페인은 RESERVED 로 남는다. 프론트는 200 + 취소가 아닌 상태면 안내를 띄우고
    새로고침한다."""
    campaign, chunks = _chunked_campaign(db_session, sample_user.sub, "2026-01-01T00:00:11+00:00")
    rejected = _web_req_id(campaign, 1)
    msghub = _use_msghub(monkeypatch, {rejected: MsghubBadRequest("이미 발송됨")})

    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert msghub.requested == [_web_req_id(campaign, i) for i in range(3)]
    statuses = _statuses(db_session, campaign)
    assert {statuses[key] for key in chunks[0] + chunks[2]} == {"CANCELED"}
    assert {statuses[key] for key in chunks[1]} == {"PENDING"}
    db_session.refresh(campaign)
    assert campaign.state == "RESERVED"
    assert campaign.pending_count == 10
    assert resp["data"]["status"] == "scheduled"
    assert resp["data"]["message"] == (
        "25명 중 15명의 예약을 취소했습니다. "
        "10명은 취소가 거부되어(이미 발송이 시작됐을 수 있음) 예정대로 발송될 수 있습니다."
    )
    audit = db_session.execute(
        select(AuditLog).where(AuditLog.action == "CANCEL_RESERVE")
    ).scalar_one()
    assert json.loads(audit.detail) == {
        "cancelled": [_web_req_id(campaign, 0), _web_req_id(campaign, 2)],
        "rejected": [rejected],
        "error": None,
    }


@pytest.mark.asyncio
async def test_error_stops_and_retry_requests_only_remaining_chunks(
    db_session, sample_user, monkeypatch
):
    """중간 청크에서 오류가 나면 뒤 청크는 요청하지 않고 멈춘다(오류가 되풀이되기 쉬움). 이미
    취소된 청크는 남고, 다시 누르면 대기 행이 남은 청크만 요청해 전체 취소를 마친다."""
    campaign, _ = _chunked_campaign(db_session, sample_user.sub, "2026-01-01T00:00:12+00:00")
    first = _use_msghub(
        monkeypatch, {_web_req_id(campaign, 1): MsghubServerError("[29012] 일시 오류")}
    )

    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert first.requested == [_web_req_id(campaign, 0), _web_req_id(campaign, 1)]
    assert resp["data"]["status"] == "scheduled"
    assert resp["data"]["message"] == (
        "25명 중 10명의 예약을 취소했습니다. 15명은 오류로 취소하지 못해 예정대로 발송될 수 "
        "있습니다. 다시 시도하면 남은 예약만 취소합니다."
    )

    retry = _use_msghub(monkeypatch)
    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert retry.requested == [_web_req_id(campaign, 1), _web_req_id(campaign, 2)]
    assert set(_statuses(db_session, campaign).values()) == {"CANCELED"}
    db_session.refresh(campaign)
    assert campaign.state == "RESERVE_CANCELED"
    assert resp["data"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_second_cancel_while_first_is_running_is_refused(
    db_session, session_factory, sample_user, monkeypatch
):
    """큰 예약은 청크마다 요청해 오래 걸리고, 프록시 시간 제한을 넘기면 브라우저엔 오류로 보여 다시
    누르게 된다. 두 취소가 같은 청크를 번갈아 요청하면 상대가 취소한 청크를 '거부'로 받아 잘못
    안내하므로 409 로 막는다. 먼저 시작한 취소가 전체를 마무리한다."""
    campaign, _ = _chunked_campaign(db_session, sample_user.sub, "2026-01-01T00:00:16+00:00")
    in_flight = asyncio.Event()
    release = asyncio.Event()

    class _SlowFirstRequest(_Msghub):
        gated = False

        async def cancel_reservation(self, web_req_id, reason=""):
            if not self.gated:
                self.gated = True
                in_flight.set()
                await release.wait()
            await super().cancel_reservation(web_req_id, reason)

    msghub = _SlowFirstRequest()
    monkeypatch.setattr("app.main.get_msghub_client", lambda: msghub)
    first = asyncio.create_task(
        cancel_campaign(str(campaign.id), user=sample_user, db=db_session)
    )
    await asyncio.wait_for(in_flight.wait(), timeout=5)  # 회귀 시 멈추지 않고 실패하게

    second_db = session_factory()  # 다시 누른 요청
    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=second_db)
    second_db.close()

    assert getattr(resp, "status_code", 200) == 409
    assert json.loads(resp.body)["error"]["code"] == "cancel_in_progress"

    release.set()
    resp = await asyncio.wait_for(first, timeout=5)

    assert msghub.requested == [_web_req_id(campaign, i) for i in range(3)]
    assert resp["data"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_partially_cancelled_campaign_completes_when_rest_is_delivered(
    db_session, sample_user, monkeypatch
):
    """일부만 취소돼 RESERVED 에 남은 캠페인도 나머지 리포트가 모두 오면 COMPLETED — 취소 행을
    대기로 세면 대기가 0 이 되지 않아 영영 RESERVED 에 머문다."""
    campaign, chunks = _chunked_campaign(db_session, sample_user.sub, "2026-01-01T00:00:13+00:00")
    _use_msghub(monkeypatch, {_web_req_id(campaign, 2): MsghubBadRequest("이미 발송됨")})
    await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    process_report(db_session, [
        ReportItem(
            msg_key=f"mk-{key}", cli_key=key, ch="RCS", result_code=SUCCESS_CODE,
            result_code_desc="성공", product_code="SMS",
        )
        for key in chunks[2]
    ])
    db_session.commit()

    db_session.refresh(campaign)
    assert campaign.state == "COMPLETED"
    assert (campaign.ok_count, campaign.fail_count, campaign.pending_count) == (5, 0, 0)


@pytest.mark.asyncio
async def test_cancel_finishes_state_left_behind_by_interrupted_attempt(
    db_session, sample_user, monkeypatch
):
    """앞선 시도가 모든 청크를 취소·커밋하고 상태를 바꾸기 전에 멈췄다면, 다시 눌렀을 때
    msghub 에 다시 요청하지 않고 RESERVE_CANCELED 로 마무리한다."""
    campaign = _reserved_campaign(
        db_session, sample_user.sub, "2026-01-01T00:00:14+00:00", total_count=2
    )
    _add_chunk(db_session, campaign, 0, ["CANCELED", "CANCELED"])
    msghub = _use_msghub(monkeypatch)

    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert msghub.requested == []
    db_session.refresh(campaign)
    assert campaign.state == "RESERVE_CANCELED"
    assert resp["data"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_nothing_to_cancel_when_remaining_chunk_is_already_sending(
    db_session, sample_user, monkeypatch
):
    """취소된 청크 말고 남은 청크가 이미 발송 중(REG)이면 요청할 청크가 없다 — 409, 상태 그대로."""
    campaign = _reserved_campaign(
        db_session, sample_user.sub, "2026-01-01T00:00:15+00:00", total_count=2
    )
    _add_chunk(db_session, campaign, 0, ["CANCELED"])
    _add_chunk(db_session, campaign, 1, ["REG"])
    msghub = _use_msghub(monkeypatch)

    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert resp.status_code == 409
    assert json.loads(resp.body)["error"]["code"] == "nothing_to_cancel"
    assert msghub.requested == []
    db_session.refresh(campaign)
    assert campaign.state == "RESERVED"


# ── 청크별 webReqId 이전(레거시) 예약 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_legacy_multi_chunk_reservation_is_not_cancelled_in_app(
    db_session, sample_user, monkeypatch
):
    """캠페인에 마지막 청크 ID 만 남은 여러 청크 예약 — 그 청크만 취소하고 캠페인을 취소로 보이게
    하지 않는다. msghub 를 부르지 않고 409 로 콘솔 취소를 안내하며 상태·메시지는 그대로."""
    campaign = _reserved_campaign(
        db_session, sample_user.sub, "2026-01-01T00:00:20+00:00",
        total_count=15, legacy_web_req_id="wr-last-chunk",
    )
    _add_chunk(db_session, campaign, 0, ["PENDING"] * 10, reserved=False)
    _add_chunk(db_session, campaign, 1, ["PENDING"] * 5, reserved=False)
    msghub = _use_msghub(monkeypatch)

    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert resp.status_code == 409
    body = json.loads(resp.body)
    assert body["error"]["code"] == "legacy_reservation"
    assert "msghub 웹 콘솔" in body["error"]["message"]
    assert msghub.requested == []
    db_session.refresh(campaign)
    assert campaign.state == "RESERVED"
    assert set(_statuses(db_session, campaign).values()) == {"PENDING"}


@pytest.mark.asyncio
async def test_reservation_without_any_web_req_id_is_rejected(
    db_session, sample_user, monkeypatch
):
    """청크에도 캠페인에도 webReqId 가 없으면 취소할 예약이 없다 — 400, msghub 호출 없음."""
    campaign = _reserved_campaign(db_session, sample_user.sub, "2026-01-01T00:00:21+00:00")
    _add_chunk(db_session, campaign, 0, ["PENDING"], reserved=False)
    msghub = _use_msghub(monkeypatch)

    resp = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert resp.status_code == 400
    assert json.loads(resp.body)["error"]["code"] == "no_reservation_id"
    assert msghub.requested == []


@pytest.mark.asyncio
@pytest.mark.parametrize("query_status", [None, "INVALID_KEY", "OVER_DATE"])
async def test_unknown_request_result_is_not_proof_of_full_cancellation(
    db_session, sample_user, monkeypatch, query_status,
):
    """타임아웃 및 재조회 불가 결과는 접수 거부 증거가 아니다. 콘솔 확인 안내가 유지된다."""
    campaign = _reserved_campaign(db_session, sample_user.sub, "2026-01-01T00:00:22+00:00")
    campaign.reserve_time = "2026-06-01 12:00"
    _add_chunk(db_session, campaign, 0, ["CANCELED"])
    keys = _add_chunk(db_session, campaign, 1, ["FAILED"])
    if query_status:
        process_sent_query(db_session, [{"cliKey": keys[0], "status": query_status}])
        db_session.commit()
    msghub = _use_msghub(monkeypatch)

    response = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert response.status_code == 409
    assert json.loads(response.body)["error"]["code"] == "unconfirmed_reservation"
    assert campaign.state == "RESERVED"
    detail = get_campaign(str(campaign.id), db=db_session)["data"]
    assert detail["canCancelReservation"] is False
    assert "1명" in detail["failureReason"]
    assert "msghub 웹 콘솔" in detail["failureReason"]
    assert msghub.requested == []


@pytest.mark.asyncio
async def test_immediate_partial_failure_is_not_a_cancelable_reservation(
    db_session, sample_user, monkeypatch,
):
    campaign = _reserved_campaign(db_session, sample_user.sub, "2026-01-01T00:00:23+00:00")
    campaign.state = "PARTIAL_FAILED"
    _add_chunk(db_session, campaign, 0, ["REG"], reserved=False)
    _add_chunk(db_session, campaign, 1, ["FAILED"])
    msghub = _use_msghub(monkeypatch)

    response = await cancel_campaign(str(campaign.id), user=sample_user, db=db_session)

    assert response.status_code == 400
    assert json.loads(response.body)["error"]["code"] == "not_reserved"
    assert get_campaign(str(campaign.id), db=db_session)["data"]["canCancelReservation"] is False
    assert msghub.requested == []
