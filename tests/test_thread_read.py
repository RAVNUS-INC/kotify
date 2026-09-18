"""팀 공유 읽음은 화면에서 관측한 MO ID 경계이며 수신 시각/요청 완료 순서에 의존하지 않는다."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_complete, require_user
from app.db import Base, get_db
from app.models import Campaign, Message, MoMessage, MsghubRequest, ThreadRead
from app.routes.threads import ThreadReadBody, api_get_thread, api_mark_read, router
from app.services.chat import list_threads, thread_unread

_CALLER = "0212345678"
_PHONE = "01099998888"
_TID = f"{_CALLER}:{_PHONE}"


def _make_mo(db, *, recv_dt="2026-05-30T12:00:00+00:00", mo_key, caller=_CALLER,
             phone=_PHONE, msg="안녕하세요", received_at=None):
    mo = MoMessage(
        mo_key=mo_key, mo_number=phone, mo_callback=caller, mo_type="message", mo_msg=msg,
        mo_recv_dt=recv_dt, raw_payload="{}", received_at=received_at or recv_dt,
    )
    db.add(mo)
    db.commit()
    return mo.id


def _thread(db, phone=_PHONE):
    return next(t for t in list_threads(db)[0] if t.phone == phone)


def _read(db, mo_id, caller=_CALLER):
    return api_mark_read(f"{caller}:{_PHONE}", ThreadReadBody(lastReadMessageId=mo_id), db=db)


@pytest.mark.parametrize(("mo", "read", "expected"), [
    (10, 9, True), (10, 10, False), (9, 10, False), (10, None, True),
    (10, 0, True), (None, 10, False), (None, None, False),
])
def test_thread_unread_helper(mo, read, expected):
    assert thread_unread(mo, read) is expected


def test_mark_read_clears_unread_and_upserts(db_session):
    mo_id = _make_mo(db_session, mo_key="a")
    assert _thread(db_session).unread is True
    assert _read(db_session, mo_id)["data"] == {
        "id": _TID, "unread": False, "lastReadMessageId": mo_id,
    }
    _read(db_session, mo_id)
    assert _thread(db_session).unread is False
    assert db_session.scalar(select(func.count()).select_from(ThreadRead)) == 1


def test_read_snapshot_does_not_swallow_message_arriving_after_get(db_session):
    first = _make_mo(db_session, mo_key="first")
    snapshot = api_get_thread(_TID, db_session)["data"]
    assert snapshot["lastInboundMessageId"] == first
    later = _make_mo(db_session, mo_key="later", recv_dt="2026-05-30T14:00:00+00:00")

    result = _read(db_session, snapshot["lastInboundMessageId"])

    assert result["data"]["unread"] is True
    assert _thread(db_session).unread is True
    detail = api_get_thread(_TID, db_session)["data"]
    assert detail["unread"] is True
    assert detail["lastInboundMessageId"] == later
    _read(db_session, later)
    assert _thread(db_session).unread is False


def test_delayed_old_source_timestamp_stays_unread_and_snapshot_uses_max_id(db_session):
    first = _make_mo(db_session, mo_key="first", recv_dt="2026-05-30T12:00:00")
    _read(db_session, first)
    assert _thread(db_session).unread is False
    later = _make_mo(db_session, mo_key="delayed", recv_dt="20260529090000",
                     received_at="2026-05-30T04:00:00+00:00")
    detail = api_get_thread(_TID, db_session)["data"]
    assert detail["messages"][-1]["id"] == f"m-in-{first}"  # 시각으로는 이전 행이 마지막이다.
    assert detail["lastInboundMessageId"] == later
    assert detail["unread"] is True
    assert _thread(db_session).unread is True
    _read(db_session, later)
    assert _thread(db_session).unread is False


def test_phone_read_is_shared_across_callers_and_reverse_requests_do_not_regress(db_session):
    first = _make_mo(db_session, mo_key="first")
    second = _make_mo(db_session, mo_key="second", caller="CHATBOT_OTHER")
    _read(db_session, second)
    _read(db_session, first)  # 같은 caller의 늦게 끝난 이전 요청.
    _read(db_session, first, caller="CHATBOT_OTHER")  # 다른 caller의 이전 요청.
    assert _thread(db_session).unread is False
    for caller in (_CALLER, "CHATBOT_OTHER"):
        assert "unread" not in api_get_thread(f"{caller}:{_PHONE}", db_session)["data"]
    assert db_session.scalar(select(ThreadRead.last_read_mo_id).where(ThreadRead.caller == _CALLER)) == second


def test_parallel_read_upserts_do_not_regress(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'read-race.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        first = _make_mo(db, mo_key="first")
        second = _make_mo(db, mo_key="second")
    barrier = Barrier(2)

    def mark(mo_id):
        with Session(engine) as db:
            barrier.wait(timeout=5)
            return _read(db, mo_id)["data"]["lastReadMessageId"]

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(mark, [second, first]))
        with Session(engine) as db:
            assert db.scalar(select(ThreadRead.last_read_mo_id)) == second
            assert _thread(db).unread is False
        assert all(value >= first for value in results)
    finally:
        engine.dispose()


def test_invalid_or_other_phone_marker_does_not_write(db_session):
    other = _make_mo(db_session, mo_key="other", phone="01000000001")
    for marker in (other, other + 100):
        result = _read(db_session, marker)
        assert result.status_code == 422
    assert db_session.scalar(select(func.count()).select_from(ThreadRead)) == 0


@pytest.fixture
def thread_app(db_session, sample_user):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_user] = lambda: sample_user
    app.dependency_overrides[require_setup_complete] = lambda: None
    app.dependency_overrides[get_db] = lambda: db_session
    db_session.connection()  # 인메모리 DB 연결을 요청 worker와 공유한다.
    return app


@pytest.mark.parametrize("payload", [None, {}, {"lastReadMessageId": 0}, {"lastReadMessageId": -1},
                                      {"lastReadMessageId": True}, {"lastReadMessageId": "1"}])
async def test_old_or_invalid_read_body_fails_closed(thread_app, db_session, payload):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=thread_app), base_url="http://test") as client:
        result = await client.post(f"/threads/{_TID}/read", json=payload)
    assert result.status_code == 422
    assert db_session.scalar(select(func.count()).select_from(ThreadRead)) == 0


def test_detail_unread_with_trailing_outbound(db_session, sample_user):
    mo_id = _make_mo(db_session, recv_dt="2026-05-30T01:00:00+00:00", mo_key="mo-trail")
    campaign = Campaign(
        created_by=sample_user.sub, caller_number=_CALLER, message_type="short", content="답장드립니다",
        total_count=1, pending_count=0, state="DISPATCHED", created_at="2026-05-30T02:00:00+00:00",
    )
    db_session.add(campaign)
    db_session.flush()
    request = MsghubRequest(campaign_id=campaign.id, chunk_index=0, sent_at=campaign.created_at)
    db_session.add(request)
    db_session.flush()
    db_session.add(Message(campaign_id=campaign.id, msghub_request_id=request.id,
                           to_number=_PHONE, to_number_raw=_PHONE, status="REG"))
    db_session.commit()
    detail = api_get_thread(_TID, db_session)["data"]
    assert detail["messages"][-1]["side"] == "us"
    assert detail["lastInboundMessageId"] == mo_id
    assert detail["unread"] is True
    _read(db_session, mo_id)
    assert _thread(db_session).unread is False
    assert "unread" not in api_get_thread(_TID, db_session)["data"]


@pytest.mark.parametrize("query", ["limit=0", "limit=201", "offset=-1", "limit=nope"])
async def test_invalid_page_bounds_rejected(thread_app, query):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=thread_app), base_url="http://test") as client:
        result = await client.get(f"/threads?{query}")
    assert result.status_code == 422
