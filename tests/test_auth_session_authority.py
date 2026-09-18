"""이전 로그인 세션은 최신 DB 권한·프로필을 덮거나 삭제된 사용자를 복원하지 않는다."""
from __future__ import annotations

import json

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import func, select
from starlette.requests import Request

from app.auth.deps import (
    get_current_user,
    parse_user_roles,
    require_role,
    require_sender,
    require_user,
    user_has_role,
)
from app.db import get_db
from app.models import User
from app.routes import auth


def _session(sub: str, roles: list[str]) -> dict:
    return {
        "user_sub": sub,
        "user_roles": roles,
        "user_email": "old-profile@example.invalid",
        "user_name": "이전 이름",
        "user_display": "이전 표시명",
    }


def _request(session: dict) -> Request:
    return Request({
        "type": "http", "method": "GET", "path": "/auth/me",
        "headers": [], "session": session,
    })


@pytest.mark.parametrize("old_roles", [["admin", "sender"], ["owner"]])
def test_stale_privileged_session_obeys_latest_viewer_role(
    db_session, sample_user, old_roles,
):
    sample_user.roles = json.dumps(["viewer"])
    db_session.commit()

    user = require_user(_request(_session(sample_user.sub, old_roles)), db_session)

    for check in (require_role("admin"), require_sender):
        with pytest.raises(HTTPException) as denied:
            check(user)
        assert denied.value.status_code == 403
    db_session.refresh(sample_user)
    assert parse_user_roles(sample_user) == ["viewer"]


@pytest.mark.parametrize("current_role", ["sender", "admin"])
def test_old_viewer_session_uses_newly_granted_db_role(db_session, sample_user, current_role):
    sample_user.roles = json.dumps([current_role])
    db_session.commit()

    user = require_user(_request(_session(sample_user.sub, ["viewer"])), db_session)

    assert require_sender(user) is user
    assert require_role(current_role)(user) is user
    assert parse_user_roles(user) == [current_role]


def test_session_lookup_preserves_latest_profile_and_actual_login_time(db_session, sample_user):
    sample_user.email = "current-profile@example.invalid"
    sample_user.name = "최신 이름"
    sample_user.display_name = "최신 표시명"
    sample_user.last_login_at = "2026-09-18T01:00:00+00:00"
    db_session.commit()
    expected = (
        sample_user.email, sample_user.name, sample_user.display_name,
        sample_user.roles, sample_user.created_at, sample_user.last_login_at,
    )

    get_current_user(_request(_session(sample_user.sub, ["admin", "sender"])), db_session)

    db_session.refresh(sample_user)
    assert (
        sample_user.email, sample_user.name, sample_user.display_name,
        sample_user.roles, sample_user.created_at, sample_user.last_login_at,
    ) == expected


def test_deleted_user_cannot_be_recreated_by_existing_session(db_session, sample_user):
    request = _request(_session(sample_user.sub, ["admin"]))
    db_session.delete(sample_user)
    db_session.commit()

    assert get_current_user(request, db_session) is None
    with pytest.raises(HTTPException) as missing:
        require_user(request, db_session)
    assert missing.value.status_code == 303
    assert db_session.scalar(select(func.count()).select_from(User)) == 0


@pytest.mark.parametrize("stored_roles", [
    "null", '"admin"', '{"admin": true}', "42", "true", "not-json",
    '["admin", null]', '["admin", {}]', '["admin", ["sender"]]', '["admin", 42]',
])
def test_malformed_db_role_values_fail_closed(sample_user, stored_roles):
    sample_user.roles = stored_roles

    assert parse_user_roles(sample_user) == []
    assert user_has_role(sample_user, "admin", "sender", "owner") is False


@pytest.fixture
def auth_me_client(db_session):
    """실제 /auth/me 의존성과 응답을 ASGI로 검증하고 외부 로그인·네트워크는 사용하지 않는다."""
    api = FastAPI()
    api.include_router(auth.router)
    session: dict = {}

    def override_db():
        yield db_session

    api.dependency_overrides[get_db] = override_db

    @api.middleware("http")
    async def inject_session(request, call_next):
        request.scope["session"] = session
        return await call_next(request)

    return api, session


@pytest.mark.parametrize(("current_roles", "old_roles"), [
    (["viewer"], ["admin"]),
    (["sender"], ["viewer"]),
    (["admin"], ["viewer"]),
])
async def test_auth_me_returns_latest_db_roles_and_profile(
    db_session, sample_user, auth_me_client, current_roles, old_roles,
):
    sample_user.roles = json.dumps(current_roles)
    sample_user.email = "current-profile@example.invalid"
    sample_user.name = "최신 이름"
    sample_user.display_name = "최신 표시명"
    db_session.commit()
    expected = {
        "sub": sample_user.sub, "email": sample_user.email, "name": sample_user.name,
        "display": sample_user.display_name, "roles": current_roles,
    }
    api, session = auth_me_client
    session.update(_session(sample_user.sub, old_roles))

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://test.local",
    ) as client:
        response = await client.get("/auth/me")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user"] == expected
    assert data["csrfToken"] == session["csrf_token"]
    assert data["csrfToken"]


async def test_auth_me_rejects_deleted_user_with_existing_session(
    db_session, sample_user, auth_me_client,
):
    api, session = auth_me_client
    session.update(_session(sample_user.sub, ["admin"]))
    db_session.delete(sample_user)
    db_session.commit()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api), base_url="http://test.local",
    ) as client:
        response = await client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"
    assert db_session.scalar(select(func.count()).select_from(User)) == 0
