"""웹훅 진단(GET /webhooks) msghub 리포트 수신 — 포맷이 섞인 report_dt 를 실제 시각으로 비교한다.

report_dt 는 msghub rptDt 원본(오프셋 없는 KST 'yyyy-MM-ddTHH:mm:ss')이고, rptDt 가 빈 리포트와
대체 SMS 요청은 UTC ISO(report._now_iso())를 기록한다. 문자열 max 로는 같은 순간의 KST 벽시계가
UTC 보다 9시간 늦어 보이고, 오프셋 없는 값을 UTC 로 읽으면 실제보다 9시간 늦은 시각이 된다.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.models import Campaign, Message, MsghubRequest
from app.routes.settings import list_webhooks
from app.security.settings_store import SettingsStore
from app.util.time import KST


def _add_report(db, *, report_dt: str) -> None:
    """리포트가 반영된 발송 1건."""
    c = Campaign(
        created_by="test-sub-001", caller_number="0212345678", message_type="short",
        content="공지", total_count=1, state="DONE", created_at="2026-06-01T00:00:00+00:00",
    )
    db.add(c)
    db.flush()
    req = MsghubRequest(campaign_id=c.id, chunk_index=0, sent_at="2026-06-01T00:00:00+00:00")
    db.add(req)
    db.flush()
    db.add(Message(
        campaign_id=c.id, msghub_request_id=req.id, to_number="01012345678",
        to_number_raw="01012345678", status="DONE", report_dt=report_dt, complete_time=report_dt,
    ))
    db.flush()


def _report_webhook(db) -> dict:
    return next(w for w in list_webhooks(db=db)["data"] if w["id"] == "msghub-report")


@pytest.mark.parametrize(
    ("stamps", "expected"),
    [
        pytest.param(("2026-06-01T12:00:00", "2026-06-01T03:30:00.250000+00:00"), "2026-06-01 12:30",
                     id="utc-fallback-after-kst"),
        pytest.param(("2026-06-01T12:40:00", "2026-06-01T03:30:00.250000+00:00"), "2026-06-01 12:40",
                     id="kst-after-utc-fallback"),
    ],
)
def test_last_received_at_is_latest_report_in_kst(db_session, sample_user, stamps, expected):
    """마지막 수신 시각은 실제로 가장 늦은 report_dt 다.

    예전엔 문자열 max 로 골라 rptDt 가 비어 UTC 로 기록된 더 늦은 리포트를 놓쳤고, 고른 msghub 값도
    UTC 로 읽어 9시간 늦게 보였다.
    """
    for stamp in stamps:
        _add_report(db_session, report_dt=stamp)
    db_session.commit()

    assert _report_webhook(db_session)["lastReceivedAt"] == expected


@pytest.mark.parametrize(
    ("hours_ago", "msghub_format", "expected"),
    [
        pytest.param(30, True, "stale", id="msghub-kst-30h"),
        pytest.param(20, True, "ok", id="msghub-kst-20h"),
        pytest.param(30, False, "stale", id="utc-fallback-30h"),
    ],
)
def test_status_follows_real_age_of_last_report(
    db_session, sample_user, hours_ago, msghub_format, expected
):
    """24시간 기준 ok/stale 은 실제 경과 시간이다.

    예전엔 오프셋 없는 msghub 값을 UTC 로 읽어 9시간 덜 지난 것으로 보여, 30시간 전 수신도 ok 였다.
    """
    store = SettingsStore(db_session)
    store.set("msghub.webhook_token", "hook-token", is_secret=True, updated_by=None)
    store.set("app.public_url", "https://sms.example.com", is_secret=False, updated_by=None)
    received = datetime.now(UTC) - timedelta(hours=hours_ago)
    stamp = (
        received.astimezone(KST).strftime("%Y-%m-%dT%H:%M:%S") if msghub_format
        else received.isoformat()
    )
    _add_report(db_session, report_dt=stamp)
    db_session.commit()

    assert _report_webhook(db_session)["status"] == expected
