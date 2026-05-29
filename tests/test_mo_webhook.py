"""MO 웹훅 안전성 테스트 (C6).

- _synth_mo_key: moKey 누락 시 대체 멱등키(결정적).
- receive_mo: moKey 누락 MO 도 저장(유실 방지), 미등록 callback 거부(위변조 방지).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import select

from app.models import Caller, MoMessage
from app.routes.webhook import _synth_mo_key, receive_mo
from app.security.settings_store import SettingsStore


def _setup_token(db):
    SettingsStore(db).set("msghub.webhook_token", "wtok", is_secret=True, updated_by="test")
    db.commit()


def _add_caller(db, number: str):
    db.add(Caller(number=number, label="발신", active=1, created_at="2026-01-01T00:00:00+00:00"))
    db.commit()


def _mo_request(body: dict):
    request = MagicMock()
    request.json = AsyncMock(return_value=body)
    request.client = MagicMock()
    request.client.host = "10.0.0.1"
    return request


# ── _synth_mo_key ────────────────────────────────────────────────────────────


def test_synth_mo_key_deterministic_and_distinct():
    k1 = _synth_mo_key("01011112222", "2026-01-01", "hi", "0212345678")
    k2 = _synth_mo_key("01011112222", "2026-01-01", "hi", "0212345678")
    k3 = _synth_mo_key("01011112222", "2026-01-01", "다른내용", "0212345678")
    assert k1 == k2  # 같은 입력 → 같은 키 (재시도 멱등)
    assert k1 != k3  # 다른 입력 → 다른 키
    assert k1.startswith("syn-")


# ── receive_mo ───────────────────────────────────────────────────────────────


def test_receive_mo_synthesizes_key_when_missing(db_session):
    """moKey 누락 MO 도 대체키로 저장된다 (이전엔 skip 후 영구 유실)."""
    _setup_token(db_session)
    body = {"moCnt": 1, "moLst": [{
        "moNumber": "01011112222", "moMsg": "키없음", "moRecvDt": "2026-01-01 10:00:00",
    }]}  # moKey, moCallback 없음

    resp = asyncio.run(receive_mo("wtok", _mo_request(body), db_session))

    assert resp.status_code == 200
    rows = db_session.execute(select(MoMessage)).scalars().all()
    assert len(rows) == 1
    assert rows[0].mo_key.startswith("syn-")


def test_receive_mo_rejects_unregistered_callback(db_session):
    """등록 발신번호가 있을 때 미등록 moCallback MO 는 거부된다 (위변조 방지)."""
    _setup_token(db_session)
    _add_caller(db_session, "0212345678")
    body = {"moCnt": 1, "moLst": [{
        "moKey": "k1", "moNumber": "01011112222", "moCallback": "07099998888",
        "moMsg": "가짜",
    }]}

    resp = asyncio.run(receive_mo("wtok", _mo_request(body), db_session))

    assert resp.status_code == 200  # 가짜 MO 도 msghub 큐에서 빼기 위해 success 응답
    rows = db_session.execute(select(MoMessage)).scalars().all()
    assert len(rows) == 0  # 저장되지 않음


def test_receive_mo_accepts_registered_callback_format_insensitive(db_session):
    """등록된 moCallback 은 하이픈 형식이어도 숫자 비교로 통과·저장된다."""
    _setup_token(db_session)
    _add_caller(db_session, "0212345678")
    body = {"moCnt": 1, "moLst": [{
        "moKey": "k2", "moNumber": "01011112222", "moCallback": "02-1234-5678",
        "moMsg": "정상",
    }]}

    resp = asyncio.run(receive_mo("wtok", _mo_request(body), db_session))

    assert resp.status_code == 200
    rows = db_session.execute(select(MoMessage)).scalars().all()
    assert len(rows) == 1
    assert rows[0].mo_msg == "정상"
