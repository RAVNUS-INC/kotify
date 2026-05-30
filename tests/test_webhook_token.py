"""웹훅 토큰 인증 + setup 자동생성 테스트 (P1-C).

- _verify_token: 저장된 토큰과 일치 시 통과, 불일치/미설정(운영) 거부.
- complete_setup: webhook_token 을 자동 생성·저장하는지 검증
  (미설정 시 운영 직후 모든 msghub 웹훅이 401 로 차단되는 문제 예방).
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import respx
from httpx import Response

from app.config import settings
from app.routes.setup import CompleteSetupBody, complete_setup
from app.routes.webhook import _verify_token
from app.security.settings_store import SettingsStore

# ── _verify_token ────────────────────────────────────────────────────────────


def test_verify_token_accepts_match(db_session):
    store = SettingsStore(db_session)
    store.set("msghub.webhook_token", "tok-abc-123", is_secret=True, updated_by="test")
    db_session.commit()
    assert _verify_token("tok-abc-123", db_session) is True


def test_verify_token_rejects_mismatch(db_session):
    store = SettingsStore(db_session)
    store.set("msghub.webhook_token", "tok-abc-123", is_secret=True, updated_by="test")
    db_session.commit()
    assert _verify_token("nope", db_session) is False


def test_verify_token_missing_rejects_in_prod(db_session, monkeypatch):
    """운영 모드(dev_mode=False)에서 토큰 미설정이면 거부 — 이 버그의 핵심 조건."""
    monkeypatch.setattr(settings, "dev_mode", False)
    assert _verify_token("anything", db_session) is False


def test_verify_token_missing_allows_in_dev(db_session, monkeypatch):
    monkeypatch.setattr(settings, "dev_mode", True)
    assert _verify_token("anything", db_session) is True


# ── complete_setup webhook_token 자동생성 (end-to-end) ───────────────────────


@respx.mock
def test_complete_setup_generates_webhook_token(db_session, monkeypatch):
    """setup 완료 시 msghub.webhook_token 이 자동 생성·저장되고,
    그 토큰으로 _verify_token 이 통과하는지(저장↔검증 키 일치) end-to-end 검증."""
    monkeypatch.setattr(
        "app.routes.setup.setup_service.verify_setup_token", lambda *a, **k: True
    )
    monkeypatch.setattr(
        "app.routes.setup.setup_service.delete_setup_token", lambda *a, **k: None
    )
    monkeypatch.setattr("app.routes.setup._validate_keycloak_issuer", lambda v: None)
    respx.get(
        "https://kc.example.com/.well-known/openid-configuration"
    ).mock(return_value=Response(200, json={"issuer": "https://kc.example.com"}))

    body = CompleteSetupBody(
        token="setup-token",
        keycloakIssuer="https://kc.example.com",
        keycloakClientId="kotify",
        keycloakClientSecret="kc-secret",
        msghubApiKey="api-key",
        msghubApiPwd="api-pwd",
    )
    request = MagicMock()
    request.session = {}

    result = asyncio.run(complete_setup(body, request, db_session))
    assert result["data"]["completed"] is True

    store = SettingsStore(db_session)
    token = store.get("msghub.webhook_token")
    assert token is not None
    assert len(token) == 32  # _secrets.token_hex(16)

    # 저장된 토큰으로 인증이 실제로 통과해야 한다 (저장 ↔ 검증 키 일치).
    assert _verify_token(token, db_session) is True
