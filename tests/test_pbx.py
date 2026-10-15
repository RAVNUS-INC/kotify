"""사내 PBX(VitalPBX) 연동 — 팩스 발송·결과 추적, 통화 기록, 녹음 재생.

실제 PBX 는 호출하지 않는다. httpx 요청은 respx 로 가로채고, 앱은 인메모리 DB
(StaticPool)로 띄운 뒤 세션 대신 가짜 사용자로 로그인한다.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
    # 운영 PBX 실측: extensions 는 번호 1개 정확 일치, 날짜는 UNIX 초, limit 는 숫자만.
    assert params["extensions"] == CUSTOMER
    assert params["calltype"] == "2"
    assert params["limit"] == "3"
    assert params["order_type"] == "desc"
    assert params["start_date"].isdigit() and params["end_date"].isdigit()
    body = res.json()
    assert body["meta"]["hasMore"] is True
    assert body["meta"]["nextCursor"] == "1760497200:0.1"
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
    params = route.calls.last.request.url.params
    assert "extensions" not in params
    # KST 2026-10-01 00:00:00 ~ 2026-10-15 23:59:59
    assert params["start_date"] == str(int(datetime(2026, 9, 30, 15, tzinfo=UTC).timestamp()))
    assert params["end_date"] == str(int(datetime(2026, 10, 15, 14, 59, 59, tzinfo=UTC).timestamp()))


def test_calls_require_sender_and_configuration(client, configure, login_as):
    login_as("sub-viewer", "viewer")
    assert client.get("/pbx/calls", params={"phone": CUSTOMER}).status_code == 403
    login_as("sub-sender", "sender")
    res = client.get("/pbx/calls", params={"phone": CUSTOMER})
    assert res.status_code == 409
    assert res.json()["error"]["code"] == "pbx_not_configured"
    configure()
    assert client.get("/pbx/calls", params={"phone": CUSTOMER, "from": "20261001"}).status_code == 400
    assert client.get("/pbx/calls", params={"phone": CUSTOMER, "from": "2026-02-30"}).status_code == 400
    assert client.get(
        "/pbx/calls", params={"phone": CUSTOMER, "from": "2026-10-15", "to": "2026-10-01"}
    ).status_code == 400
    assert client.get("/pbx/calls", params={"phone": CUSTOMER, "cursor": "x:y"}).status_code == 400


def test_calls_keyset_pagination_keeps_same_second_rows(client, configure, login_as):
    """page 파라미터가 무시되는 PBX — end_date 경계를 포함해 다시 받고 본 id 만 버린다."""
    configure()
    login_as("sub-sender", "sender")
    rows = [_cdr_row(cdr_id=10, calldate_ts=300), _cdr_row(cdr_id=9, calldate_ts=200),
            _cdr_row(cdr_id=8, calldate_ts=200), _cdr_row(cdr_id=7, calldate_ts=100)]

    def _cdr(request: httpx.Request) -> httpx.Response:
        p = request.url.params
        end = int(p["end_date"])
        selected = [r for r in rows if r["calldate_ts"] <= end][: int(p["limit"])]
        return _ok({"result": selected, "rows": len(rows)})

    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/cdr").mock(side_effect=_cdr)
        first = client.get("/pbx/calls", params={"phone": CUSTOMER, "limit": 2}).json()
        assert [c["id"] for c in first["data"]] == [10, 9]
        cursor = first["meta"]["nextCursor"]
        assert cursor == "200:9"
        second = client.get("/pbx/calls", params={"phone": CUSTOMER, "limit": 2, "cursor": cursor}).json()
    assert [c["id"] for c in second["data"]] == [8, 7]
    assert second["meta"]["hasMore"] is False
    assert second["meta"]["nextCursor"] is None


def test_calldate_without_ts_is_utc():
    row = _cdr_row(calldate_ts=None, calldate="2026-10-15 14:31:46")
    assert calls_service.summarize_cdr(row, "u")["at"] == "2026-10-15T23:31:46+09:00"


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
    tampered = good[:-1] + ("1" if good[-1] == "0" else "0")
    assert client.get(f"/pbx/fax-files/{tampered}.pdf").status_code == 404
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
    real = {"device_id": 2, "unix_date": str(int(time.time()))}
    logs = {
        1: {"type": "Incoming", "file": "x.pdf", "status": "Received", **real},
        2: {"type": "Outgoing", "file": "1760000000.1.pdf", "status": "Sent", "error": "", **real},
        3: {"type": "Outgoing", "file": "1760000000.2.pdf", "status": "Sending", **real},
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
        # 받은 팩스도 보아야 해서 작업을 다 찾아도 빈 ID 3개까지 읽고, 첫 주기에는
        # 커서 이전(1~3)을 한 번 더 훑는다(기존 수신 가져오기).
        assert route.call_count == 3 + fax_service.LOG_SCAN_MISSES + 3

        logs[3] = {"type": "Outgoing", "file": "1760000000.2.pdf", "status": "Failed",
                   "error": "The call dropped prematurely", **real}
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
    entry = {"type": "Outgoing", "file": "other.pdf", "recipient": FAX_TO, "device_id": 2,
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
    # 커서가 없을 때(첫 추적)는 앞쪽 빈 ID 를 길게 건너뛰다 멈추고, 커서는 그대로다.
    assert route.call_count == fax_service.LOG_DISCOVERY_MISSES
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


async def test_submit_survives_pbx_fetch_commit_on_file_wal_db(tmp_path, configure, db_factory):
    """운영과 같은 파일 SQLite(WAL)에서, 발송 요청 도중 PBX 의 PDF 내려받기가 다른
    연결로 커밋해도 발송 결과 저장이 실패하지 않아야 한다(오래된 읽기 스냅샷 쓰기 금지)."""
    from sqlalchemy import event

    from app.db import Base as _Base

    engine = create_engine(f"sqlite:///{tmp_path / 'wal.db'}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=2000")
        cur.close()

    _Base.metadata.create_all(engine)
    # 운영 SessionLocal 과 같은 옵션 (app/db.py).
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    setup = factory()
    setup.add(User(sub="sub-sender", email="s@example.com", name="s", roles='["sender"]',
                   created_at=_now_iso(), last_login_at=_now_iso()))
    store = SettingsStore(setup)
    for key, value in {"pbx.tenant": TENANT, "pbx.app_key": APP_KEY, "pbx.fax_device_id": "2",
                       "pbx.fax_fetch_base_url": "http://10.0.5.204:3000"}.items():
        store.set(key, value, is_secret=key == "pbx.app_key", updated_by=None)
    setup.commit()
    setup.close()

    db = factory()
    config = load_pbx_config(db)
    job = fax_service.create_job(db, user_sub="sub-sender", recipient=FAX_TO, filename="a.pdf",
                                 pdf=PDF, resolution="standard")

    def _pbx_send(request: httpx.Request) -> httpx.Response:
        token = request.content.decode().split("/api/pbx/fax-files/", 1)[1].split(".pdf", 1)[0]
        other = factory()
        assert fax_service.fetch_pdf(other, token) == PDF
        other.close()
        return _ok({"file": "/var/lib/vitalpbx/fax/tmp/1.2.pdf"})

    with respx.mock(base_url=BASE) as mock:
        mock.post("/api/v2/virtual_faxes/2/send").mock(side_effect=_pbx_send)
        job = await fax_service.submit_job(db, job, config)
    assert job.status == "SUBMITTED"
    check = factory()
    saved = check.get(FaxJob, job.id)
    assert (saved.status, saved.fetch_count, saved.pbx_file) == ("SUBMITTED", 1, "1.2.pdf")
    check.close()
    db.close()
    engine.dispose()


# 운영 PBX 가 없는 ID 에 돌려주는 자리표시 레코드 (2026-10-15 실측 모양)
_PLACEHOLDER = {"device": None, "device_id": None, "error": None, "file": "File Removed",
                "recipient": "", "sender": "", "status": "fax_viewer.status.", "type": "Outgoing",
                "unix_date": None}


async def test_track_skips_placeholder_ids_then_uses_short_gap(db_factory, configure):
    """실제 로그가 74번부터 있고 그 앞·뒤는 200 자리표시인 운영 상황."""
    configure()
    db = db_factory()
    now = int(time.time())
    job = _job(db, pbx_file="1760000000.1234.pdf", submitted_at=_now_iso())
    config = load_pbx_config(db)
    real = {74: {"type": "Incoming", "status": "Received", "error": "OK", "file": "fax-in-1.pdf",
                 "device_id": 2, "unix_date": str(now - 900)},
            75: {"type": "Outgoing", "status": "Sent", "error": "OK", "file": "1700000000.1111.pdf",
                 "recipient": FAX_TO, "device_id": 2, "unix_date": str(now - 800)}}
    calls: list[int] = []

    def _log(request: httpx.Request) -> httpx.Response:
        log_id = int(request.url.path.rsplit("/", 1)[1])
        calls.append(log_id)
        return _ok(real.get(log_id, _PLACEHOLDER))

    with respx.mock(base_url=BASE) as mock:
        mock.get(url__regex=r"/api/v2/virtual_faxes/log/\d+").mock(side_effect=_log)
        await fax_service.track_fax_jobs(db, config)
        # 74·75 를 찾은 뒤 짧은 빈칸(3)만 보고 멈춘다. 오래된 75(다른 파일)는 매칭하지 않는다.
        assert max(calls) == 75 + fax_service.LOG_SCAN_MISSES
        assert SettingsStore(db).get("pbx.fax_log_cursor") == "75"
        db.refresh(job)
        assert (job.status, job.pbx_log_id) == ("SUBMITTED", None)

        real[77] = {"type": "Outgoing", "status": "Sent", "error": "OK", "file": "1760000000.1234.pdf",
                    "recipient": FAX_TO, "device_id": 2, "unix_date": str(now)}
        calls.clear()
        await fax_service.track_fax_jobs(db, config)
    db.refresh(job)
    assert (job.status, job.pbx_log_id) == ("SENT", 77)
    assert calls[0] == 76  # 커서 다음부터 읽는다
    db.close()


def test_calls_attach_names_from_hiworks_then_contacts(client, configure, login_as, db_factory, monkeypatch):
    """고객 번호에 하이웍스 CID 이름, 없으면 kotify 주소록 이름. 내선끼리는 이름 없음."""
    from app.models import Contact
    from app.services import hiworks

    configure()
    login_as("sub-admin", "admin")
    other = "01000000002"
    gone = "01000000003"
    db = db_factory()
    for phone, name, active in ((other, "주소록 고객", 1), (gone, "삭제된 고객", 0)):
        db.add(Contact(name=name, phone=phone, active=active, created_by="sub-admin",
                       created_at=_now_iso(), updated_at=_now_iso()))
    db.commit()
    db.close()
    asked: list[list[str]] = []

    def _lookup(_db, phones):
        asked.append(sorted(phones))
        return {CUSTOMER: {"name": "가상", "display": "가상 고객 (가상회사)"}}

    monkeypatch.setattr(hiworks, "lookup_names", _lookup)
    rows = [
        _cdr_row(cdr_id=1),  # 수신: source 가 고객
        _cdr_row(cdr_id=2, calltype="3", source="101", destination=other),  # 발신: destination 이 고객
        _cdr_row(cdr_id=3, calltype="3", source="101", destination=gone),
        _cdr_row(cdr_id=4, calltype="1", source="101", destination="102"),  # 내선
    ]
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/cdr").mock(return_value=_ok({"result": rows}))
        res = client.get("/pbx/calls")
    names = {c["id"]: c["name"] for c in res.json()["data"]}
    assert names == {1: "가상 고객 (가상회사)", 2: "주소록 고객", 3: None, 4: None}
    assert asked == [sorted([CUSTOMER, other, gone])]  # 한 번에 조회, 내선 제외

    monkeypatch.setattr(hiworks, "lookup_names", lambda _db, phones: {})  # 하이웍스 장애·미설정
    with respx.mock(base_url=BASE) as mock:
        mock.get("/api/v2/cdr").mock(return_value=_ok({"result": rows[:1]}))
        res = client.get("/pbx/calls")
    assert res.status_code == 200
    assert res.json()["data"][0]["name"] is None


# ── 받은 팩스 ───────────────────────────────────────────────────────────────

from app.models import FaxInbox  # noqa: E402
from app.pbx import sftp as sftp_mod  # noqa: E402
from app.services import fax_inbox as inbox  # noqa: E402

SENDER = "0200000009"


def _incoming(log_id_ts: int, **overrides) -> dict:
    entry = {"type": "Incoming", "status": "Received", "error": "OK", "device_id": 2,
             "file": f"fax-in-{log_id_ts}.67.pdf", "sender": f'"{SENDER}" <{SENDER}>',
             "recipient": "0200000001", "unix_date": str(log_id_ts)}
    entry.update(overrides)
    return entry


def _log_router(logs: dict):
    def _log(request: httpx.Request) -> httpx.Response:
        log_id = int(request.url.path.rsplit("/", 1)[1])
        return _ok(logs.get(log_id, _PLACEHOLDER))
    return _log


@pytest.mark.parametrize(
    ("raw", "digits"),
    [(f'"{SENDER}" <{SENDER}>', SENDER), ("<+82200000009>", SENDER), ("0200000009", SENDER), ("", "")],
)
def test_sender_number(raw, digits):
    assert inbox.sender_number(raw) == digits


async def test_scan_records_incoming_once_and_still_matches_outgoing(db_factory, configure):
    configure()
    db = db_factory()
    SettingsStore(db).set("pbx.fax_log_cursor", "10", is_secret=False, updated_by=None)
    SettingsStore(db).set("pbx.fax_inbox_backfill_upto", "10", is_secret=False, updated_by=None)
    db.commit()
    job = _job(db, pbx_file="1760000000.1.pdf", submitted_at=_now_iso())
    now = int(time.time())
    logs = {
        11: _incoming(now - 60),
        12: {"type": "Outgoing", "status": "Sent", "error": "OK", "file": "1760000000.1.pdf",
             "device_id": 2, "unix_date": str(now)},
        13: _incoming(now, status="Failed", error="Carrier lost during fax receive",
                      file="File Removed"),
    }
    config = load_pbx_config(db)
    with respx.mock(base_url=BASE) as mock:
        mock.get(url__regex=r"/api/v2/virtual_faxes/log/\d+").mock(side_effect=_log_router(logs))
        await fax_service.track_fax_jobs(db, config)
        await fax_service.track_fax_jobs(db, config)  # 두 번 돌아도 중복 없음
    db.refresh(job)
    assert (job.status, job.pbx_log_id) == ("SENT", 12)
    rows = list(db.execute(select(FaxInbox).order_by(FaxInbox.pbx_log_id)).scalars())
    assert [(r.pbx_log_id, r.status, r.fetch_status, r.sender_number) for r in rows] == [
        (11, "RECEIVED", "PENDING", SENDER),
        (13, "FAILED", "NONE", SENDER),
    ]
    assert rows[1].error == "Carrier lost during fax receive"
    assert SettingsStore(db).get("pbx.fax_log_cursor") == "13"
    db.close()


async def test_backfill_reads_ids_before_cursor_once(db_factory, configure):
    configure()
    db = db_factory()
    SettingsStore(db).set("pbx.fax_log_cursor", "90", is_secret=False, updated_by=None)
    db.commit()
    logs = {74: _incoming(1790000000), 88: {"type": "Outgoing", "status": "Sent", "device_id": 2,
                                            "file": "1.2.pdf", "unix_date": "1790000100"}}
    config = load_pbx_config(db)
    with respx.mock(base_url=BASE) as mock:
        route = mock.get(url__regex=r"/api/v2/virtual_faxes/log/\d+").mock(side_effect=_log_router(logs))
        await fax_service.track_fax_jobs(db, config)
        first = route.call_count
        await fax_service.track_fax_jobs(db, config)
        second = route.call_count - first
    assert first == fax_service.LOG_SCAN_MISSES + 90  # 앞으로 빈칸 3 + 1~90 한 번
    assert second == fax_service.LOG_SCAN_MISSES  # 다시 훑지 않는다
    assert [r.pbx_log_id for r in db.execute(select(FaxInbox)).scalars()] == [74]
    assert SettingsStore(db).get("pbx.fax_inbox_backfill_upto") == "90"
    db.close()


def _sftp_settings(db, **overrides):
    store = SettingsStore(db)
    for key, value in {"pbx.sftp_user": "kotify-fax", **overrides}.items():
        store.set(key, value, is_secret=False, updated_by=None)
    db.commit()


def test_sftp_config_defaults_and_rejects_unsafe_values(db_factory, configure):
    configure()
    db = db_factory()
    assert sftp_mod.load_sftp_config(db) is None  # 계정 없음 = 기능 off
    _sftp_settings(db)
    cfg = sftp_mod.load_sftp_config(db)
    assert (cfg.user, cfg.host, cfg.port, cfg.directory) == (
        "kotify-fax", "10.0.5.10", "55530", "/var/lib/vitalpbx/fax/recvd")
    for bad in ({"pbx.sftp_dir": "/x/../etc"}, {"pbx.sftp_dir": "/x y"}, {"pbx.sftp_user": "a;rm"},
                {"pbx.sftp_port": "22x"}):
        _sftp_settings(db, **{"pbx.sftp_dir": "/recvd", "pbx.sftp_port": "55530"})
        _sftp_settings(db, **bad)
        assert sftp_mod.load_sftp_config(db) is None, bad
    db.close()


class _FakeProc:
    def __init__(self, behaviour, calls):
        self.behaviour, self.calls, self.returncode = behaviour, calls, None

    async def communicate(self, data):
        line = data.decode()
        self.calls[-1]["batch"] = line
        _, src, dest = line.split()
        content, rc = self.behaviour(src)
        if content is not None:
            Path(dest).write_bytes(content)
        self.returncode = rc
        return b"", b""

    def kill(self):
        pass

    async def wait(self):
        return self.returncode


def _fake_sftp(monkeypatch, behaviour):
    calls: list[dict] = []

    async def _exec(*args, **kwargs):
        calls.append({"args": list(args)})
        return _FakeProc(behaviour, calls)

    monkeypatch.setattr(sftp_mod.asyncio, "create_subprocess_exec", _exec)
    return calls


async def test_fetch_pending_gets_exact_file_with_pinned_host_key(db_factory, configure, monkeypatch):
    configure()
    db = db_factory()
    _sftp_settings(db)
    inbox.record_incoming(db, 93, _incoming(1792080356))
    db.commit()
    calls = _fake_sftp(monkeypatch, lambda src: (PDF, 0))
    assert await inbox.fetch_pending(db, sftp_mod.load_sftp_config(db)) == 1
    row = db.execute(select(FaxInbox)).scalar_one()
    assert (row.fetch_status, row.pdf_blob, row.file_size_bytes) == ("FETCHED", PDF, len(PDF))
    args = calls[0]["args"]
    assert args[0] == "sftp"
    assert "StrictHostKeyChecking=yes" in args and "BatchMode=yes" in args
    assert any(a.startswith("UserKnownHostsFile=") and a.endswith("pbx_known_hosts") for a in args)
    assert args[-1] == "kotify-fax@10.0.5.10"
    assert calls[0]["batch"].startswith("get /var/lib/vitalpbx/fax/recvd/fax-in-1792080356.67.pdf ")
    db.close()


async def test_fetch_failures_retry_then_give_up(db_factory, configure, monkeypatch):
    configure()
    db = db_factory()
    _sftp_settings(db)
    inbox.record_incoming(db, 93, _incoming(1792080356))
    inbox.record_incoming(db, 94, _incoming(1792080400))
    db.commit()
    _fake_sftp(monkeypatch, lambda src: (None, 1) if "1792080356" in src else (b"<html>", 0))
    cfg = sftp_mod.load_sftp_config(db)
    for _ in range(inbox.MAX_FETCH_ATTEMPTS + 1):
        await inbox.fetch_pending(db, cfg)
    rows = {r.pbx_log_id: r for r in db.execute(select(FaxInbox)).scalars()}
    assert (rows[93].fetch_status, rows[93].fetch_attempts) == ("FETCH_FAILED", inbox.MAX_FETCH_ATTEMPTS)
    assert (rows[94].fetch_status, rows[94].pdf_blob) == ("FETCH_FAILED", None)  # PDF 아님
    db.close()


async def test_fetch_rejects_unexpected_file_names(db_factory, configure):
    configure()
    db = db_factory()
    _sftp_settings(db)
    with pytest.raises(sftp_mod.SftpError) as info:
        await sftp_mod.fetch_inbox_pdf(sftp_mod.load_sftp_config(db), "../../etc/passwd")
    assert info.value.code == "bad_name"
    db.close()


def test_inbox_routes_permissions_names_view_and_audit(client, configure, login_as, db_factory, monkeypatch):
    from app.services import hiworks

    configure()
    db = db_factory()
    ok = inbox.record_incoming(db, 93, _incoming(1792080356))
    ok.pdf_blob, ok.file_size_bytes, ok.fetch_status = PDF, len(PDF), "FETCHED"
    pending = inbox.record_incoming(db, 94, _incoming(1792080400))
    inbox.record_incoming(db, 95, _incoming(1792080500, status="Failed", error="Timer T2 expired", file="File Removed"))
    db.commit()
    ok_id, pending_id = ok.id, pending.id
    db.close()
    monkeypatch.setattr(hiworks, "lookup_names", lambda _db, phones: {SENDER: {"display": "가상 거래처"}})

    login_as("sub-viewer", "viewer")
    assert client.get("/fax/inbox").status_code == 403
    assert client.get(f"/fax/inbox/{ok_id}/pdf").status_code == 403

    login_as("sub-sender", "sender")
    body = client.get("/fax/inbox").json()
    assert [r["status"] for r in body["data"]] == ["FAILED", "RECEIVED", "RECEIVED"]  # 최신순
    assert body["data"][0]["senderName"] == "가상 거래처"
    assert body["meta"]["unread"] == 2
    assert "fax-in-" not in json.dumps(body)  # PBX 파일 이름은 내려주지 않는다
    assert client.get(f"/fax/inbox/{pending_id}/pdf").status_code == 409
    res = client.get(f"/fax/inbox/{ok_id}/pdf")
    assert res.status_code == 200 and res.content == PDF
    assert res.headers["cache-control"] == "private, no-store"
    body = client.get("/fax/inbox").json()
    assert body["meta"]["unread"] == 1
    viewed = next(r for r in body["data"] if r["id"] == ok_id)
    assert viewed["firstViewedBy"] == "sub-sender" and viewed["firstViewedAt"]

    db = db_factory()
    assert [a.target for a in db.execute(select(AuditLog).where(AuditLog.action == "FAX_INBOX_VIEW")).scalars()] == [f"fax_inbox:{ok_id}"]
    db.close()

    assert client.post(f"/fax/inbox/{pending_id}/refetch").status_code == 403
    login_as("sub-admin", "admin")
    res = client.post(f"/fax/inbox/{pending_id}/refetch")
    assert res.status_code == 409 and res.json()["error"]["code"] == "sftp_not_configured"
