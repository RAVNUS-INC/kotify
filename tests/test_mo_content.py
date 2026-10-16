"""MMS MO 첨부 — 웹훅 뒤 받아 보관, 실패하면 7일 안에서 재시도, 대화방에 표시 (19-mo)."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.models import MoMessage
from app.msghub.client import MsghubClient
from app.msghub.schemas import MsghubAuthError, MsghubBadRequest, MsghubServerError
from app.routes.threads import api_get_thread, get_mo_content
from app.routes.webhook import receive_mo
from app.services import mo_content
from tests.test_mo_webhook import _mo_request, _setup_token

_NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
_JPEG = b"\xff\xd8\xff\xe0fake-jpeg"


def _mo(db, *, key="mk-1", received=_NOW, status="PENDING", attempts=0, next_at=None, title=None):
    mo = MoMessage(
        mo_key=key, mo_number="01011112222", mo_callback="0212345678", mo_type="MMSMO",
        mo_title=title, mo_msg="사진 보냅니다", content_cnt=1, raw_payload="{}",
        received_at=received.isoformat(), content_fetch_status=status,
        content_fetch_attempts=attempts, content_next_fetch_at=next_at,
    )
    db.add(mo)
    db.commit()
    return mo


class _Client:
    def __init__(self, *results):
        self.results = list(results)
        self.keys: list[str] = []

    async def fetch_mo_content(self, mo_key, *, max_bytes):
        self.keys.append(mo_key)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


# ── 웹훅 ─────────────────────────────────────────────────────────────────────


def test_webhook_marks_mms_mo_pending_and_schedules_fetch(db_session, monkeypatch):
    _setup_token(db_session)
    body = {"moCnt": 2, "moLst": [
        {"moKey": "mms-1", "moNumber": "0212345678", "moCallback": "01011112222", "moType": "MMSMO",
         "moTitle": "사진", "moMsg": "", "contentCnt": 1,
         "contentInfoLst": [{"contentName": "a.jpg", "contentExt": "jpg"}]},
        {"moKey": "sms-1", "moNumber": "0212345678", "moCallback": "01011112222", "moType": "SMSMO",
         "moMsg": "글만"},
    ]}
    resp = asyncio.run(receive_mo("wtok", _mo_request(body), db_session))

    assert resp.status_code == 200
    rows = {r.mo_key: r for r in db_session.execute(select(MoMessage)).scalars()}
    assert rows["mms-1"].content_fetch_status == "PENDING"
    assert rows["sms-1"].content_fetch_status is None
    [task] = resp.background.tasks
    assert task.func is mo_content.fetch_new and task.args == ([rows["mms-1"].id],)


def test_webhook_warns_on_unknown_mo_format(db_session, caplog):
    _setup_token(db_session)
    with caplog.at_level(logging.WARNING, logger="app.routes.webhook"):
        resp = asyncio.run(receive_mo("wtok", _mo_request({"newLst": [{"phone": "01011112222"}]}), db_session))
    assert resp.status_code == 200
    assert "모르는 MO 페이로드 형식" in caplog.text
    assert "01011112222" not in caplog.text


# ── 가져오기 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_stores_content(db_session):
    mo = _mo(db_session)
    assert await mo_content.fetch_pending(db_session, _Client((_JPEG, "image/jpeg")), now=_NOW) == 1
    assert (mo.content_fetch_status, mo.content_type, mo.content_size) == ("FETCHED", "image/jpeg", len(_JPEG))
    assert mo.content_blob == _JPEG


@pytest.mark.asyncio
async def test_failed_fetch_backs_off_then_retries(db_session):
    mo = _mo(db_session)
    client = _Client(MsghubServerError("HTTP 503", code="HTTP_ERROR"), (_JPEG, "image/png"))

    await mo_content.fetch_pending(db_session, client, now=_NOW)
    assert (mo.content_fetch_status, mo.content_fetch_attempts) == ("FAILED", 1)
    assert mo.content_next_fetch_at == (_NOW + timedelta(minutes=1)).isoformat()

    await mo_content.fetch_pending(db_session, client, now=_NOW + timedelta(seconds=30))
    assert client.keys == ["mk-1"]  # 아직 대기 시각 전

    await mo_content.fetch_pending(db_session, client, now=_NOW + timedelta(minutes=2))
    assert mo.content_fetch_status == "FETCHED"


@pytest.mark.asyncio
async def test_fetch_gives_up_after_retention_or_attempts(db_session):
    old = _mo(db_session, key="old", received=_NOW - timedelta(days=8))
    tired = _mo(db_session, key="tired", attempts=mo_content.MAX_ATTEMPTS - 1, status="FAILED")
    big = _mo(db_session, key="big")
    client = _Client(
        MsghubServerError("HTTP 503", code="HTTP_ERROR"),
        MsghubBadRequest("상한 초과", code="TOO_LARGE"),
    )
    await mo_content.fetch_pending(db_session, client, now=_NOW)

    assert client.keys == ["tired", "big"]  # 7일 지난 건 요청하지 않는다
    assert {m.mo_key: m.content_fetch_status for m in (old, tired, big)} == {
        "old": "EXPIRED", "tired": "EXPIRED", "big": "EXPIRED",
    }


@pytest.mark.asyncio
async def test_auth_error_stops_batch_without_counting(db_session):
    first = _mo(db_session, key="a")
    _mo(db_session, key="b")
    client = _Client(MsghubAuthError("[20002] 패스워드 불일치", code="20002"))
    await mo_content.fetch_pending(db_session, client, now=_NOW)
    assert client.keys == ["a"]
    assert (first.content_fetch_status, first.content_fetch_attempts) == ("PENDING", 0)


# ── 클라이언트 ───────────────────────────────────────────────────────────────


def _http_client(handler) -> MsghubClient:
    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/auth/v1/"):
            return httpx.Response(200, json={"code": "10000", "data": {"token": "t", "refreshToken": "r"}})
        return handler(request)

    client = MsghubClient("qa", "key", "pwd")
    http = httpx.AsyncClient(transport=httpx.MockTransport(route))
    client._http = http
    client._token_mgr._http = http
    return client


@pytest.mark.asyncio
async def test_client_returns_file_body():
    def handler(request):
        assert request.url.raw_path == b"/mo/v1/file/mk%2F1"
        return httpx.Response(200, content=_JPEG, headers={"content-type": "image/jpeg; charset=binary"})

    body, ctype = await _http_client(handler).fetch_mo_content("mk/1", max_bytes=1024)
    assert (body, ctype) == (_JPEG, "image/jpeg")


@pytest.mark.asyncio
async def test_client_raises_on_json_error_and_size_limit():
    client = _http_client(lambda r: httpx.Response(
        400, content=json.dumps({"code": "29005", "message": "없음"}), headers={"content-type": "application/json"},
    ))
    with pytest.raises(MsghubBadRequest):
        await client.fetch_mo_content("mk-1", max_bytes=1024)

    client = _http_client(lambda r: httpx.Response(200, content=b"x" * 2048, headers={"content-type": "image/png"}))
    with pytest.raises(MsghubBadRequest) as info:
        await client.fetch_mo_content("mk-1", max_bytes=1024)
    assert info.value.code == "TOO_LARGE"


# ── 대화방 표시 ──────────────────────────────────────────────────────────────


def test_thread_shows_title_and_attachment_and_serves_image(db_session):
    mo = _mo(db_session, title="견적서 사진")
    mo.content_fetch_status, mo.content_type, mo.content_blob = "FETCHED", "image/jpeg", _JPEG
    pending = _mo(db_session, key="mk-2")
    db_session.commit()

    detail = api_get_thread("0212345678:01011112222", db_session)["data"]
    them = {m["id"]: m for m in detail["messages"]}
    shown = them[f"m-in-{mo.id}"]
    assert shown["title"] == "견적서 사진"
    assert shown["kind"] == "mms"
    assert shown["attachment"] == {"status": "ready", "url": f"/api/threads/mo/{mo.id}/content", "isImage": True}
    assert them[f"m-in-{pending.id}"]["attachment"] == {"status": "pending"}

    resp = get_mo_content(mo.id, db_session)
    assert (resp.status_code, resp.media_type, resp.body) == (200, "image/jpeg", _JPEG)
    assert resp.headers["content-disposition"].startswith("inline")


def test_non_image_attachment_is_download_only(db_session):
    mo = _mo(db_session)
    mo.content_fetch_status, mo.content_type, mo.content_blob = "FETCHED", "text/html", b"<script>"
    db_session.commit()
    resp = get_mo_content(mo.id, db_session)
    assert resp.media_type == "application/octet-stream"
    assert resp.headers["content-disposition"].startswith("attachment")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert get_mo_content(9999, db_session).status_code == 404
