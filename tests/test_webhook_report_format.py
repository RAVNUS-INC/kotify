"""리포트 웹훅 형식 오류 항목은 건너뛰고 나머지를 반영해 200 — 재전송 72시간 방지. health check 주기."""
from __future__ import annotations

import asyncio

import pytest

from app.models import Campaign
from tests.test_sms_fallback import (
    _make_chat_reply,
    _message,
    _post_report,
    _setup_token,
    _SmsClient,
)


def test_bad_item_is_skipped_and_good_item_applied(db_session, sample_user, monkeypatch):
    _setup_token(db_session)
    monkeypatch.setattr("app.main.get_msghub_client", lambda: _SmsClient())
    campaign, cli_key = _make_chat_reply(db_session)
    good = {
        "msgKey": "mk-chat", "cliKey": cli_key, "ch": "RCS", "resultCode": "10000",
        "resultCodeDesc": "성공", "productCode": "CHAT", "phone": "01099998888",
    }

    resp = _post_report(db_session, "형식이 틀린 항목", good)

    assert resp.status_code == 200
    assert _message(db_session, campaign.id).status == "DONE"
    assert db_session.get(Campaign, campaign.id).state == "COMPLETED"


@pytest.mark.asyncio
async def test_health_check_runs_on_its_own_under_a_minute(monkeypatch):
    """재조정과 분리돼 요청 시간을 빼고 50초 간격으로 돈다 — 예전엔 60초 + 재조정 시간이었다."""
    import app.main as main

    calls = 0
    sleeps: list[float] = []

    class _Client:
        async def health_check(self):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("일시 장애")  # 실패해도 다음 주기를 막지 않는다
            return True

    async def _client():
        return _Client()

    async def _sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(main, "aget_msghub_client", _client)
    monkeypatch.setattr(main.asyncio, "sleep", _sleep)
    with pytest.raises(asyncio.CancelledError):
        await main._health_check_loop()

    assert calls == 2
    assert all(45 < s <= main._HEALTH_CHECK_INTERVAL_SECONDS < 60 for s in sleeps)
