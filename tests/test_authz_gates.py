"""역할 게이트 회귀 테스트 — 발신번호 읽기/쓰기, 발송, 검색·알림의 admin 전용 데이터.

실제 app.main.app 을 인메모리 DB(StaticPool — TestClient 워커 스레드와 공유)로
띄우고, 세션 대신 `app.auth.deps.get_current_user` 를 역할별 가짜 사용자로 바꿔
라우터에 걸린 의존성 그대로 검증한다.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.auth.deps as deps
from app.db import Base, get_db
from app.main import app
from app.models import AuditLog, User
from app.security.settings_store import SettingsStore

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


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
    yield factory
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


@pytest.fixture
def raw_client(db_factory):
    """초기 설정이 끝나지 않은 상태의 클라이언트."""
    return TestClient(app)


@pytest.fixture
def client(db_factory, raw_client):
    db = db_factory()
    SettingsStore(db).mark_bootstrap_completed("test")
    db.commit()
    db.close()
    return raw_client


@pytest.fixture
def login_as(monkeypatch):
    """역할을 받아 가짜 사용자로 로그인. 사용자 조회 호출 횟수를 담은 dict 반환."""
    calls = {"count": 0}

    def _login(*roles: str) -> dict:
        def _fake_current_user(request, db):
            calls["count"] += 1
            return User(
                sub=f"sub-{'-'.join(roles)}",
                email="staff@example.com",
                name="직원",
                display_name="직원",
                roles=json.dumps(list(roles)),
                created_at=_now_iso(),
                last_login_at=_now_iso(),
            )

        monkeypatch.setattr(deps, "get_current_user", _fake_current_user)
        return calls

    return _login


def _add_audit(db_factory, action: str, target: str | None = None) -> None:
    db = db_factory()
    db.add(AuditLog(actor_sub=None, action=action, target=target, created_at=_now_iso()))
    db.commit()
    db.close()


def _numbers_write_routes() -> list[tuple[str, str]]:
    # FastAPI 0.137+ 는 include_router 한 라우터를 복사하지 않고 트리로 보관해 app.routes 에
    # 하위 라우트가 펼쳐지지 않는다. 그래서 0.137.2 에 추가된 iter_route_contexts 로 순회한다.
    # 0.137.0~0.137.1 은 두 방식 모두 빈 목록이 되지만 아래 수집 테스트가 실패로 드러낸다.
    try:
        from fastapi.routing import iter_route_contexts
    except ImportError:  # 0.136 이하 — app.routes 가 이미 평탄한 라우트 목록
        candidates = app.routes
    else:
        candidates = iter_route_contexts(app.routes)

    routes = set()
    for route in candidates:
        path = getattr(route, "path", None) or ""
        if not path.startswith("/numbers"):
            continue
        for method in (getattr(route, "methods", None) or set()) & _WRITE_METHODS:
            routes.add((method, path.replace("{nid}", "1")))
    return sorted(routes)


# ── 발신번호 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("roles", [("viewer",), ("sender",), ("admin",)])
def test_numbers_list_is_readable_by_any_role(client, login_as, roles):
    login_as(*roles)
    assert client.get("/numbers").status_code == 200


def test_numbers_write_routes_are_collected():
    # 아래 파라미터 테스트가 빈 목록으로 조용히 통과하지 않도록.
    assert len(_numbers_write_routes()) >= 4


@pytest.mark.parametrize("roles", [("viewer",), ("sender",)])
@pytest.mark.parametrize(("method", "path"), _numbers_write_routes())
def test_numbers_write_routes_require_admin(client, login_as, method, path, roles):
    login_as(*roles)
    res = client.request(method, path, json={})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize(("method", "path"), _numbers_write_routes())
def test_numbers_write_routes_admit_admin(client, login_as, method, path):
    login_as("admin")
    assert client.request(method, path, json={}).status_code != 403


def test_numbers_list_can_skip_usage_aggregate(client, login_as, monkeypatch):
    import app.routes.numbers as numbers

    def _fail(db):
        raise AssertionError("include_usage=false 인데 사용량 집계가 실행됨")

    monkeypatch.setattr(numbers, "_daily_usage_map", _fail)
    login_as("sender")
    res = client.get("/numbers", params={"status": "approved", "include_usage": "false"})
    assert res.status_code == 200


def test_role_gate_resolves_user_once_per_request(client, login_as):
    calls = login_as("viewer")
    assert client.post("/numbers/1/toggle").status_code == 403
    assert calls["count"] == 1


# ── 발송 ────────────────────────────────────────────────────────────────────

_SEND_PATHS = ["/campaigns", "/threads/0212345678:01012345678/messages"]


@pytest.mark.parametrize("path", _SEND_PATHS)
def test_send_routes_reject_viewer(client, login_as, path):
    login_as("viewer")
    res = client.post(path, json={})
    assert res.status_code == 403
    assert res.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize("roles", [("sender",), ("admin",)])
@pytest.mark.parametrize("path", _SEND_PATHS)
def test_send_routes_admit_sender_and_admin(client, login_as, path, roles):
    login_as(*roles)
    # 권한 게이트를 통과하면 빈 body 검증에서 422 로 끝난다.
    assert client.post(path, json={}).status_code == 422


# ── 검색·알림의 admin 전용 데이터 ────────────────────────────────────────────


def test_search_returns_audit_logs_only_to_admin(client, login_as, db_factory):
    _add_audit(db_factory, "LOGIN", target="probe-target")

    login_as("viewer")
    viewer = client.get("/search", params={"q": "probe-target"}).json()["data"]
    assert viewer["auditLogs"] == []
    assert viewer["counts"]["auditLogs"] == 0

    login_as("admin")
    admin = client.get("/search", params={"q": "probe-target"}).json()["data"]
    assert admin["counts"]["auditLogs"] == 1


def test_settings_notification_links_only_for_admin(client, login_as, db_factory):
    _add_audit(db_factory, "SETTINGS_UPDATE")

    def _settings_item() -> dict:
        items = client.get("/notifications").json()["data"]
        return next(n for n in items if n["title"] == "설정 변경")

    login_as("viewer")
    assert "href" not in _settings_item()

    login_as("admin")
    assert _settings_item()["href"] == "/settings"


# ── 303 응답의 원인 코드 ─────────────────────────────────────────────────────


def test_missing_session_returns_auth_required(client):
    res = client.get("/dashboard", follow_redirects=False)
    assert res.status_code == 303
    assert "location" not in res.headers
    assert res.json()["error"]["code"] == "auth_required"


def test_incomplete_setup_returns_setup_required(raw_client, login_as):
    login_as("admin")
    res = raw_client.get("/dashboard", follow_redirects=False)
    assert res.status_code == 303
    assert res.json()["error"]["code"] == "setup_required"
