"""CSRF 통합 테스트 — SMS_DISABLE_CSRF 미설정 상태에서 실제 검증 확인.

이 테스트는 conftest.py의 SMS_DISABLE_CSRF=1 우회를 unset한 상태에서 실행된다.
실제 프로덕션 CSRF 검증 동작을 보장한다.
"""
from __future__ import annotations

import os

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from starlette.testclient import TestClient

from app.security.csrf import get_csrf_token, verify_csrf


def _make_csrf_app() -> FastAPI:
    """CSRF 통합 테스트용 독립 FastAPI 앱."""
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="integration-test-secret-key")

    @app.get("/token")
    async def get_token(request: Request):
        token = get_csrf_token(request)
        return JSONResponse({"csrf_token": token})

    @app.post("/protected")
    async def protected(request: Request):
        await verify_csrf(request)
        return JSONResponse({"ok": True})

    return app


@pytest.fixture(autouse=True)
def disable_csrf_bypass(monkeypatch):
    """이 모듈에서는 SMS_DISABLE_CSRF를 unset하여 실제 CSRF 검증을 활성화한다."""
    monkeypatch.delenv("SMS_DISABLE_CSRF", raising=False)
    yield


@pytest.fixture
def csrf_app():
    return _make_csrf_app()


@pytest.fixture
def client(csrf_app):
    return TestClient(csrf_app, raise_server_exceptions=False)


class TestCSRFIntegration:
    """실제 CSRF 검증 동작 통합 테스트."""

    def test_post_without_token_returns_403(self, client):
        """CSRF 토큰 없이 POST → 403."""
        resp = client.post("/protected")
        assert resp.status_code == 403

    def test_post_with_valid_form_token_returns_200(self, client):
        """세션에서 받은 토큰을 form 필드로 전송 → 200."""
        with client as c:
            resp = c.get("/token")
            assert resp.status_code == 200
            token = resp.json()["csrf_token"]

            resp = c.post(
                "/protected",
                data={"csrf_token": token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert resp.status_code == 200

    def test_post_with_invalid_token_returns_403(self, client):
        """잘못된 토큰으로 POST → 403."""
        with client as c:
            c.get("/token")  # 세션 생성

            resp = c.post(
                "/protected",
                data={"csrf_token": "invalid-token-value"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert resp.status_code == 403

    def test_htmx_post_with_valid_header_returns_200(self, client):
        """HTMX X-CSRF-Token 헤더로 POST → 200."""
        with client as c:
            resp = c.get("/token")
            token = resp.json()["csrf_token"]

            resp = c.post(
                "/protected",
                headers={"X-CSRF-Token": token},
            )
            assert resp.status_code == 200

    def test_htmx_post_with_wrong_header_returns_403(self, client):
        """잘못된 X-CSRF-Token 헤더로 POST → 403."""
        with client as c:
            c.get("/token")  # 세션 생성

            resp = c.post(
                "/protected",
                headers={"X-CSRF-Token": "wrong-header-token"},
            )
            assert resp.status_code == 403

    def test_post_without_session_returns_403(self, csrf_app):
        """세션 없는 앱에서 POST → 403."""
        # 세션 미들웨어 없는 앱
        bare_app = FastAPI()

        @bare_app.post("/protected")
        async def protected(request: Request):
            await verify_csrf(request)
            return JSONResponse({"ok": True})

        bare_client = TestClient(bare_app, raise_server_exceptions=False)
        resp = bare_client.post("/protected")
        assert resp.status_code == 403
