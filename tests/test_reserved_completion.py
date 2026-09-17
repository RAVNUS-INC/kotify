"""예약(RESERVED) 캠페인 완료 경로 검증 (H5).

예약 발송 직후 캠페인은 state=RESERVED, 메시지는 status=PENDING 으로 남는다
(send_rcs resv_yn=Y → ReserveResponse → _create_messages_from_response 의 PENDING
분기). 예약 시각이 도래해 msghub 가 실제 발송하고 배달 결과가 돌아오면, 캠페인은
RESERVED 에서 벗어나 COMPLETED/PARTIAL_FAILED/FAILED 로 전이돼야 한다 ("영구 RESERVED"
방지).

이 전이는 _refresh_campaign_counters(report.py) 의 전이 대상 state 목록에
"RESERVED" 가 포함돼 있어 추가 코드 없이 동작한다. 또한 reconcile 는 캠페인
state 가 아니라 "메시지 status + sent_at" 으로만 필터하므로 예약 캠페인의 PENDING
도 자연히 대상이 된다. 본 테스트는 이 암묵적 보장을 웹훅·재조정 양쪽에서 고정한다.

예약 요청이 예외라 RESERVE_FAILED 로 기록했어도 msghub 가 실제로 예약했다면 예약 시각에
리포트가 온다 — 그때도 state 가 리포트를 따라야 한다.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.models import Campaign, Message, MsghubRequest
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import ReportItem
from app.services.compose import dispatch_campaign
from app.services.reconcile import reconcile_pending_messages
from app.services.report import process_report


class _FakeClient:
    """query_sent 만 흉내내는 테스트 클라이언트 (test_reconcile 와 동일 패턴)."""

    def __init__(self, result: list[dict]):
        self._result = result
        self.calls: list = []

    async def query_sent(self, cli_keys):
        self.calls.append(cli_keys)
        return self._result


def _make_reserved(db, sub, *, sent_at, statuses, cli_prefix="resv"):
    """RESERVED 캠페인 1개 + 주어진 상태의 메시지들을 만들어 (campaign, cli_keys) 반환."""
    n = len(statuses)
    campaign = Campaign(
        created_by=sub, caller_number="0212345678", message_type="short",
        content="예약 안내", total_count=n, pending_count=n,
        state="RESERVED", created_at="2026-01-01T00:00:00+00:00",
        reserve_time="2026-06-01 12:00",
    )
    db.add(campaign)
    db.flush()
    req = MsghubRequest(campaign_id=campaign.id, chunk_index=0, sent_at=sent_at)
    db.add(req)
    db.flush()
    keys = []
    for i, status in enumerate(statuses):
        key = f"{cli_prefix}-{campaign.id}-{i}"
        db.add(Message(
            campaign_id=campaign.id, msghub_request_id=req.id,
            to_number=f"0100000000{i}", to_number_raw=f"0100000000{i}",
            cli_key=key, msg_key=None, status=status,
        ))
        keys.append(key)
    db.commit()
    return campaign, keys


def _done_report(cli_key, phone, result_code=SUCCESS_CODE):
    return ReportItem(
        msg_key=f"mk-{cli_key}", cli_key=cli_key, ch="RCS",
        result_code=result_code, result_code_desc="결과", product_code="SMS",
        phone=phone,
    )


def test_reserved_completes_via_webhook(db_session, sample_user):
    """RESERVED 캠페인의 PENDING 메시지가 배달 리포트로 전건 DONE → COMPLETED."""
    campaign, keys = _make_reserved(
        db_session, sample_user.sub,
        sent_at="2026-06-01T03:00:00+00:00", statuses=["PENDING", "PENDING"],
    )

    process_report(db_session, [
        _done_report(keys[0], "01000000000"),
        _done_report(keys[1], "01000000001"),
    ])

    assert campaign.state == "COMPLETED"  # 영구 RESERVED 아님
    assert campaign.pending_count == 0
    assert campaign.ok_count == 2


def test_reserved_partial_failure_via_webhook(db_session, sample_user):
    """일부 item 실패 시 RESERVED → PARTIAL_FAILED (역시 RESERVED 에서 벗어남)."""
    campaign, keys = _make_reserved(
        db_session, sample_user.sub,
        sent_at="2026-06-01T03:00:00+00:00", statuses=["PENDING", "PENDING"],
    )

    process_report(db_session, [
        _done_report(keys[0], "01000000000"),
        _done_report(keys[1], "01000000001", result_code="29002"),  # 실패 코드
    ])

    assert campaign.state == "PARTIAL_FAILED"
    assert campaign.pending_count == 0
    assert campaign.ok_count == 1
    assert campaign.fail_count == 1


def test_reserved_all_failed_via_webhook(db_session, sample_user):
    """전건 실패면 RESERVED → FAILED — 성공이 0 인데 PARTIAL_FAILED("일부 실패")가 아니다."""
    campaign, keys = _make_reserved(
        db_session, sample_user.sub,
        sent_at="2026-06-01T03:00:00+00:00", statuses=["PENDING", "PENDING"],
    )

    process_report(db_session, [
        _done_report(keys[0], "01000000000", result_code="29002"),
        _done_report(keys[1], "01000000001", result_code="29002"),
    ])

    assert campaign.state == "FAILED"
    assert (campaign.pending_count, campaign.ok_count, campaign.fail_count) == (0, 0, 2)


class _TimeoutRcsClient:
    """msghub 는 예약을 접수했지만 응답을 못 받은 경우 — send_rcs 가 예외를 던진다."""

    async def send_rcs(self, **kwargs):
        raise httpx.ReadTimeout("응답 대기 시간 초과")


@pytest.mark.asyncio
async def test_reserve_failed_follows_reports_of_reservation_that_went_through(
    db_session, sample_user, sample_caller,
):
    """RESERVE_FAILED 로 기록한 예약이 실제로 발송돼 리포트가 오면 state 가 그 결과를 따른다 —
    "예약 실패 · 재시도 필요" 로 남으면 사용자가 다시 보내 중복 발송하게 된다."""
    reserve_at = (datetime.now(ZoneInfo("Asia/Seoul")) + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
    recipients = ["01000000001", "01000000002"]
    campaign = await dispatch_campaign(
        db=db_session,
        msghub_client=_TimeoutRcsClient(),
        created_by=sample_user.sub,
        caller_number=sample_caller.number,
        content="예약 안내",
        recipients=recipients,
        message_type="SMS",
        reserve_time_local=reserve_at,
    )
    assert (campaign.state, campaign.fail_count) == ("RESERVE_FAILED", 2)

    process_report(db_session, [
        _done_report(f"c{campaign.id}-0-0", recipients[0]),
        _done_report(f"c{campaign.id}-0-1", recipients[1]),
    ])

    assert (campaign.state, campaign.ok_count, campaign.fail_count) == ("COMPLETED", 2, 0)
    assert campaign.completed_at is not None


def test_reserve_canceled_is_not_changed_by_reports(db_session, sample_user):
    """취소한 예약은 메시지 결과가 실패로 확정돼도 RESERVE_CANCELED 로 남는다 ("발송 실패" 오표기 방지)."""
    campaign, keys = _make_reserved(
        db_session, sample_user.sub,
        sent_at="2026-06-01T03:00:00+00:00", statuses=["PENDING", "PENDING"],
    )
    campaign.state = "RESERVE_CANCELED"
    db_session.commit()

    process_report(db_session, [
        _done_report(keys[0], "01000000000", result_code="29002"),
        _done_report(keys[1], "01000000001", result_code="29002"),
    ])

    assert (campaign.state, campaign.pending_count, campaign.completed_at) == ("RESERVE_CANCELED", 0, None)


def test_reserved_completes_via_reconcile(db_session, sample_user):
    """예약 시각이 지난 RESERVED 캠페인의 PENDING 을 reconcile 가 DONE 보정 → COMPLETED.

    reconcile 는 MsghubRequest.sent_at < (now-10min) 인 미완료만 조회한다. 예약
    메시지의 sent_at 은 예약 시각이므로, 예약 시각+cutoff 가 지난 시점이라야 대상이
    된다. 여기서는 과거 예약 시각(sent_at=과거)으로 그 시점을 재현하고, reconcile 가
    RESERVED 캠페인을 제외하지 않음을 함께 확인한다.
    """
    campaign, keys = _make_reserved(
        db_session, sample_user.sub,
        sent_at="2026-01-01T00:00:00+00:00",  # 이미 지난 예약 시각
        statuses=["PENDING", "PENDING"],
    )
    client = _FakeClient([
        {"cliKey": keys[0], "status": "DONE", "resultCode": SUCCESS_CODE, "ch": "RCS", "productCode": "SMS"},
        {"cliKey": keys[1], "status": "DONE", "resultCode": SUCCESS_CODE, "ch": "RCS", "productCode": "SMS"},
    ])

    n = asyncio.run(reconcile_pending_messages(db_session, client, older_than_minutes=10))

    assert n == 2
    assert client.calls  # query_sent 호출됨 — RESERVED 캠페인이 제외되지 않음
    assert campaign.state == "COMPLETED"
    assert campaign.pending_count == 0
    assert campaign.ok_count == 2
