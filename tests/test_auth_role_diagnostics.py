"""역할 진단은 로그인 권한을 바꾸지 않고 원인 구분에 필요한 정보만 남긴다."""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from starlette.requests import Request

from app.auth.deps import get_current_user
from app.auth.oidc import diagnose_role_claims
from app.models import AuditLog
from app.routes import auth
from app.security.settings_store import SettingsStore


def _request(session=None):
    return Request({
        "type": "http", "method": "GET", "path": "/auth/callback",
        "headers": [], "session": session if session is not None else {},
    })


@pytest.fixture
def login_callback(monkeypatch, db_session):
    store = SettingsStore(db_session)
    store.set("keycloak.client_id", "test-client", is_secret=False, updated_by=None)

    async def run(claims=None, *, token=None, userinfo=None, settings=None):
        for key, value in (settings or {}).items():
            store.set(key, value, is_secret=False, updated_by=None)
        if token is None:
            token = {"userinfo": claims, "id_token": "secret-raw-id-token"}
        keycloak = SimpleNamespace(
            authorize_access_token=AsyncMock(return_value=token),
            userinfo=AsyncMock(return_value=userinfo),
        )
        oauth = SimpleNamespace(create_client=lambda _: keycloak)
        monkeypatch.setattr(auth, "get_oauth_client", lambda _: oauth)
        request = _request()
        response = await auth.callback(request, db_session)
        entries = db_session.scalars(select(AuditLog).order_by(AuditLog.id)).all()
        detail = json.loads(entries[-1].detail) if entries else None
        return response, request.session, detail, keycloak

    return run


def _claims(**extra):
    return {
        "sub": "profile-sub-sentinel", "email": "staff@example.invalid",
        "name": "profile-name-sentinel", "azp": "test-client", **extra,
    }


@pytest.mark.parametrize("role_source", ["realm_access", "resource_access"])
async def test_sender_claims_remain_sender_and_have_safe_source(login_callback, role_source):
    access = {"roles": ["sender", "offline_access"]}
    claims = _claims(**{role_source: access if role_source == "realm_access" else {
        "test-client": access,
    }})
    response, session, detail, keycloak = await login_callback(claims)
    assert response.headers["location"] == "/"
    assert session["user_roles"] == ["sender"]
    assert session["role_diagnostics_v1"] is True
    diag = detail["role_diagnostics"]
    assert diag["claims_source"] == "authlib_verified_id_token"
    assert diag["configured_client_matches_azp"] is True
    assert diag["parsed_roles"] == diag["final_roles"] == ["sender"]
    assert diag["viewer_fallback_used"] is False
    observed = diag["realm_access"] if role_source == "realm_access" else diag["azp_client"]
    assert observed["roles_present"] is True
    assert observed["roles"] == {
        "type": "array", "known_roles": ["sender"], "unknown_role_count": 1,
    }
    keycloak.userinfo.assert_not_awaited()


async def test_missing_roles_defaults_to_viewer_with_fallback_diagnostic(login_callback):
    response, session, detail, _ = await login_callback(_claims())
    diag = detail["role_diagnostics"]
    assert response.headers["location"] == "/"
    assert session["user_roles"] == ["viewer"]
    assert diag["viewer_fallback_used"] is True
    assert diag["realm_access"]["present"] is False
    assert diag["realm_access"]["roles_present"] is False
    assert diag["resource_access_present"] is False
    assert diag["azp_client"]["present"] is False
    assert diag["parsed_roles"] == diag["final_roles"] == ["viewer"]


async def test_explicit_viewer_is_distinguished_from_default_viewer(login_callback):
    _, session, detail, _ = await login_callback(_claims(realm_access={"roles": ["viewer"]}))
    assert session["user_roles"] == ["viewer"]
    assert detail["role_diagnostics"]["viewer_fallback_used"] is False


async def test_wrong_client_sender_is_diagnosed_without_granting_role(login_callback):
    _, session, detail, _ = await login_callback(_claims(resource_access={
        "different-client-sentinel": {"roles": ["sender", "custom-role-sentinel"]},
    }))
    diag = detail["role_diagnostics"]
    assert session["user_roles"] == ["viewer"]
    assert diag["viewer_fallback_used"] is True
    assert diag["configured_client"]["present"] is False
    assert diag["other_client_count"] == 1
    assert diag["other_client_known_roles"] == ["sender"]
    assert "sentinel" not in json.dumps(diag)


@pytest.mark.parametrize("azp", [None, "different-client-sentinel"])
async def test_configured_client_sender_with_missing_or_different_azp(login_callback, azp):
    claims = _claims(resource_access={"test-client": {"roles": ["sender"]}})
    if azp is None:
        claims.pop("azp")
    else:
        claims["azp"] = azp
    _, session, detail, _ = await login_callback(claims)
    diag = detail["role_diagnostics"]
    assert session["user_roles"] == ["viewer"]
    assert diag["configured_client"]["roles"]["known_roles"] == ["sender"]
    assert diag["azp_present"] is (azp is not None)
    assert diag["configured_client_matches_azp"] is False
    assert diag["azp_client"]["present"] is False
    assert diag["viewer_fallback_used"] is True


@pytest.mark.parametrize(("settings", "policy"), [
    ({"setup.first_admin_email": "staff@example.invalid"}, "email_anchor"),
    ({"setup.pending_first_admin": "true"}, "pending_first_login"),
])
async def test_first_admin_policy_distinguishes_parsed_and_final_roles(
    login_callback, settings, policy,
):
    _, session, detail, _ = await login_callback(_claims(), settings=settings)
    diag = detail["role_diagnostics"]
    assert diag["first_admin_policy"] == policy
    assert diag["parsed_roles"] == ["viewer"]
    assert diag["final_roles"] == session["user_roles"] == ["admin", "viewer"]


async def test_userinfo_endpoint_is_labeled_separately(login_callback):
    _, session, detail, keycloak = await login_callback(
        token={"access_token": "secret-access-token"},
        userinfo=_claims(realm_access={"roles": ["sender"]}),
    )
    assert session["user_roles"] == ["sender"]
    assert detail["role_diagnostics"]["claims_source"] == "userinfo_endpoint"
    keycloak.userinfo.assert_awaited_once()


@pytest.mark.parametrize("token", [
    {"id_token": "raw.jwt.sentinel"},
    {"userinfo": "unverified.jwt.sentinel", "id_token": "raw.jwt.sentinel"},
    {"id_token": {"sub": "unverified-profile", "realm_access": {"roles": ["admin"]}}},
])
async def test_raw_or_nonmapping_claims_are_rejected(login_callback, token):
    response, session, detail, keycloak = await login_callback(token=token)
    assert response.headers["location"] == "/auth/login?error=invalid_claims"
    assert session == {}
    assert detail is None
    keycloak.userinfo.assert_not_awaited()


async def test_diagnostic_never_contains_token_profile_client_or_arbitrary_role(login_callback):
    malicious = "custom-role-sentinel\nforged-log=true"
    claims = _claims(
        iss="https://issuer-sentinel.invalid", realm_access={"roles": ["sender", malicious]},
        resource_access={"test-client": {"roles": ["custom-client-role-sentinel"]}},
    )
    _, _, detail, _ = await login_callback(claims)
    serialized = json.dumps(detail["role_diagnostics"])
    for private in [
        "sentinel", "test-client", "staff@example.invalid", "secret-raw-id-token",
        "forged-log", "https://",
    ]:
        assert private not in serialized
    assert detail["role_diagnostics"]["realm_access"]["roles"]["unknown_role_count"] == 1


@pytest.mark.parametrize(("value", "expected_type"), [
    (None, "null"), ("private-string-sentinel", "string"),
    (42, "number"), (True, "boolean"), ({"private": "value"}, "object"),
])
def test_claim_shapes_are_recorded_without_values(value, expected_type):
    diag = diagnose_role_claims({"realm_access": {"roles": value}}, "test-client")
    assert diag["realm_access"]["roles_present"] is True
    assert diag["realm_access"]["roles"]["type"] == expected_type
    assert diag["realm_access"]["roles"]["known_roles"] == []
    assert "sentinel" not in json.dumps(diag)


@pytest.mark.parametrize("diagnostic_session", [False, True])
def test_old_viewer_session_keeps_latest_db_roles_without_leaking_diagnostics(
    db_session, sample_user, caplog, diagnostic_session,
):
    sample_user.roles = json.dumps(["sender", "private-db-role-sentinel"])
    db_session.commit()
    session = {
        "user_sub": sample_user.sub, "user_email": "private-email@example.invalid",
        "user_name": "private-name-sentinel", "user_roles": ["viewer"],
        "id_token": "private-token-sentinel",
    }
    if diagnostic_session:
        session["role_diagnostics_v1"] = True
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        user = get_current_user(_request(session), db_session)
        get_current_user(_request(session), db_session)
    assert json.loads(user.roles) == ["sender", "private-db-role-sentinel"]
    messages = [r.message for r in caplog.records if "auth_session_role_mismatch" in r.message]
    # 세션은 과거 로그인 스냅샷일 수 있다. 경고를 유지해도 요청마다 반복하거나 식별자를 남기지 않는다.
    assert len(messages) <= 1
    for message in messages:
        diag = json.loads(message.split(" ", 1)[1])
        assert diag["db_roles"]["known_roles"] == ["sender"]
        assert diag["db_roles"]["unknown_role_count"] == 1
        assert diag["session_roles"]["known_roles"] == ["viewer"]
        assert diag["session_has_role_diagnostics"] is diagnostic_session
        for private in [sample_user.sub, "sentinel", "@example.invalid"]:
            assert private not in message


def test_equal_roles_in_different_order_do_not_warn(db_session, sample_user, caplog):
    request = _request({"user_sub": sample_user.sub, "user_roles": ["admin", "sender"]})
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        get_current_user(request, db_session)
    assert not [r for r in caplog.records if "auth_session_role_mismatch" in r.message]


@pytest.mark.parametrize(("db_roles", "session_roles"), [
    ({"private-db-sentinel": "admin"}, ["viewer"]),
    (["sender"], [{"private-session-sentinel": "admin"}, "viewer"]),
])
def test_malformed_role_values_do_not_break_or_leak_in_mismatch_diagnostics(
    db_session, sample_user, caplog, db_roles, session_roles,
):
    sample_user.roles = json.dumps(db_roles)
    db_session.commit()
    request = _request({"user_sub": sample_user.sub, "user_roles": session_roles})
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        user = get_current_user(request, db_session)
    assert json.loads(user.roles) == db_roles
    messages = [r.message for r in caplog.records if "auth_session_role_mismatch" in r.message]
    assert len(messages) <= 1
    assert all("sentinel" not in message for message in messages)
