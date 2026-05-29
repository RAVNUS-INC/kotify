"""웹훅 재조정 (C5) 테스트.

reconcile_pending_messages 가 미완료 메시지를 msghub query_sent 로 조회해 상태를
보정하는지, cutoff(최근 건 제외)·idempotency(DONE 제외)가 동작하는지 검증한다.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from sqlalchemy import select

from app.models import Campaign, Message, MsghubRequest
from app.services.reconcile import _req_dt_kst, reconcile_pending_messages


class _FakeClient:
    """query_sent 만 흉내내는 테스트용 msghub 클라이언트 (덕 타이핑)."""

    def __init__(self, result: list[dict]):
        self._result = result
        self.calls: list = []

    async def query_sent(self, cli_keys):
        self.calls.append(cli_keys)
        return self._result


def _make_pending(db, sub, sent_at, *, status="REG", cli_key="c1-0-0"):
    campaign = Campaign(
        created_by=sub, caller_number="0212345678", message_type="short",
        content="x", total_count=1, pending_count=1, state="DISPATCHED",
        created_at=sent_at,
    )
    db.add(campaign)
    db.flush()
    req = MsghubRequest(campaign_id=campaign.id, chunk_index=0, sent_at=sent_at)
    db.add(req)
    db.flush()
    msg = Message(
        campaign_id=campaign.id, msghub_request_id=req.id,
        to_number="01011112222", to_number_raw="01011112222",
        cli_key=cli_key, status=status,
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
