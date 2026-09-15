"""예약 취소된 메시지 — 대화방·캠페인 수신자 배지·재조정·리포트 매칭·마이그레이션 0017.

예약 취소가 캠페인만 RESERVE_CANCELED 로 바꾸고 메시지를 PENDING 으로 남겨, 발송되지 않을
메시지가 대화방 말풍선(`SMS · 대기`)과 수신자 배지(대기)에 영영 대기로 보이고 재조정이 매
주기 msghub 에 조회했다. 이제 취소 라우트가 PENDING 을 CANCELED 로 바꾸고(기존 행은 alembic
0017), 소비처는 이 상태를 본다.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import select

from app.models import AuditLog, Campaign, Message, MsghubRequest
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import ReportItem
from app.routes.campaigns import cancel_campaign, get_campaign
from app.routes.threads import api_get_thread
from app.services.reconcile import reconcile_pending_messages
from app.services.report import process_report

_ROOT = Path(__file__).resolve().parents[1]
_CALLER = "0212345678"
_PHONE = "01055556666"
_TID = f"{_CALLER}:{_PHONE}"
_RESERVED_AT = "2026-06-01T03:00:00+00:00"  # 예약 시각(UTC) — 예약 발송의 msghub_requests.sent_at


def _campaign(
    db, sub, *, key, chunks, state="RESERVED", created_at="2026-05-31T00:00:00+00:00",
    cli_keys=True,
):
    """캠페인 1개. chunks = 청크별 메시지 상태 목록. 첫 수신자만 _PHONE(대화방 대상)."""
    total = sum(len(statuses) for statuses in chunks)
    campaign = Campaign(
        created_by=sub, caller_number=_CALLER, message_type="short",
        content="9월 정기 점검 안내", total_count=total, pending_count=total, state=state,
        created_at=created_at, reserve_time="2026-06-01 12:00", web_req_id=f"wr-{key}",
        rcs_messagebase_id="RPSSAXX001",
    )
    db.add(campaign)
    db.flush()
    n = 0
    for chunk_index, statuses in enumerate(chunks):
        req = MsghubRequest(
            campaign_id=campaign.id, chunk_index=chunk_index, sent_at=_RESERVED_AT
        )
        db.add(req)
        db.flush()
        for i, status in enumerate(statuses):
            phone = _PHONE if n == 0 else f"0107777{n:04d}"
            db.add(Message(
                campaign_id=campaign.id, msghub_request_id=req.id, to_number=phone,
                to_number_raw=phone, status=status,
                cli_key=f"{key}-{chunk_index}-{i}" if cli_keys else None,
            ))
            n += 1
    db.commit()
    return campaign


def _statuses(db, campaign):
    return list(db.execute(
        select(Message.status)
        .where(Message.campaign_id == campaign.id)
        .order_by(Message.id)
    ).scalars())


def _status(db, cli_key):
    return db.execute(
        select(Message.status).where(Message.cli_key == cli_key)
    ).scalar_one()


def _report(*, cli_key="", phone=_PHONE):
    return ReportItem(
        msg_key=f"mk-{cli_key}" if cli_key else "", cli_key=cli_key, ch="RCS",
        result_code=SUCCESS_CODE, result_code_desc="성공", product_code="SMS", phone=phone,
    )


class _MsghubStub:
    """예약 취소는 받아들이고, 재조정 조회(query_sent)는 요청한 cliKey 만 기록한다."""

    def __init__(self):
        self.queried: list[str] = []

    async def cancel_reservation(self, web_req_id, reason=""):
        return None

    async def query_sent(self, cli_keys):
        self.queried.extend(key for key, _req_dt in cli_keys)
        return []


@pytest.fixture
def msghub(monkeypatch):
    stub = _MsghubStub()
    monkeypatch.setattr("app.main.get_msghub_client", lambda: stub)
    return stub


# ── 취소 → 대화방·수신자 배지 ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancelled_reservation_reads_cancelled_in_thread_and_recipients(
    db_session, sample_user, msghub
):
    cancelled = _campaign(
        db_session, sample_user.sub, key="resv-a", chunks=[["PENDING", "PENDING"]],
        created_at="2026-05-31T00:00:00+00:00",
    )
    _campaign(
        db_session, sample_user.sub, key="resv-b", chunks=[["PENDING"]],
        created_at="2026-05-31T01:00:00+00:00",
    )

    await cancel_campaign(str(cancelled.id), user=sample_user, db=db_session)

    # 같은 고객에게 걸린 두 예약 — 취소분은 취소, 살아 있는 예약은 여전히 대기.
    messages = api_get_thread(_TID, db=db_session)["data"]["messages"]
    assert [(m["side"], m["status"]) for m in messages] == [
        ("us", "cancelled"),
        ("us", "pending"),
    ]

    # 캠페인 상세 — 상태 배지와 수신자 배지가 같은 취소로 읽힌다. 발송 시각은 없다.
    detail = get_campaign(str(cancelled.id), db=db_session)["data"]
    assert detail["status"] == "cancelled"
    assert [r["status"] for r in detail["recipientsSample"]] == ["cancelled", "cancelled"]
    assert all("sentAt" not in r for r in detail["recipientsSample"])


# ── 재조정·리포트 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconcile_stops_querying_cancelled_reservation(db_session, sample_user, msghub):
    """예약 시각이 지나도 취소분은 msghub 에 조회하지 않는다 — 살아 있는 예약만 조회."""
    cancelled = _campaign(db_session, sample_user.sub, key="resv-c", chunks=[["PENDING"]])
    _campaign(db_session, sample_user.sub, key="resv-d", chunks=[["PENDING"]])

    await cancel_campaign(str(cancelled.id), user=sample_user, db=db_session)
    await reconcile_pending_messages(db_session, msghub, older_than_minutes=10)

    assert msghub.queried == ["resv-d-0-0"]


def test_phone_only_report_is_not_held_by_cancelled_message(db_session, sample_user):
    """같은 번호의 취소분은 phone 보조매칭 후보가 아니다 — 모호성 보류 없이 남은 발송 1건에 붙는다."""
    _campaign(
        db_session, sample_user.sub, key="resv-e", chunks=[["CANCELED"]],
        state="RESERVE_CANCELED",
    )
    _campaign(db_session, sample_user.sub, key="send-f", chunks=[["REG"]], state="DISPATCHED")

    processed, _ = process_report(db_session, [_report(phone=_PHONE)])

    assert processed == 1
    assert _status(db_session, "send-f-0-0") == "DONE"
    assert _status(db_session, "resv-e-0-0") == "CANCELED"


def test_delivery_report_replaces_cancelled_when_msghub_sent_it(db_session, sample_user):
    """캠페인엔 마지막 청크의 webReqId 만 저장돼 앞 청크엔 취소가 닿지 않을 수 있다. 그 청크가
    실제 발송돼 리포트가 오면 CANCELED 를 덮어 전달 결과를 남긴다 — 받은 메시지를 취소로 두지 않는다.
    """
    _campaign(
        db_session, sample_user.sub, key="resv-g", chunks=[["CANCELED"], ["CANCELED"]],
        state="RESERVE_CANCELED",
    )

    process_report(db_session, [_report(cli_key="resv-g-0-0")])

    assert _status(db_session, "resv-g-0-0") == "DONE"
    assert _status(db_session, "resv-g-1-0") == "CANCELED"
    messages = api_get_thread(_TID, db=db_session)["data"]["messages"]
    assert [m["status"] for m in messages] == ["sent"]


# ── alembic 0017: 기존 행 정리 ───────────────────────────────────────────────


def _alembic_scripts() -> ScriptDirectory:
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "alembic"))
    return ScriptDirectory.from_config(cfg)


def _run_0017(db, step):
    """0017 의 upgrade/downgrade 를 테스트 DB 에서 실행 — 데이터만 바꾸므로 현재 모델 스키마로 충분."""
    module = _alembic_scripts().get_revision("0017").module
    with Operations.context(MigrationContext.configure(db.connection())):
        getattr(module, step)()
    db.commit()


def _cancel_audit(db, sub, campaign, created_at):
    db.add(AuditLog(
        actor_sub=sub, action="CANCEL_RESERVE", target=f"campaign:{campaign.id}",
        detail='{"web_req_id": "wr"}', created_at=created_at,
    ))
    db.commit()


def test_migration_0017_is_the_single_head_after_0016():
    scripts = _alembic_scripts()
    assert scripts.get_heads() == ["0017"]
    assert scripts.get_revision("0017").down_revision == "0016"


def test_migration_0017_moves_only_reservations_cancelled_before_send(db_session, sample_user):
    sub = sample_user.sub
    before_send = "2026-06-01T02:40:00.123456+00:00"  # 예약 20분 전 — msghub 가 받아들인 취소
    after_send = "2026-06-01T03:05:00.654321+00:00"   # 예약 뒤 — H6 전엔 거부돼도 취소로 커밋

    accepted = _campaign(
        db_session, sub, key="m-ok", chunks=[["PENDING", "PENDING"], ["FAILED"]],
        state="RESERVE_CANCELED",
    )
    _cancel_audit(db_session, sub, accepted, before_send)
    ncp = _campaign(
        db_session, sub, key="m-ncp", chunks=[["PENDING"]], state="RESERVE_CANCELED",
        cli_keys=False,
    )
    _cancel_audit(db_session, sub, ncp, before_send)
    partly_sent = _campaign(
        db_session, sub, key="m-part", chunks=[["DONE"], ["PENDING"]],
        state="RESERVE_CANCELED",
    )
    _cancel_audit(db_session, sub, partly_sent, before_send)
    rejected = _campaign(
        db_session, sub, key="m-h6", chunks=[["PENDING"]], state="RESERVE_CANCELED"
    )
    _cancel_audit(db_session, sub, rejected, after_send)
    unaudited = _campaign(
        db_session, sub, key="m-noaudit", chunks=[["PENDING"]], state="RESERVE_CANCELED"
    )
    reserved = _campaign(db_session, sub, key="m-live", chunks=[["PENDING"]])

    _run_0017(db_session, "upgrade")

    assert _statuses(db_session, accepted) == ["CANCELED", "CANCELED", "FAILED"]
    assert _statuses(db_session, ncp) == ["CANCELED"]
    assert _statuses(db_session, partly_sent) == ["DONE", "CANCELED"]
    # 발송됐을 수 있는 H6 행·근거 없는 행·살아 있는 예약은 PENDING 그대로.
    assert _statuses(db_session, rejected) == ["PENDING"]
    assert _statuses(db_session, unaudited) == ["PENDING"]
    assert _statuses(db_session, reserved) == ["PENDING"]

    _run_0017(db_session, "upgrade")  # 멱등
    assert _statuses(db_session, accepted) == ["CANCELED", "CANCELED", "FAILED"]

    _run_0017(db_session, "downgrade")

    assert _statuses(db_session, accepted) == ["PENDING", "PENDING", "FAILED"]
    assert _statuses(db_session, ncp) == ["PENDING"]
    assert _statuses(db_session, partly_sent) == ["DONE", "PENDING"]
    assert _statuses(db_session, rejected) == ["PENDING"]
