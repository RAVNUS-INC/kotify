"""고객 회신(MO) 첨부 이미지 — 수신 기록, 한 번만 내려받기, 대화방 표시, 소급 마이그레이션."""
from __future__ import annotations

import asyncio
import json
import socket
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select

from app.db import Base
from app.models import MoMedia, MoMessage
from app.routes.threads import api_get_mo_media, api_get_thread
from app.routes.webhook import receive_mo
from app.security.settings_store import SettingsStore
from app.services import mo_media
from app.services.chat import _batch_last_mo_bodies
from tests.test_thread_read_migration import _config

_PHONE = "01011112222"
_URL = "https://image.example-carrier.test/exp/abc/mo/def.jpg"
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
_NOW = "2026-10-16T00:00:00+00:00"


def _info(url: str | None = _URL, mime: str = "image/jpeg", text: str | None = None) -> dict:
    return {
        "textMessage": text,
        "fileMessage": {"fileMIMEType": mime, "fileUrl": url} if url else None,
        "geolocationPushMessage": None,
    }


def _add_mo(db, *, key="k1", info: dict | None = None, text: str | None = None) -> MoMessage:
    mo = MoMessage(
        mo_key=key, mo_number=_PHONE, mo_callback="chatbot", mo_type="message",
        mo_msg=text, content_info_lst=json.dumps(info, ensure_ascii=False) if info else None,
        raw_payload="{}", received_at=_NOW,
    )
    db.add(mo)
    db.flush()
    return mo


def _add_media(db, mo: MoMessage, status: str = "PENDING", **kw) -> MoMedia:
    row = MoMedia(mo_id=mo.id, declared_mime="image/jpeg", fetch_status=status,
                  fetch_attempts=0, created_at=_NOW, **kw)
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def public_host(monkeypatch):
    """테스트 호스트 이름을 실제 DNS 대신 공인 주소로 풀어 준다."""
    async def fake_getaddrinfo(self, host, port, **kw):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", port))]
    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake_getaddrinfo)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _fetch(db, handler) -> int:
    async def run():
        async with _client(handler) as client:
            return await mo_media.fetch_pending(db, client=client)
    return asyncio.run(run())


# ── 웹훅 수신 ────────────────────────────────────────────────────────────────


def _webhook(db, item: dict):
    SettingsStore(db).set("msghub.webhook_token", "wtok", is_secret=True, updated_by="test")
    db.commit()
    request = MagicMock()
    request.json = AsyncMock(return_value={"rcsBiCnt": 1, "rcsBiLst": [item]})
    request.client = MagicMock()
    return asyncio.run(receive_mo("wtok", request, db))


def _rcs_item(key: str, info: dict) -> dict:
    return {"msgKey": key, "phone": _PHONE, "chatbotId": "chatbot", "eventType": "message",
            "replyId": "r1", "contentInfo": info, "moRecvDt": "2026-10-16T09:00:00"}


def test_webhook_records_image_and_schedules_fetch(db_session):
    resp = _webhook(db_session, _rcs_item("img-1", _info()))

    assert resp.status_code == 200
    row = db_session.execute(select(MoMedia)).scalar_one()
    assert (row.fetch_status, row.declared_mime) == ("PENDING", "image/jpeg")
    funcs = [t.func for t in resp.background.tasks]
    assert mo_media.fetch_new in funcs
    assert next(t for t in resp.background.tasks if t.func is mo_media.fetch_new).args == ([row.id],)


def test_webhook_marks_non_image_unsupported_without_fetch(db_session):
    resp = _webhook(db_session, _rcs_item("vid-1", _info(mime="video/mp4")))

    assert db_session.execute(select(MoMedia.fetch_status)).scalar_one() == "UNSUPPORTED"
    assert resp.background is None


def test_webhook_text_only_creates_no_media(db_session):
    _webhook(db_session, _rcs_item("txt-1", _info(url=None, text="안녕하세요")))
    assert db_session.execute(select(MoMedia)).first() is None


# ── 내려받기 ────────────────────────────────────────────────────────────────


def test_fetch_stores_sniffed_image(db_session, public_host):
    row = _add_media(db_session, _add_mo(db_session, info=_info()))
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(200, content=_JPEG, headers={"content-type": "application/octet-stream"})

    assert _fetch(db_session, handler) == 1
    db_session.refresh(row)
    assert seen == [_URL]
    assert (row.fetch_status, row.content_type, row.content_blob) == ("FETCHED", "image/jpeg", _JPEG)
    assert row.file_size_bytes == len(_JPEG) and row.fetch_attempts == 1 and row.locked_at is None


def _due(db, row):
    """재시도 간격(next_fetch_at)이 지난 것으로 만든다."""
    db.refresh(row)
    row.next_fetch_at = None
    db.commit()


@pytest.mark.parametrize("status", [404, 410])
def test_client_error_is_final_and_not_retried(db_session, public_host, status):
    """응답을 받은 4xx 는 만료·소진 — 일회성 주소라 다시 열지 않는다."""
    row = _add_media(db_session, _add_mo(db_session, info=_info()))
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status)

    _fetch(db_session, handler)
    _fetch(db_session, handler)
    db_session.refresh(row)
    assert (row.fetch_status, row.error, len(calls)) == ("FAILED", f"HTTP {status}", 1)


def test_server_error_retries_up_to_limit(db_session, public_host):
    row = _add_media(db_session, _add_mo(db_session, info=_info()))
    handler = lambda request: httpx.Response(503)  # noqa: E731

    for expected in ("PENDING", "PENDING", "FAILED"):
        _fetch(db_session, handler)
        db_session.refresh(row)
        assert row.fetch_status == expected
        _due(db_session, row)
    assert row.fetch_attempts == mo_media.MAX_FETCH_ATTEMPTS["RCS_URL"]


@pytest.mark.parametrize("status", [401, 403])
def test_auth_rejection_is_marked_and_retried(db_session, public_host, status):
    """인증 거부는 바로 닫지 않고 구분 가능한 error 로 다시 시도한다(M7) — 방법을 바꾼 뒤 되살릴 수 있게."""
    row = _add_media(db_session, _add_mo(db_session, info=_info()))
    _fetch(db_session, lambda request: httpx.Response(status))
    db_session.refresh(row)
    assert (row.fetch_status, row.error) == ("PENDING", f"인증 거부 HTTP {status}")
    assert row.next_fetch_at is not None  # 바로 다시 열지 않고 간격을 둔다


def test_retry_waits_for_backoff(db_session, public_host):
    row = _add_media(db_session, _add_mo(db_session, info=_info()))
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(503)

    _fetch(db_session, handler)
    _fetch(db_session, handler)
    assert len(calls) == 1  # 간격(1분) 전에는 다시 열지 않는다
    _due(db_session, row)
    _fetch(db_session, handler)
    assert len(calls) == 2


def test_connection_error_retries(db_session, public_host):
    row = _add_media(db_session, _add_mo(db_session, info=_info()))

    def handler(request):
        raise httpx.ConnectError("down", request=request)

    _fetch(db_session, handler)
    db_session.refresh(row)
    assert (row.fetch_status, row.error) == ("PENDING", "ConnectError")


def test_non_image_body_fails(db_session, public_host):
    row = _add_media(db_session, _add_mo(db_session, info=_info()))
    _fetch(db_session, lambda request: httpx.Response(200, content=b"<html>x</html>"))
    db_session.refresh(row)
    assert (row.fetch_status, row.content_blob) == ("FAILED", None)


def test_oversized_body_fails(db_session, public_host, monkeypatch):
    monkeypatch.setattr(mo_media, "MAX_BYTES", 10)
    row = _add_media(db_session, _add_mo(db_session, info=_info()))
    _fetch(db_session, lambda request: httpx.Response(200, content=_JPEG))
    db_session.refresh(row)
    assert (row.fetch_status, row.error) == ("FAILED", "크기 초과")


@pytest.mark.parametrize("url", ["http://image.example-carrier.test/a.jpg", "https://10.0.5.204/a.jpg"])
def test_refuses_non_https_or_private_address(db_session, url):
    row = _add_media(db_session, _add_mo(db_session, info=_info(url=url)))
    calls = []
    _fetch(db_session, lambda request: calls.append(1) or httpx.Response(200, content=_JPEG))
    db_session.refresh(row)
    assert row.fetch_status == "FAILED" and calls == []


def test_redirect_to_private_address_is_refused(db_session, monkeypatch):
    async def fake_getaddrinfo(self, host, port, **kw):
        ip = "1.1.1.1" if host == "image.example-carrier.test" else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]
    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", fake_getaddrinfo)
    row = _add_media(db_session, _add_mo(db_session, info=_info()))
    seen = []

    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(302, headers={"location": "https://internal.test/x.jpg"})

    _fetch(db_session, handler)
    db_session.refresh(row)
    assert (row.fetch_status, row.error, seen) == ("FAILED", "공인 주소가 아님", ["image.example-carrier.test"])


def test_concurrent_fetches_open_url_once(db_session, session_factory, public_host):
    """BackgroundTask 와 주기 작업이 겹쳐도 같은 일회성 주소는 한 번만 연다."""
    row = _add_media(db_session, _add_mo(db_session, info=_info()))
    calls = []

    async def handler(request):
        calls.append(1)
        await asyncio.sleep(0.01)
        return httpx.Response(200, content=_JPEG)

    async def run():
        other = session_factory()
        try:
            async with _client(handler) as client:
                await asyncio.gather(
                    mo_media.fetch_pending(db_session, client=client),
                    mo_media.fetch_pending(other, client=client),
                )
        finally:
            other.close()

    asyncio.run(run())
    db_session.refresh(row)
    assert (row.fetch_status, len(calls)) == ("FETCHED", 1)


def test_stale_fetching_row_gets_another_turn(db_session, public_host):
    row = _add_media(db_session, _add_mo(db_session, info=_info()), status="FETCHING",
                     locked_at="2026-01-01T00:00:00+00:00")
    _fetch(db_session, lambda request: httpx.Response(200, content=_JPEG))
    db_session.refresh(row)
    assert row.fetch_status == "FETCHED"


# ── 대화방 표시 ──────────────────────────────────────────────────────────────


def _thread_messages(db):
    return api_get_thread(f"chatbot:{_PHONE}", db=db)["data"]["messages"]


def test_thread_exposes_attachment_status_and_url(db_session):
    ready = _add_mo(db_session, key="a", info=_info())
    _add_media(db_session, ready, "FETCHED", content_type="image/jpeg", content_blob=_JPEG)
    _add_media(db_session, _add_mo(db_session, key="b", info=_info()), "PENDING")
    _add_media(db_session, _add_mo(db_session, key="c", info=_info()), "FAILED")
    _add_media(db_session, _add_mo(db_session, key="d", info=_info(mime="video/mp4")), "UNSUPPORTED")
    _add_mo(db_session, key="e", text="글만")
    db_session.commit()

    by_id = {m["id"]: m for m in _thread_messages(db_session)}
    assert by_id[f"m-in-{ready.id}"]["attachment"] == {
        "kind": "image", "status": "ready", "url": f"/api/chat/media/{ready.id}",
    }
    assert [m.get("attachment", {}).get("status") for m in by_id.values()] == [
        "ready", "pending", "failed", "unsupported", None,
    ]
    assert all("url" not in (m.get("attachment") or {}) for m in list(by_id.values())[1:])


def test_media_endpoint_serves_only_fetched_image(db_session):
    ready = _add_mo(db_session, key="a", info=_info())
    _add_media(db_session, ready, "FETCHED", content_type="image/jpeg", content_blob=_JPEG)
    pending = _add_mo(db_session, key="b", info=_info())
    _add_media(db_session, pending, "PENDING")

    resp = api_get_mo_media(ready.id, db=db_session)
    assert resp.status_code == 200 and resp.body == _JPEG
    assert resp.headers["content-type"] == "image/jpeg"
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in resp.headers["content-security-policy"]
    assert resp.headers["cache-control"].startswith("private")
    assert api_get_mo_media(pending.id, db=db_session).status_code == 404
    assert api_get_mo_media(999, db=db_session).status_code == 404


def test_image_only_reply_previews_as_photo(db_session):
    _add_mo(db_session, key="a", info=_info())
    db_session.commit()
    assert _batch_last_mo_bodies(db_session, [_PHONE]) == {_PHONE: "[사진]"}

    _add_media(db_session, db_session.scalar(select(MoMessage)), "PENDING")
    assert api_get_thread(f"chatbot:{_PHONE}", db=db_session)["data"]["preview"] == "[사진]"


def test_preview_labels(db_session):
    assert mo_media.display_text("본문", json.dumps(_info())) == "본문"
    assert mo_media.display_text(None, json.dumps(_info())) == "[사진]"
    assert mo_media.display_text(None, json.dumps(_info(mime="video/mp4"))) == "[첨부 파일]"
    assert mo_media.display_text(None, "not json") == ""
    _add_mo(db_session, key="v", info=_info(mime="video/mp4"))
    _add_mo(db_session, key="bad", text=None)
    db_session.execute(MoMessage.__table__.update().where(MoMessage.mo_key == "bad").values(
        content_info_lst="not json", mo_number="01000000000"))
    db_session.commit()
    assert _batch_last_mo_bodies(db_session, [_PHONE, "01000000000"]) == {
        _PHONE: "[첨부 파일]", "01000000000": "",
    }


# ── 소급 마이그레이션 ────────────────────────────────────────────────────────


def test_migration_backfills_existing_file_replies(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    Base.metadata.tables["mo_messages"].create(engine)
    rows = [
        (1, json.dumps(_info())),
        (2, json.dumps(_info(mime="image/png"))),
        (3, json.dumps(_info(mime="video/mp4"))),
        (4, json.dumps(_info(url=None, text="글"))),
        (5, None),
        (6, "not json"),
    ]
    module = ScriptDirectory.from_config(_config()).get_revision("0026").module
    with engine.begin() as conn:
        for mo_id, info in rows:
            conn.exec_driver_sql(
                "INSERT INTO mo_messages (id, mo_key, mo_number, content_cnt, content_info_lst,"
                " raw_payload, received_at) VALUES (?, ?, ?, 0, ?, '{}', ?)",
                (mo_id, f"k{mo_id}", _PHONE, info, _NOW),
            )
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        got = list(conn.exec_driver_sql(
            "SELECT mo_id, declared_mime, fetch_status, fetch_attempts FROM mo_media ORDER BY mo_id"
        ))
        assert got == [
            (1, "image/jpeg", "PENDING", 0),
            (2, "image/png", "PENDING", 0),
            (3, "video/mp4", "UNSUPPORTED", 0),
        ]
        with Operations.context(MigrationContext.configure(conn)):
            module.downgrade()
    engine.dispose()


def test_finished_fetch_refreshes_open_threads(db_session, public_host, monkeypatch):
    published = []
    monkeypatch.setattr(mo_media.events, "publish_throttled", published.append)
    _add_media(db_session, _add_mo(db_session, info=_info()))

    _fetch(db_session, lambda request: httpx.Response(503))
    assert published == []  # 아직 기다리는 중 — 화면이 바뀔 게 없다
    db_session.execute(MoMedia.__table__.update().values(next_fetch_at=None))
    db_session.commit()
    _fetch(db_session, lambda request: httpx.Response(200, content=_JPEG))
    assert published == ["message.new"]
