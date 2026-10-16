"""MMS MO 첨부 — mo_media 의 MMS_API source (msghub GET /mo/v1/file/{moKey}, 19-mo)."""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select

from app.db import Base
from app.models import MoMedia, MoMessage
from app.msghub.client import MsghubClient
from app.msghub.schemas import MsghubAuthError, MsghubBadRequest, MsghubServerError
from app.routes.threads import api_get_mo_media, api_get_thread
from app.routes.webhook import receive_mo
from app.security.settings_store import SettingsStore
from app.services import mo_media
from app.services.chat import _batch_last_mo_bodies
from app.services.notify import _mo_to_payload
from tests.test_thread_read_migration import _config

_PHONE = "01011112222"
_NOW = datetime(2026, 10, 16, 3, 0, tzinfo=UTC)
_JPEG = b"\xff\xd8\xff\xe0fake-jpeg"
_PDF = b"%PDF-1.4 fake"


def _mms(db, *, key="mk-1", ext="jpg", received=_NOW, title=None, text=None) -> MoMessage:
    mo = MoMessage(
        mo_key=key, mo_number=_PHONE, mo_callback="0212345678", mo_type="MMSMO", mo_title=title,
        mo_msg=text, content_cnt=1, content_info_lst=json.dumps([{"contentName": f"a.{ext}", "contentExt": ext}]),
        raw_payload="{}", received_at=received.isoformat(),
    )
    db.add(mo)
    db.flush()
    return mo


def _row(db, mo, status="PENDING", **kw) -> MoMedia:
    row = MoMedia(mo_id=mo.id, source="MMS_API", declared_mime=mo_media.mms_declared_mime(mo.content_info_lst),
                  fetch_status=status, fetch_attempts=kw.pop("fetch_attempts", 0), created_at=_NOW.isoformat(), **kw)
    db.add(row)
    db.commit()
    return row


class _Msghub:
    def __init__(self, *results):
        self.results = list(results)
        self.keys: list[str] = []

    async def fetch_mo_content(self, mo_key, *, max_bytes):
        self.keys.append(mo_key)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _fetch(db, msghub, now=_NOW):
    return asyncio.run(mo_media.fetch_pending(db, msghub=msghub, now=now))


# ── 웹훅 ─────────────────────────────────────────────────────────────────────


def test_webhook_records_mms_attachment_and_schedules_fetch(db_session):
    SettingsStore(db_session).set("msghub.webhook_token", "wtok", is_secret=True, updated_by="test")
    db_session.commit()
    request = MagicMock()
    request.json = AsyncMock(return_value={"moCnt": 2, "moLst": [
        {"moKey": "mms-1", "moNumber": "0212345678", "moCallback": _PHONE, "moType": "MMSMO",
         "moTitle": "사진", "contentCnt": 1, "contentInfoLst": [{"contentName": "a.jpg", "contentExt": "jpg"}]},
        {"moKey": "sms-1", "moNumber": "0212345678", "moCallback": _PHONE, "moType": "SMSMO", "moMsg": "글"},
    ]})
    request.client = MagicMock()
    resp = asyncio.run(receive_mo("wtok", request, db_session))

    [row] = db_session.execute(select(MoMedia)).scalars()
    assert (row.source, row.fetch_status, row.declared_mime) == ("MMS_API", "PENDING", "image/jpeg")
    [task] = [t for t in resp.background.tasks if t.func is mo_media.fetch_new]
    assert task.args == ([row.id],)


def test_synthetic_key_mms_is_not_recorded(db_session):
    mo = _mms(db_session, key="syn-abc")
    assert mo_media.record_for(db_session, mo) is None


# ── 가져오기 ─────────────────────────────────────────────────────────────────


def test_fetch_stores_image_and_non_image(db_session):
    img = _row(db_session, _mms(db_session, key="a"))
    pdf = _row(db_session, _mms(db_session, key="b", ext="pdf"))
    assert _fetch(db_session, _Msghub((_JPEG, "image/jpeg"), (_PDF, "application/pdf"))) == 2
    db_session.refresh(img)
    db_session.refresh(pdf)
    assert (img.fetch_status, img.content_type) == ("FETCHED", "image/jpeg")
    assert (pdf.fetch_status, pdf.content_type, pdf.content_blob) == ("FETCHED", "application/octet-stream", _PDF)


def test_rcs_rows_are_fetched_without_msghub_but_mms_waits(db_session):
    row = _row(db_session, _mms(db_session))
    assert asyncio.run(mo_media.fetch_pending(db_session, msghub=None)) == 0
    db_session.refresh(row)
    assert (row.fetch_status, row.fetch_attempts) == ("PENDING", 0)


def test_failed_fetch_backs_off_then_retries(db_session):
    row = _row(db_session, _mms(db_session))
    hub = _Msghub(MsghubServerError("HTTP 503", code="HTTP_ERROR"), (_JPEG, "image/jpeg"))

    _fetch(db_session, hub)
    db_session.refresh(row)
    assert (row.fetch_status, row.fetch_attempts) == ("PENDING", 1)
    assert row.next_fetch_at == (_NOW + timedelta(minutes=1)).isoformat()

    _fetch(db_session, hub, _NOW + timedelta(seconds=30))
    assert hub.keys == ["mk-1"]
    _fetch(db_session, hub, _NOW + timedelta(minutes=2))
    db_session.refresh(row)
    assert row.fetch_status == "FETCHED"


def test_gives_up_after_retention_attempts_or_too_large(db_session):
    old = _row(db_session, _mms(db_session, key="old", received=_NOW - timedelta(days=8)))
    tired = _row(db_session, _mms(db_session, key="tired"), fetch_attempts=mo_media.MAX_FETCH_ATTEMPTS["MMS_API"] - 1)
    big = _row(db_session, _mms(db_session, key="big"))
    hub = _Msghub(MsghubServerError("HTTP 503", code="HTTP_ERROR"), MsghubBadRequest("상한", code="TOO_LARGE"))
    _fetch(db_session, hub)

    assert hub.keys == ["tired", "big"]  # 7일 지난 건 요청하지 않는다
    for row in (old, tired, big):
        db_session.refresh(row)
    assert [r.fetch_status for r in (old, tired, big)] == ["FAILED", "FAILED", "FAILED"]
    assert old.error.startswith("보관 기간")


def test_permission_error_closes_row_and_continues(db_session):
    """29011(권한 없음)은 다시 받아도 같다 — 그 행만 닫고, 토큰 재발급을 부르지 않게 루프는 계속(M5)."""
    a = _row(db_session, _mms(db_session, key="a"))
    b = _row(db_session, _mms(db_session, key="b"))
    hub = _Msghub(MsghubAuthError("[29011] 권한 없음", code="29011"), (_JPEG, "image/jpeg"))
    _fetch(db_session, hub)
    db_session.refresh(a)
    db_session.refresh(b)
    assert (a.fetch_status, a.error) == ("FAILED", "권한 없음 [29011]")
    assert b.fetch_status == "FETCHED"


def test_other_auth_error_stops_batch_without_counting(db_session):
    a = _row(db_session, _mms(db_session, key="a"))
    _row(db_session, _mms(db_session, key="b"))
    hub = _Msghub(MsghubAuthError("[20002] 패스워드 불일치", code="20002"))
    _fetch(db_session, hub)
    db_session.refresh(a)
    assert hub.keys == ["a"]
    assert (a.fetch_status, a.fetch_attempts, a.locked_at) == ("PENDING", 0, None)


def test_row_time_limit(db_session, monkeypatch):
    monkeypatch.setattr(mo_media, "ROW_TIMEOUT", 0.01)
    row = _row(db_session, _mms(db_session))

    class _Slow:
        async def fetch_mo_content(self, mo_key, *, max_bytes):
            await asyncio.sleep(1)

    _fetch(db_session, _Slow())
    db_session.refresh(row)
    assert (row.fetch_status, row.error) == ("PENDING", "시간 초과")


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

    assert await _http_client(handler).fetch_mo_content("mk/1", max_bytes=1024) == (_JPEG, "image/jpeg")


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


# ── 대화방·알림 표시 ─────────────────────────────────────────────────────────


def test_thread_shows_title_and_kinds(db_session):
    img = _mms(db_session, key="a", title="견적서 사진")
    _row(db_session, img, "FETCHED", content_type="image/jpeg", content_blob=_JPEG)
    pdf = _mms(db_session, key="b", ext="pdf")
    _row(db_session, pdf, "FETCHED", content_type="application/octet-stream", content_blob=_PDF)
    waiting = _mms(db_session, key="c", ext="pdf")
    _row(db_session, waiting)

    by_id = {m["id"]: m for m in api_get_thread(f"0212345678:{_PHONE}", db=db_session)["data"]["messages"]}
    shown = by_id[f"m-in-{img.id}"]
    assert (shown["title"], shown["kind"]) == ("견적서 사진", "mms")
    assert shown["attachment"] == {"kind": "image", "status": "ready", "url": f"/api/chat/media/{img.id}"}
    assert by_id[f"m-in-{pdf.id}"]["attachment"]["kind"] == "file"
    assert by_id[f"m-in-{waiting.id}"]["attachment"] == {"kind": "file", "status": "pending"}

    resp = api_get_mo_media(pdf.id, db=db_session)
    assert (resp.status_code, resp.body) == (200, _PDF)
    assert resp.headers["content-type"] == "application/octet-stream"
    assert resp.headers["content-disposition"].startswith("attachment")
    assert "sandbox" in resp.headers["content-security-policy"]
    assert api_get_mo_media(img.id, db=db_session).headers["content-disposition"].startswith("inline")


def test_mms_preview_and_notification_labels(db_session):
    photo = _mms(db_session, key="a")
    db_session.commit()
    assert _batch_last_mo_bodies(db_session, [_PHONE]) == {_PHONE: "[사진]"}
    assert _mo_to_payload(photo)["text"] == "[사진]"

    pdf = _mms(db_session, key="b", ext="pdf", received=_NOW + timedelta(minutes=1))
    db_session.commit()
    assert _batch_last_mo_bodies(db_session, [_PHONE]) == {_PHONE: "[첨부 파일]"}
    assert _mo_to_payload(pdf)["text"] == "[첨부 파일]"
    assert mo_media.display_text("글", pdf.content_info_lst, 1) == "글"


# ── 소급 마이그레이션 ────────────────────────────────────────────────────────


def test_migration_backfills_mms_and_rcs_once(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    Base.metadata.tables["mo_messages"].create(engine)
    rcs = json.dumps({"fileMessage": {"fileMIMEType": "image/jpeg", "fileUrl": "https://x.test/a"}})
    mms = json.dumps([{"contentExt": "jpg"}])
    rows = [
        (1, "k1", 0, rcs),          # RCS 사진
        (2, "k2", 1, mms),          # MMS 첨부
        (3, "syn-x", 1, mms),       # 대체 키 — 조회 불가
        (4, "k4", 0, None),         # 첨부 없음
        (5, "k5", 1, "not json"),   # 깨진 JSON 이어도 오류 없이 MMS 로
    ]
    module = ScriptDirectory.from_config(_config()).get_revision("0026").module
    with engine.begin() as conn:
        for mo_id, key, cnt, info in rows:
            conn.exec_driver_sql(
                "INSERT INTO mo_messages (id, mo_key, mo_number, content_cnt, content_info_lst,"
                " raw_payload, received_at) VALUES (?, ?, ?, ?, ?, '{}', ?)",
                (mo_id, key, _PHONE, cnt, info, _NOW.isoformat()),
            )
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        got = list(conn.exec_driver_sql("SELECT mo_id, source, fetch_status FROM mo_media ORDER BY mo_id"))
        assert got == [(1, "RCS_URL", "PENDING"), (2, "MMS_API", "PENDING"), (5, "MMS_API", "PENDING")]
        with Operations.context(MigrationContext.configure(conn)):
            module.downgrade()
    engine.dispose()
