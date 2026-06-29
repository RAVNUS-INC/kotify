"""아웃바운드 n8n 알림 테스트.

- MO 수신 시 notify.n8n_enabled=true 면 n8n URL 로 POST 한다.
- 비활성/URL 미설정이면 전송하지 않는다.
- n8n 전송이 실패해도 msghub 응답(success)은 막지 않는다(격리).
- 페이로드에 회신 번호/본문/표시형 번호가 들어간다.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.routes.webhook import receive_mo
from app.security.settings_store import SettingsStore
from app.services import notify


def _setup_token(db):
    SettingsStore(db).set(
        "msghub.webhook_token", "wtok", is_secret=True, updated_by="test"
    )
    db.commit()


def _enable_n8n(db, url="https://n8n.example.com/webhook/abc"):
    store = SettingsStore(db)
    store.set("notify.n8n_enabled", "true", is_secret=False, updated_by="test")
    store.set("notify.n8n_url", url, is_secret=False, updated_by="test")
    db.commit()


def _mo_request(body: dict):
    request = MagicMock()
    request.json = AsyncMock(return_value=body)
    request.client = MagicMock()
    request.client.host = "10.0.0.1"
    return request


def _mo_body(msg="안녕하세요 회신입니다"):
    return {"moCnt": 1, "moLst": [{
        "moKey": "k1", "moNumber": "010-1234-5678", "moMsg": msg,
        "moRecvDt": "2026-01-01 10:00:00",
    }]}


# ── notify_n8n_mo (서비스 단위) ───────────────────────────────────────────────


def test_notify_disabled_does_not_send(db_session):
    """enabled=false(기본) 면 전송하지 않는다."""
    mo = MagicMock(mo_number="01012345678", mo_msg="hi", mo_callback="025771000",
                   mo_title=None, mo_type="SMS", telco=None, mo_recv_dt="",
                   received_at="2026-01-01T00:00:00+00:00", mo_key="k1")
    with patch("httpx.AsyncClient.post", new=AsyncMock()) as m:
        sent = asyncio.run(notify.notify_n8n_mo(db_session, [mo]))
    assert sent == 0
    m.assert_not_called()


def test_notify_enabled_posts_payload(db_session):
    """enabled=true + URL 설정이면 각 MO 를 POST 한다."""
    _enable_n8n(db_session)
    mo = MagicMock(mo_number="01012345678", mo_msg="회신내용", mo_callback="025771000",
                   mo_title=None, mo_type="SMS", telco="LGU", mo_recv_dt="20260101100000",
                   received_at="2026-01-01T00:00:00+00:00", mo_key="k1")

    resp = MagicMock(status_code=200)
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)) as m:
        sent = asyncio.run(notify.notify_n8n_mo(db_session, [mo]))

    assert sent == 1
    m.assert_called_once()
    # 페이로드 검증
    _, kwargs = m.call_args
    payload = kwargs["json"]
    assert payload["from"] == "01012345678"
    assert payload["fromDisplay"] == "010-1234-5678"
    assert payload["text"] == "회신내용"
    assert payload["event"] == "message.received"


def test_notify_failure_is_swallowed(db_session):
    """n8n 이 예외/4xx 여도 notify 는 예외를 던지지 않는다(격리)."""
    _enable_n8n(db_session)
    mo = MagicMock(mo_number="01012345678", mo_msg="x", mo_callback="025771000",
                   mo_title=None, mo_type="SMS", telco=None, mo_recv_dt="",
                   received_at="2026-01-01T00:00:00+00:00", mo_key="k1")
    import httpx

    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=httpx.ConnectError("down"))):
        sent = asyncio.run(notify.notify_n8n_mo(db_session, [mo]))
    assert sent == 0  # 실패해도 예외 없이 0 반환


# ── receive_mo 통합 (수신 → 알림) ─────────────────────────────────────────────


def test_receive_mo_triggers_n8n_when_enabled(db_session):
    """MO 수신 저장 후 enabled 면 n8n 으로 전송된다.

    전송은 응답의 BackgroundTask 로 미뤄지므로, 응답을 받은 뒤 background 를
    명시적으로 실행해 전송이 일어나는지 확인한다(ASGI 스택이 하는 일을 모사).
    """
    _setup_token(db_session)
    _enable_n8n(db_session)

    resp_obj = MagicMock(status_code=200)
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp_obj)) as m:
        resp = asyncio.run(receive_mo("wtok", _mo_request(_mo_body()), db_session))
        assert resp.status_code == 200
        assert resp.background is not None  # 알림 작업이 예약됨
        m.assert_not_called()  # 아직 응답 전 — 전송은 미발생
        # 응답 후 백그라운드 실행 (Starlette 가 응답 직후 호출하는 것과 동일)
        asyncio.run(resp.background())

    m.assert_called_once()
    _, kwargs = m.call_args
    assert kwargs["json"]["fromDisplay"] == "010-1234-5678"


def test_receive_mo_success_even_if_n8n_down(db_session):
    """n8n 이 죽어도 msghub 응답은 success(200) 여야 한다."""
    _setup_token(db_session)
    _enable_n8n(db_session)
    import httpx

    with patch(
        "httpx.AsyncClient.post",
        new=AsyncMock(side_effect=httpx.ConnectError("down")),
    ):
        resp = asyncio.run(receive_mo("wtok", _mo_request(_mo_body()), db_session))
        assert resp.status_code == 200  # 알림 실패가 수신 처리를 막지 않음
        # 백그라운드 실행 시 예외가 새어 나오지 않아야 한다(deliver_n8n 이 격리).
        assert resp.background is not None
        asyncio.run(resp.background())  # 예외 없이 완료되어야 함


def test_receive_mo_no_n8n_when_disabled(db_session):
    """알림 비활성 시 background 작업 자체가 예약되지 않는다."""
    _setup_token(db_session)  # n8n 설정 안 함

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as m:
        resp = asyncio.run(receive_mo("wtok", _mo_request(_mo_body()), db_session))

    assert resp.status_code == 200
    assert resp.background is None  # 예약 안 됨
    m.assert_not_called()
