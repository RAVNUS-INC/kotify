"""대화방 실시간 갱신(SSE) 이벤트 테스트.

- publish → 구독자 큐 전달, 구독 해제 후엔 미전달.
- 구독자 없어도/큐 가득 차도 publish 는 예외 없이 동작(webhook 보호).
- MO 수신 시 "message.new" 이벤트가 실제로 발행된다(새로고침 없이 갱신되는 근거).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from app.routes.webhook import receive_mo
from app.security.settings_store import SettingsStore
from app.services import events


def _setup_token(db):
    SettingsStore(db).set(
        "msghub.webhook_token", "wtok", is_secret=True, updated_by="test"
    )
    db.commit()


def _mo_request(body: dict):
    request = MagicMock()
    request.json = AsyncMock(return_value=body)
    request.client = MagicMock()
    request.client.host = "10.0.0.1"
    return request


def _mo_body(key="e1"):
    return {"moCnt": 1, "moLst": [{
        "moKey": key, "moNumber": "01012345678", "moMsg": "회신",
        "moRecvDt": "2026-01-01 10:00:00",
    }]}


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


# ── MO 수신 → 이벤트 발행 (통합) ─────────────────────────────────────────────


def test_receive_mo_publishes_event(db_session):
    """고객 회신 저장 시 message.new 발행 → 브라우저가 즉시 갱신."""
    _setup_token(db_session)

    async def run():
        q = events.subscribe()
        try:
            resp = await receive_mo("wtok", _mo_request(_mo_body()), db_session)
            assert resp.status_code == 200
            assert q.get_nowait() == "message.new"
        finally:
            events.unsubscribe(q)

    asyncio.run(run())


def test_duplicate_mo_does_not_publish(db_session):
    """중복 MO(재전송)는 저장 안 되므로 이벤트도 발행 안 함(불필요 갱신 방지)."""
    _setup_token(db_session)

    async def run():
        # 1회차 — 저장 + 발행
        await receive_mo("wtok", _mo_request(_mo_body("dup1")), db_session)
        # 2회차 — 같은 moKey → 중복, 구독 후 확인
        q = events.subscribe()
        try:
            await receive_mo("wtok", _mo_request(_mo_body("dup1")), db_session)
            assert q.empty()  # 중복이라 발행 없음
        finally:
            events.unsubscribe(q)

    asyncio.run(run())
