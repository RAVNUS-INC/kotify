"""아웃바운드 n8n 알림 테스트.

- MO 수신 시 notify.n8n_enabled=true 면 n8n URL 로 POST 한다.
- 비활성/URL 미설정이면 전송하지 않는다.
- n8n 전송이 실패해도 msghub 응답(success)은 막지 않는다(격리).
- 페이로드에 회신 번호/본문/표시형 번호가 들어간다.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from sqlalchemy import select

from app.models import (
    Campaign,
    Message,
    MsghubRequest,
    NotificationDelivery,
    User,
)
from app.routes.settings import N8nTestBody
from app.routes.settings import test_n8n_notify as _test_n8n_notify_route
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
    # 발송 이력 없음 → lastSender 키는 존재하되 null
    assert payload["lastSender"] is None


def test_notify_failure_is_swallowed(db_session):
    """n8n 이 예외/4xx 여도 notify 는 예외를 던지지 않는다(격리)."""
    _enable_n8n(db_session)
    mo = MagicMock(mo_number="01012345678", mo_msg="x", mo_callback="025771000",
                   mo_title=None, mo_type="SMS", telco=None, mo_recv_dt="",
                   received_at="2026-01-01T00:00:00+00:00", mo_key="k1")
    with patch("httpx.AsyncClient.post", new=AsyncMock(side_effect=httpx.ConnectError("down"))):
        sent = asyncio.run(notify.notify_n8n_mo(db_session, [mo]))
    assert sent == 0  # 실패해도 예외 없이 0 반환


def test_notify_redirect_is_failure(db_session):
    """3xx는 n8n 실행 성공이 아니므로 성공 건수에 포함하지 않는다."""
    resp = MagicMock(status_code=302)
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)) as post:
        sent = asyncio.run(notify.deliver_n8n("https://n8n.example/hook", [{"a": 1}]))
    assert sent == 0
    post.assert_awaited_once()


def test_n8n_test_routes_to_current_user():
    """설정 테스트도 실제 워크플로가 요구하는 lastSender를 포함한다."""
    recipient = {
        "id": "tester@example.com",
        "email": "tester@example.com",
        "name": "테스터",
        "sentAt": "2026-09-18T00:00:00+00:00",
        "messageId": "TEST",
    }
    resp = MagicMock(status_code=200)
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp)) as post:
        ok, _ = asyncio.run(
            notify.send_n8n_test("https://n8n.example/hook", recipient)
        )
    assert ok is True
    payload = post.await_args.kwargs["json"]
    assert payload["lastSender"] == recipient
    assert "test" not in payload


def test_settings_test_n8n_uses_logged_in_user(db_session, sample_user):
    """설정 API가 버튼을 누른 로그인 사용자를 Telegram 수신자로 넘긴다."""
    with patch(
        "app.services.notify.send_n8n_test",
        new=AsyncMock(return_value=(True, "ok")),
    ) as send:
        result = asyncio.run(
            _test_n8n_notify_route(
                N8nTestBody(url="https://n8n.example/hook"),
                user=sample_user,
                db=db_session,
            )
        )

    recipient = send.await_args.args[1]
    assert result == {"data": {"ok": True, "message": "ok"}}
    assert recipient["id"] == sample_user.email
    assert recipient["messageId"] == "TEST"


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
    with patch(
        "httpx.AsyncClient.post",
        new=AsyncMock(side_effect=httpx.ConnectError("down")),
    ):
        resp = asyncio.run(receive_mo("wtok", _mo_request(_mo_body()), db_session))
        assert resp.status_code == 200  # 알림 실패가 수신 처리를 막지 않음
        # 백그라운드 실행 시 예외가 새어 나오지 않아야 한다(deliver_n8n 이 격리).
        assert resp.background is not None
        asyncio.run(resp.background())  # 예외 없이 완료되어야 함

    delivery = db_session.execute(select(NotificationDelivery)).scalar_one()
    assert delivery.status == "FAILED"
    assert delivery.attempts == 1
    assert "down" in (delivery.last_error or "")


def test_failed_outbox_is_retried_and_delivered(db_session):
    """실패 행은 DB에 남고 다음 처리 주기에서 다시 전송된다."""
    _setup_token(db_session)
    _enable_n8n(db_session)
    with patch(
        "httpx.AsyncClient.post",
        new=AsyncMock(side_effect=httpx.ConnectError("temporary")),
    ):
        resp = asyncio.run(receive_mo("wtok", _mo_request(_mo_body()), db_session))
        asyncio.run(resp.background())

    delivery = db_session.execute(select(NotificationDelivery)).scalar_one()
    delivery.next_attempt_at = "2000-01-01T00:00:00+00:00"
    db_session.commit()

    with patch(
        "httpx.AsyncClient.post",
        new=AsyncMock(return_value=MagicMock(status_code=204)),
    ) as post:
        delivered = asyncio.run(notify.process_n8n_outbox(db_session))

    db_session.refresh(delivery)
    assert delivered == 1
    assert delivery.status == "DELIVERED"
    assert delivery.attempts == 2
    post.assert_awaited_once()


def test_duplicate_mo_does_not_duplicate_outbox(db_session):
    """msghub 재전송은 같은 MO와 알림 행을 추가하지 않는다."""
    _setup_token(db_session)
    _enable_n8n(db_session)
    first = asyncio.run(receive_mo("wtok", _mo_request(_mo_body()), db_session))
    second = asyncio.run(receive_mo("wtok", _mo_request(_mo_body()), db_session))
    assert first.background is not None
    assert second.background is None
    assert len(db_session.execute(select(NotificationDelivery)).scalars().all()) == 1


def test_receive_mo_no_n8n_when_disabled(db_session):
    """알림 비활성 시 background 작업 자체가 예약되지 않는다."""
    _setup_token(db_session)  # n8n 설정 안 함

    with patch("httpx.AsyncClient.post", new=AsyncMock()) as m:
        resp = asyncio.run(receive_mo("wtok", _mo_request(_mo_body()), db_session))

    assert resp.status_code == 200
    assert resp.background is None  # 예약 안 됨
    m.assert_not_called()


# ── lookup_last_sender (회신 담당자 매칭) ─────────────────────────────────────


def _make_user(db, sub, email, display_name):
    db.add(User(
        sub=sub, email=email, name=email.split("@")[0], display_name=display_name,
        roles='["sender"]', created_at="2026-01-01T00:00:00+00:00",
        last_login_at="2026-01-01T00:00:00+00:00",
    ))
    db.commit()


def _make_outbound(
    db,
    *,
    sub,
    phone,
    created_at,
    sent_at=None,
    complete_time=None,
    status="DONE",
    result_code="10000",
    state="COMPLETED",
    reserve_time=None,
):
    """sub 직원이 phone 으로 보낸 발송(MT) 1건."""
    c = Campaign(
        created_by=sub, caller_number="0212345678", message_type="short",
        content="공지", total_count=1, pending_count=0, state=state,
        created_at=created_at, reserve_time=reserve_time,
    )
    db.add(c)
    db.flush()
    req = MsghubRequest(
        campaign_id=c.id, chunk_index=0, sent_at=sent_at or created_at
    )
    db.add(req)
    db.flush()
    db.add(Message(
        campaign_id=c.id, msghub_request_id=req.id,
        to_number=phone,
        to_number_raw=phone,
        status=status,
        result_code=result_code,
        complete_time=(complete_time or sent_at or created_at) if status == "DONE" else complete_time,
    ))
    db.commit()


def test_lookup_last_sender_found(db_session):
    """발송 이력 있으면 담당자 id=email, name=display_name 반환."""
    _make_user(db_session, "u1", "stopdragon@ravnus.com", "정지용")
    _make_outbound(db_session, sub="u1", phone="01012345678",
                   created_at="2026-06-01T00:00:00+00:00")

    got = notify.lookup_last_sender(db_session, "01012345678")
    assert got is not None
    assert got["id"] == "stopdragon@ravnus.com"
    assert got["email"] == "stopdragon@ravnus.com"
    assert got["name"] == "정지용"
    assert got["messageId"].startswith("MT-")
    assert got["sentAt"].endswith("+09:00")  # KST 변환


def test_lookup_last_sender_none_when_no_history(db_session):
    """그 번호로 보낸 적 없으면 None."""
    _make_user(db_session, "u1", "a@ravnus.com", "에이")
    _make_outbound(db_session, sub="u1", phone="01099998888",
                   created_at="2026-06-01T00:00:00+00:00")
    # 다른 번호 회신
    assert notify.lookup_last_sender(db_session, "01012345678") is None


def test_lookup_last_sender_most_recent_wins(db_session):
    """같은 번호에 여러 담당자 → 가장 최근 발송 담당자."""
    _make_user(db_session, "u1", "old@ravnus.com", "옛담당")
    _make_user(db_session, "u2", "new@ravnus.com", "새담당")
    _make_outbound(db_session, sub="u1", phone="01012345678",
                   created_at="2026-05-01T00:00:00+00:00")
    _make_outbound(db_session, sub="u2", phone="01012345678",
                   created_at="2026-06-20T00:00:00+00:00")

    got = notify.lookup_last_sender(db_session, "01012345678")
    assert got["id"] == "new@ravnus.com"


def test_lookup_last_sender_uses_delivery_time_not_campaign_creation(db_session):
    """늦게 만든 캠페인보다 실제 전달 시각이 늦은 발송 담당자가 선택된다."""
    _make_user(db_session, "u1", "late-delivery@ravnus.com", "늦은전달")
    _make_user(db_session, "u2", "late-created@ravnus.com", "늦은생성")
    _make_outbound(
        db_session,
        sub="u1",
        phone="01012345678",
        created_at="2026-06-01T00:00:00+00:00",
        complete_time="2026-06-03T00:00:00+00:00",
    )
    _make_outbound(
        db_session,
        sub="u2",
        phone="01012345678",
        created_at="2026-06-02T00:00:00+00:00",
        complete_time="2026-06-02T01:00:00+00:00",
    )
    assert notify.lookup_last_sender(db_session, "01012345678")["id"] == (
        "late-delivery@ravnus.com"
    )


def test_lookup_last_sender_ignores_failed_latest_message(db_session):
    """최근 캠페인의 실패 메시지가 이전 정상 담당자를 가로채지 않는다."""
    _make_user(db_session, "u1", "ok@ravnus.com", "정상담당")
    _make_user(db_session, "u2", "failed@ravnus.com", "실패담당")
    _make_outbound(
        db_session,
        sub="u1",
        phone="01012345678",
        created_at="2026-06-01T00:00:00+00:00",
    )
    _make_outbound(
        db_session,
        sub="u2",
        phone="01012345678",
        created_at="2026-06-02T00:00:00+00:00",
        status="FAILED",
        result_code="50000",
        state="FAILED",
    )
    assert notify.lookup_last_sender(db_session, "01012345678")["id"] == (
        "ok@ravnus.com"
    )


def test_lookup_last_sender_ignores_future_reservation(db_session):
    """아직 발송 시각이 오지 않은 예약 건은 마지막 담당자가 아니다."""
    _make_user(db_session, "u1", "sent@ravnus.com", "발송담당")
    _make_user(db_session, "u2", "reserved@ravnus.com", "예약담당")
    _make_outbound(
        db_session,
        sub="u1",
        phone="01012345678",
        created_at="2026-06-01T00:00:00+00:00",
    )
    _make_outbound(
        db_session,
        sub="u2",
        phone="01012345678",
        created_at=datetime.now(UTC).isoformat(),
        sent_at=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
        status="REG",
        result_code=None,
        state="RESERVED",
        reserve_time=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
    )
    assert notify.lookup_last_sender(db_session, "01012345678")["id"] == (
        "sent@ravnus.com"
    )


def test_lookup_last_sender_uses_elapsed_reservation_time(db_session):
    """지난 예약은 등록 시각이 아니라 실제 예약 시각으로 최근 발송을 정한다."""
    _make_user(db_session, "u1", "immediate@ravnus.com", "즉시담당")
    _make_user(db_session, "u2", "reserved@ravnus.com", "예약담당")
    _make_outbound(
        db_session,
        sub="u1",
        phone="01012345678",
        created_at="2026-06-02T00:00:00+00:00",
        complete_time="2026-06-02T01:00:00+00:00",
    )
    _make_outbound(
        db_session,
        sub="u2",
        phone="01012345678",
        created_at="2026-06-01T00:00:00+00:00",
        sent_at="2026-06-01T00:00:00+00:00",
        status="REG",
        result_code=None,
        state="RESERVED",
        reserve_time="2026-06-03T09:00:00+09:00",
    )
    got = notify.lookup_last_sender(db_session, "01012345678")
    assert got["id"] == "reserved@ravnus.com"
    assert got["sentAt"] == "2026-06-03T09:00:00+09:00"


def test_lookup_last_sender_matches_old_history(db_session):
    """오래된 발송이라도 마지막 담당자면 매칭된다 (기간 제한 없음)."""
    _make_user(db_session, "u1", "old@ravnus.com", "옛담당")
    stale = (datetime.now(UTC) - timedelta(days=400)).isoformat()
    _make_outbound(db_session, sub="u1", phone="01012345678", created_at=stale)

    got = notify.lookup_last_sender(db_session, "01012345678")
    assert got is not None
    assert got["id"] == "old@ravnus.com"


def test_receive_mo_payload_includes_last_sender(db_session):
    """통합: 회신 수신 시 payload.lastSender 가 담당자로 채워진다."""
    _setup_token(db_session)
    _enable_n8n(db_session)
    _make_user(db_session, "u1", "stopdragon@ravnus.com", "정지용")
    _make_outbound(db_session, sub="u1", phone="01012345678",
                   created_at="2026-06-01T00:00:00+00:00")

    resp_obj = MagicMock(status_code=200)
    with patch("httpx.AsyncClient.post", new=AsyncMock(return_value=resp_obj)) as m:
        resp = asyncio.run(receive_mo("wtok", _mo_request(_mo_body()), db_session))
        assert resp.background is not None
        asyncio.run(resp.background())

    _, kwargs = m.call_args
    ls = kwargs["json"]["lastSender"]
    assert ls is not None
    assert ls["id"] == "stopdragon@ravnus.com"
    assert ls["name"] == "정지용"
