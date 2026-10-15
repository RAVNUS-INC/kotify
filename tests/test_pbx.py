"""사내 PBX(VitalPBX) 연동 — 팩스 발송·결과 추적, 통화 기록, 녹음 재생.

실제 PBX 는 호출하지 않는다. httpx 요청은 respx 로 가로채고, 앱은 인메모리 DB
(StaticPool)로 띄운 뒤 세션 대신 가짜 사용자로 로그인한다.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.auth.deps as deps
from app.db import Base, get_db
from app.main import app
from app.models import AuditLog, FaxJob, User
from app.pbx.client import PbxClient, PbxError, load_pbx_config
from app.security.crypto import get_fernet
from app.security.settings_store import SettingsStore
from app.services import calls as calls_service
from app.services import fax as fax_service

BASE = "https://10.0.5.10:4430"
TENANT = "tenant-test"
APP_KEY = "test-app-key-0000"
PDF = b"%PDF-1.4\n% test fax\n%%EOF\n"
# 가상 번호 — 실제 연락처 아님
CUSTOMER = "01000000001"
FAX_TO = "0200000001"
REC_PATH = f"/vrecordings/{TENANT}/2026/10/15/120000-IN-NONE-{CUSTOMER}-1760000000.1.wav"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@pytest.fixture
def db_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def _get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db
    db = factory()
    SettingsStore(db).mark_bootstrap_completed("test")
    for sub, roles in (("sub-sender", ["sender"]), ("sub-admin", ["admin"]), ("sub-other", ["sender"])):
        db.add(User(sub=sub, email=f"{sub}@example.com", name=sub, display_name=sub,
                    roles=json.dumps(roles), created_at=_now_iso(), last_login_at=_now_iso()))
    db.commit()
    db.close()
    yield factory
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


@pytest.fixture
def configure(db_factory):
    def _configure(**overrides: str) -> None:
        db = db_factory()
        store = SettingsStore(db)
        values = {
            "pbx.tenant": TENANT,
            "pbx.app_key": APP_KEY,
            "pbx.fax_device_id": "2",
            "pbx.fax_fetch_base_url": "http://10.0.5.204:3000",
            **overrides,
        }
        for key, value in values.items():
            store.set(key, value, is_secret=key == "pbx.app_key", updated_by=None)
        db.commit()
        db.close()

    return _configure


@pytest.fixture
def client(db_factory):
    return TestClient(app)


@pytest.fixture
def login_as(monkeypatch):
    def _login(sub: str, *roles: str) -> None:
        def _fake_current_user(request, db):
            return User(sub=sub, email=f"{sub}@example.com", name=sub, display_name=sub,
                        roles=json.dumps(list(roles)), created_at=_now_iso(),
                        last_login_at=_now_iso())

        monkeypatch.setattr(deps, "get_current_user", _fake_current_user)

    return _login


def _cdr_row(**overrides) -> dict:
    row = {
        "cdr_id": 544,
        "calldate_ts": 1760497200,  # 2025-10-15 03:00:00 UTC
        "calldate": "2025-10-15 12:00:00",
        "source": CUSTOMER,
        "destination": "101",
        "duration": 11,
        "billsec": 9,
        "channel": "PJSIP/trunk-0001",
        "dstchannel": "PJSIP/101-0000000e",
        "lastdata": "PJSIP/101/sip:101@192.0.2.10",
        "calltype": "2",
        "recfile": f"/var/spool/asterisk/monitor/2026/10/15/x-{CUSTOMER}.wav",
        "disposition": "ANSWERED",
        "recording_url": f"https://time.example.com:4430{REC_PATH}",
    }
    row.update(overrides)
    return row


def _ok(data) -> httpx.Response:
    return httpx.Response(200, json={"status": "success", "message": None, "data": data})


# ── 설정·클라이언트 ─────────────────────────────────────────────────────────


def test_config_is_none_without_key(db_factory):
    db = db_factory()
    SettingsStore(db).set("pbx.tenant", TENANT, is_secret=False, updated_by=None)
    assert load_pbx_config(db) is None
    db.close()


async def test_client_sends_key_headers_and_unwraps(db_factory, configure):
    configure()
    db = db_factory()
    config = load_pbx_config(db)
    db.close()
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/api/v2/cdr").mock(return_value=_ok({"result": [_cdr_row()]}))
        rows = await PbxClient(config).list_cdr({"limit": "1"})
    assert rows[0]["cdr_id"] == 544
    sent = route.calls.last.request
    assert sent.headers["app-key"] == APP_KEY
    assert sent.headers["tenant"] == TENANT


@pytest.mark.parametrize(
    ("response", "code", "uncertain"),
    [
        (httpx.Response(200, json={"status": "error", "message": f"bad {CUSTOMER}"}), "rejected", False),
        (httpx.Response(401, json={"status": "error"}), "http_401", False),
        (httpx.Response(503, text="down"), "http_503", True),
        (httpx.Response(200, text="<html>"), "bad_response", True),
        (httpx.ReadTimeout("slow"), "timeout", True),
    ],
)
async def test_client_errors_are_classified_without_pii_in_logs(
    db_factory, configure, caplog, response, code, uncertain
):
    configure()
    db = db_factory()
    config = load_pbx_config(db)
    db.close()
    # 운영은 루트 로거 WARNING(uvicorn 기본) — httpx 의 INFO 요청 로그는 나가지 않는다.
    caplog.set_level(logging.WARNING)
    caplog.set_level(logging.DEBUG, logger="app.pbx.client")
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/api/v2/cdr")
        if isinstance(response, Exception):
            route.mock(side_effect=response)
        else:
            route.mock(return_value=response)
        with pytest.raises(PbxError) as info:
            await PbxClient(config).list_cdr({"extensions": CUSTOMER})
    assert info.value.code == code
    assert info.value.uncertain is uncertain
    assert CUSTOMER not in caplog.text
    assert APP_KEY not in caplog.text


# ── 통화 기록 ───────────────────────────────────────────────────────────────


def test_calls_for_customer_hide_raw_fields(client, configure, login_as):
    configure()
    login_as("sub-sender", "sender")
    rows = [_cdr_row(cdr_id=i) for i in range(3)]
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/api/v2/cdr").mock(return_value=_ok({"result": rows}))
        res = client.get("/pbx/calls", params={"phone": "010-0000-0001", "type": "in", "limit": 2})
    assert res.status_code == 200, res.text
    params = route.calls.last.request.url.params
    assert params["extensions"] == f"{CUSTOMER},{CUSTOMER[1:]},82{CUSTOMER[1:]}"
    assert params["calltype"] == "2"
    assert params["limit"] == "0,3"
    assert params["order_type"] == "desc"
    body = res.json()
    assert body["meta"]["hasMore"] is True
    assert len(body["data"]) == 2
    call = body["data"][0]
    assert call["direction"] == "in"
    assert call["from"] == CUSTOMER
    assert call["at"] == "2025-10-15T12:00:00+09:00"
    assert call["recordingToken"]
    for raw in ("recording_url", "recfile", "vrecordings", "PJSIP", "time.example.com"):
        assert raw not in res.text


def test_calls_without_phone_is_admin_only(client, configure, login_as):
    configure()
    login_as("sub-sender", "sender")
    assert client.get("/pbx/calls").status_code == 403
    login_as("sub-admin", "admin")
    with respx.mock(base_url=BASE) as mock:
        route = mock.get("/api/v2/cdr").mock(return_value=_ok({"result": []}))
        res = client.get("/pbx/calls", params={"from": "2026-10-01", "to": "2026-10-15"})
    assert res.status_code == 200
    assert "extensions" not in route.calls.last.request.url.params
    assert route.calls.last.request.url.params["start_date"] == "2026-10-01"


def test_calls_require_sender_and_configuration(client, configure, login_as):
    login_as("sub-viewer", "viewer")
    assert client.get("/pbx/calls", params={"phone": CUSTOMER}).status_code == 403
    login_as("sub-sender", "sender")
    res = client.get("/pbx/calls", params={"phone": CUSTOMER})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "pbx_not_configured"
    configure()
    assert client.get("/pbx/calls", params={"phone": CUSTOMER, "from": "20261001"}).status_code == 400


def test_calls_pbx_failure_is_502(client, configure, login_as):
    configure()
    login_as("sub-sender", "sender")
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/cdr").mock(return_value=httpx.Response(500))
        res = client.get("/pbx/calls", params={"phone": CUSTOMER})
    assert res.status_code == 502
    assert res.json()["error"]["code"] == "pbx_error"


# ── 녹음 ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "https://x/vrecordings/t/2026/10/15/../../../etc/passwd.wav",
        "https://x/api/v2/cdr",
        "https://x/vrecordings/t/2026/10/15/a.php",
        "",
        None,
    ],
)
def test_recording_path_rejects_unexpected_paths(url):
    assert calls_service.recording_path(url) is None


def _recording_token(client, login_as, sub="sub-sender") -> str:
    login_as(sub, "sender")
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/cdr").mock(return_value=_ok({"result": [_cdr_row()]}))
        res = client.get("/pbx/calls", params={"phone": CUSTOMER})
    return res.json()["data"][0]["recordingToken"]


def test_recording_streams_from_internal_host_with_range(client, configure, login_as, db_factory):
    configure()
    token = _recording_token(client, login_as)
    audio = b"RIFF" + b"\0" * 60
    with respx.mock(base_url=BASE) as mock:
        route = mock.get(REC_PATH).mock(
            return_value=httpx.Response(
                206,
                content=audio[:10],
                headers={"content-type": "audio/x-wav", "content-range": f"bytes 0-9/{len(audio)}"},
            )
        )
        res = client.get(f"/pbx/recordings/{token}", headers={"Range": "bytes=0-9"})
        assert res.status_code == 206
        assert res.content == audio[:10]
        assert res.headers["content-range"] == f"bytes 0-9/{len(audio)}"
        assert res.headers["content-type"] == "audio/x-wav"
        assert res.headers["cache-control"] == "private, no-store"
        sent = route.calls.last.request
        assert sent.headers["range"] == "bytes=0-9"
        assert "app-key" not in sent.headers  # 녹음 경로에는 키를 보내지 않는다

        # 탐색 요청은 감사 로그를 다시 남기지 않는다.
        client.get(f"/pbx/recordings/{token}", headers={"Range": "bytes=30-"})
    db = db_factory()
    logs = list(db.execute(select(AuditLog).where(AuditLog.action == "RECORDING_PLAY")).scalars())
    assert [entry.target for entry in logs] == ["cdr:544"]
    db.close()


def test_recording_token_is_bound_to_user_and_expires(client, configure, login_as):
    configure()
    token = _recording_token(client, login_as, sub="sub-sender")
    login_as("sub-other", "sender")
    assert client.get(f"/pbx/recordings/{token}").status_code == 404
    login_as("sub-sender", "sender")
    assert client.get(f"/pbx/recordings/{token[:-4]}AAAA").status_code == 404

    expired = get_fernet().encrypt_at_time(
        json.dumps({"p": REC_PATH, "u": "sub-sender", "c": "1"}).encode(),
        int(time.time()) - calls_service.RECORDING_TOKEN_TTL_SECONDS - 5,
    ).decode()
    assert client.get(f"/pbx/recordings/{expired}").status_code == 404

    forged_path = get_fernet().encrypt(
        json.dumps({"p": "/api/v2/cdr", "u": "sub-sender", "c": "1"}).encode()
    ).decode()
    assert client.get(f"/pbx/recordings/{forged_path}").status_code == 404


def test_recording_requires_sender(client, configure, login_as):
    configure()
    token = _recording_token(client, login_as)
    login_as("sub-sender", "viewer")
    assert client.get(f"/pbx/recordings/{token}").status_code == 403


# ── 팩스 발송 ───────────────────────────────────────────────────────────────


def _send(client, **overrides):
    data = {"recipient": "02-0000-0001", "resolution": "standard", **overrides.pop("data", {})}
    files = {"file": overrides.pop("file", ("견적서.pdf", PDF, "application/pdf"))}
    return client.post("/fax", data=data, files=files)


def test_fax_send_submits_signed_url_and_pbx_can_fetch(client, configure, login_as, db_factory):
    configure()
    login_as("sub-sender", "sender")
    fetched: dict = {}

    def _pbx_send(request: httpx.Request) -> httpx.Response:
        body = request.content.decode()
        fields = {}
        for part in body.split("--")[1:]:
            if 'name="' in part:
                name = part.split('name="', 1)[1].split('"', 1)[0]
                fields[name] = part.split("\r\n\r\n", 1)[1].rsplit("\r\n", 1)[0]
        fetched["fields"] = fields
        # PBX 가 이 요청 안에서 URL 의 PDF 를 받아 간다 — 행이 커밋돼 있어야 한다.
        token = fields["url"].rsplit("/", 1)[1].removesuffix(".pdf")
        db = db_factory()
        fetched["pdf"] = fax_service.fetch_pdf(db, token)
        db.close()
        return _ok({
            "device": "ttyIAX2",
            "recipients": [FAX_TO],
            "file": "/var/lib/vitalpbx/fax/tmp/1760000000.1234.pdf",
            "status": "Waiting for modem to come free\n",
        })

    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/api/v2/virtual_faxes/2/send").mock(side_effect=_pbx_send)
        res = _send(client)
    assert res.status_code == 200, res.text
    assert res.json()["data"]["status"] == "SUBMITTED"
    assert route.call_count == 1
    fields = fetched["fields"]
    assert fields["recipients"] == FAX_TO
    assert fields["resolution"] == "standard"
    assert fields["retries"] == "2"
    assert fields["url"].startswith("http://10.0.5.204:3000/api/pbx/fax-files/")
    assert fetched["pdf"] == PDF

    db = db_factory()
    job = db.execute(select(FaxJob)).scalar_one()
    assert job.pbx_file == "1760000000.1234.pdf"
    assert job.fetch_count == 1
    entry = db.execute(select(AuditLog).where(AuditLog.action == "FAX_SEND")).scalar_one()
    assert entry.target == f"fax:{job.id}"
    assert FAX_TO not in (entry.detail or "")
    db.close()


@pytest.mark.parametrize(
    ("response", "status"),
    [
        (httpx.Response(200, json={"status": "error", "message": "invalid"}), "FAILED"),
        (httpx.ReadTimeout("slow"), "UNKNOWN"),
        (httpx.Response(502), "UNKNOWN"),
    ],
)
def test_fax_send_failure_states_never_retry(client, configure, login_as, response, status):
    configure()
    login_as("sub-sender", "sender")
    with respx.mock(base_url=BASE) as mock:
        route = mock.post("/api/v2/virtual_faxes/2/send")
        if isinstance(response, Exception):
            route.mock(side_effect=response)
        else:
            route.mock(return_value=response)
        res = _send(client)
    assert res.status_code == 200
    assert res.json()["data"]["status"] == status
    assert route.call_count == 1


@pytest.mark.parametrize(
    ("kwargs", "code", "http"),
    [
        ({"data": {"recipient": "12345"}}, "invalid_recipient", 400),
        ({"data": {"resolution": "ultra"}}, "invalid_resolution", 400),
        ({"file": ("a.pdf", b"not a pdf", "application/pdf")}, "not_pdf", 400),
        ({"file": ("a.pdf", b"", "application/pdf")}, "empty_file", 400),
        ({"file": ("a.pdf", b"%PDF-" + b"0" * fax_service.MAX_PDF_BYTES, "application/pdf")},
         "file_too_large", 413),
    ],
)
def test_fax_send_validation(client, configure, login_as, kwargs, code, http):
    configure()
    login_as("sub-sender", "sender")
    res = _send(client, **kwargs)
    assert res.status_code == http
    assert res.json()["error"]["code"] == code


def test_fax_send_requires_sender_config_and_free_line(client, configure, login_as, db_factory):
    login_as("sub-viewer", "viewer")
    assert _send(client).status_code == 403
    login_as("sub-sender", "sender")
    assert _send(client).status_code == 409  # 미설정
    configure()
    db = db_factory()
    for _ in range(fax_service.MAX_IN_FLIGHT):
        db.add(FaxJob(created_by="sub-other", recipient=FAX_TO, original_filename="a.pdf",
                      pdf_blob=PDF, file_size_bytes=len(PDF), resolution="standard", retries=2,
                      retry_time=300, status="SUBMITTED", fetch_count=0, created_at=_now_iso()))
    db.commit()
    db.close()
    res = _send(client)
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "fax_busy"


def _job(db, **overrides) -> FaxJob:
    values = dict(created_by="sub-sender", recipient=FAX_TO, original_filename="a.pdf",
                  pdf_blob=PDF, file_size_bytes=len(PDF), resolution="standard", retries=2,
                  retry_time=300, status="SUBMITTED", fetch_count=0, created_at=_now_iso())
    values.update(overrides)
    job = FaxJob(**values)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def test_fetch_endpoint_rejects_bad_expired_closed_and_overused(client, db_factory):
    db = db_factory()
    job = _job(db, status="QUEUED")
    good = fax_service.make_fetch_token(db, job.id)
    old = fax_service.make_fetch_token(db, job.id, now=time.time() - fax_service.FETCH_URL_TTL_SECONDS - 1)
    db.close()

    assert client.get("/pbx/fax-files/garbage.pdf").status_code == 404
    assert client.get(f"/pbx/fax-files/{good[:-1]}0.pdf").status_code in (404,)
    assert client.get(f"/pbx/fax-files/{old}.pdf").status_code == 404
    res = client.get(f"/pbx/fax-files/{good}.pdf")
    assert res.status_code == 200
    assert res.content == PDF
    assert res.headers["content-type"] == "application/pdf"
    for _ in range(fax_service.MAX_FETCHES - 1):
        assert client.get(f"/pbx/fax-files/{good}.pdf").status_code == 200
    assert client.get(f"/pbx/fax-files/{good}.pdf").status_code == 404

    db = db_factory()
    closed = _job(db, status="SENT")
    token = fax_service.make_fetch_token(db, closed.id)
    db.close()
    assert client.get(f"/pbx/fax-files/{token}.pdf").status_code == 404


def test_fax_list_scoping_resend_and_pdf_view(client, configure, login_as, db_factory):
    configure()
    db = db_factory()
    mine = _job(db, status="FAILED").id
    theirs = _job(db, created_by="sub-other", status="SENT").id
    db.close()

    login_as("sub-sender", "sender")
    ids = [row["id"] for row in client.get("/fax").json()["data"]]
    assert ids == [mine]
    assert client.get(f"/fax/{theirs}/pdf").status_code == 404
    assert client.get(f"/fax/{mine}/pdf").content == PDF
    assert client.post(f"/fax/{theirs}/resend").status_code == 404

    with respx.mock(base_url=BASE) as mock:
        mock.post("/api/v2/virtual_faxes/2/send").mock(return_value=_ok({"file": "/tmp/9.pdf"}))
        res = client.post(f"/fax/{mine}/resend")
    assert res.status_code == 200
    assert res.json()["data"]["id"] not in (mine, theirs)

    login_as("sub-admin", "admin")
    assert len(client.get("/fax").json()["data"]) == 3


# ── 결과 추적 ───────────────────────────────────────────────────────────────


async def test_track_scans_logs_forward_and_matches_by_file(db_factory, configure):
    configure()
    db = db_factory()
    sent = _job(db, pbx_file="1760000000.1.pdf", submitted_at=_now_iso())
    pending = _job(db, pbx_file="1760000000.2.pdf", submitted_at=_now_iso())
    config = load_pbx_config(db)
    logs = {
        1: {"type": "Incoming", "file": "x.pdf", "status": "Received"},
        2: {"type": "Outgoing", "file": "1760000000.1.pdf", "status": "Sent", "error": ""},
        3: {"type": "Outgoing", "file": "1760000000.2.pdf", "status": "Sending"},
    }

    def _log(request: httpx.Request) -> httpx.Response:
        log_id = int(request.url.path.rsplit("/", 1)[1])
        if log_id in logs:
            return _ok(logs[log_id])
        return httpx.Response(404, json={"status": "error"})

    with respx.mock(base_url=BASE) as mock:
        route = mock.get(url__regex=r"/api/v2/virtual_faxes/log/\d+").mock(side_effect=_log)
        await fax_service.track_fax_jobs(db, config)
        db.refresh(sent)
        db.refresh(pending)
        assert (sent.status, sent.pbx_log_id) == ("SENT", 2)
        assert (pending.status, pending.pbx_log_id) == ("SUBMITTED", 3)
        assert SettingsStore(db).get("pbx.fax_log_cursor") == "3"
        # 열린 작업을 모두 찾으면 더 읽지 않는다.
        assert route.call_count == 3

        logs[3] = {"type": "Outgoing", "file": "1760000000.2.pdf", "status": "Failed",
                   "error": "The call dropped prematurely"}
        await fax_service.track_fax_jobs(db, config)
        db.refresh(pending)
    assert pending.status == "FAILED"
    assert pending.error == "The call dropped prematurely"
    db.close()


async def test_track_falls_back_to_recipient_and_time(db_factory, configure):
    configure()
    db = db_factory()
    created = datetime.now(UTC) - timedelta(minutes=3)
    job = _job(db, status="UNKNOWN", pbx_file=None, created_at=created.isoformat())
    config = load_pbx_config(db)
    entry = {"type": "Outgoing", "file": "other.pdf", "recipient": FAX_TO,
             "unix_date": str(int(created.timestamp()) + 30), "status": "Sent"}
    with respx.mock(base_url=BASE, assert_all_called=False) as mock:
        mock.get(url__regex=r"/api/v2/virtual_faxes/log/1$").mock(return_value=_ok(entry))
        mock.get(url__regex=r"/api/v2/virtual_faxes/log/\d+").mock(return_value=httpx.Response(404))
        await fax_service.track_fax_jobs(db, config)
    db.refresh(job)
    assert (job.status, job.pbx_log_id) == ("SENT", 1)
    db.close()


async def test_track_marks_old_unmatched_and_stale_queued_unknown(db_factory, configure):
    configure()
    db = db_factory()
    old = (datetime.now(UTC) - fax_service.MATCH_DEADLINE - timedelta(minutes=1)).isoformat()
    submitted = _job(db, pbx_file="never.pdf", created_at=old, submitted_at=old)
    queued = _job(db, status="QUEUED", created_at=old)
    config = load_pbx_config(db)
    with respx.mock(base_url=BASE) as mock:
        route = mock.get(url__regex=r"/api/v2/virtual_faxes/log/\d+").mock(
            return_value=httpx.Response(404)
        )
        await fax_service.track_fax_jobs(db, config)
    # 빈 ID 가 LOG_SCAN_MISSES 개 이어지면 멈추고 커서는 그대로다.
    assert route.call_count == fax_service.LOG_SCAN_MISSES
    assert SettingsStore(db).get("pbx.fax_log_cursor") == "0"
    db.refresh(submitted)
    db.refresh(queued)
    assert submitted.status == "UNKNOWN"
    assert queued.status == "UNKNOWN"
    db.close()


@pytest.mark.parametrize(
    ("status", "expected"),
    [("Sent", "SENT"), ("Failed", "FAILED"), ("Busy", "FAILED"), ("Sending", None), ("", None)],
)
def test_map_log_status(status, expected):
    assert fax_service.map_log_status(status) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("02-0000-0001", "0200000001"), ("+82 2 0000 0001", "0200000001"),
     ("031-000-0000", "0310000000"), ("1234", None), ("10000000001", None)],
)
def test_normalize_fax_number(raw, expected):
    assert fax_service.normalize_fax_number(raw) == expected


# ── 설정 ───────────────────────────────────────────────────────────────────


def test_settings_store_pbx_key_encrypted_and_masked(client, login_as, db_factory):
    login_as("sub-admin", "admin")
    res = client.patch("/settings/provider", json={
        "pbxTenant": TENANT, "pbxAppKey": APP_KEY, "pbxTlsVerify": "false",
        "pbxFaxDeviceId": "2", "pbxFaxFetchBaseUrl": "http://10.0.5.204:3000",
    })
    assert res.status_code == 200, res.text
    got = client.get("/settings/provider").json()["data"]
    assert got["public"]["pbxTenant"] == TENANT
    assert got["secrets"]["pbxAppKey"]["configured"] is True
    assert APP_KEY not in json.dumps(got)
    db = db_factory()
    assert load_pbx_config(db).app_key == APP_KEY
    db.close()


def test_pbx_test_reports_device_without_secret(client, configure, login_as):
    configure()
    login_as("sub-admin", "admin")
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/cdr").mock(return_value=_ok({"result": []}))
        mock.get("/api/v2/virtual_faxes/2").mock(
            return_value=_ok({"id": 2, "description": "RAVNUS", "secret": "device-secret",
                              "cid_number": FAX_TO})
        )
        res = client.post("/pbx/test")
    assert res.status_code == 200
    assert res.json()["data"]["message"] == "연결 성공 · 팩스 장치 RAVNUS"
    assert "device-secret" not in res.text
    assert FAX_TO not in res.text
    login_as("sub-sender", "sender")
    assert client.post("/pbx/test").status_code == 403
