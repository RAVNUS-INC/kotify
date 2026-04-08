"""CSRF 보호 테스트 — POST without/with token."""
from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from app.security.csrf import get_csrf_token, verify_csrf


@pytest.fixture(autouse=True)
def disable_csrf_bypass(monkeypatch):
    """이 모듈에서는 SMS_DISABLE_CSRF를 unset하여 실제 CSRF 검증을 활성화한다."""
    monkeypatch.delenv("SMS_DISABLE_CSRF", raising=False)
    yield


def _make_app() -> FastAPI:
    """CSRF 검증 테스트용 미니 FastAPI 앱."""
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="test-secret-key-for-csrf-tests")

    @app.get("/token")
    async def get_token(request: Request):
        """세션에 CSRF 토큰을 생성하고 반환한다."""
        token = get_csrf_token(request)
        return JSONResponse({"csrf_token": token})

    @app.post("/protected")
    async def protected(request: Request):
        """CSRF 토큰 검증 후 처리한다."""
        await verify_csrf(request)
        return JSONResponse({"ok": True})

    return app


class TestCSRF:
    def setup_method(self):
        self.app = _make_app()
        self.client = TestClient(self.app, raise_server_exceptions=False)

    def test_get_csrf_token_creates_token(self):
        """GET /token 은 CSRF 토큰을 반환한다."""
        resp = self.client.get("/token")
        assert resp.status_code == 200
        data = resp.json()
        assert "csrf_token" in data
        assert len(data["csrf_token"]) > 10

    def test_post_without_token_returns_403(self):
        """CSRF 토큰 없이 POST하면 403."""
        resp = self.client.post("/protected")
        assert resp.status_code == 403

    def test_post_with_valid_form_token_returns_200(self):
        """올바른 form csrf_token으로 POST하면 200."""
        with self.client as c:
            # 먼저 토큰 획득 (세션 생성)
            resp = c.get("/token")
            assert resp.status_code == 200
            token = resp.json()["csrf_token"]

            # 토큰을 form 데이터로 전송
            resp = c.post(
                "/protected",
                data={"csrf_token": token},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert resp.status_code == 200

    def test_post_with_valid_header_token_returns_200(self):
        """올바른 X-CSRF-Token 헤더로 POST하면 200."""
        with self.client as c:
            resp = c.get("/token")
            token = resp.json()["csrf_token"]

            resp = c.post(
                "/protected",
                headers={"X-CSRF-Token": token},
            )
            assert resp.status_code == 200

    def test_post_with_wrong_token_returns_403(self):
        """잘못된 토큰으로 POST하면 403."""
        with self.client as c:
            c.get("/token")  # 세션 생성

            resp = c.post(
                "/protected",
                data={"csrf_token": "wrong-token-value"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert resp.status_code == 403

    def test_token_is_consistent_across_requests(self):
        """같은 세션에서 토큰은 동일해야 한다."""
        with self.client as c:
            resp1 = c.get("/token")
            resp2 = c.get("/token")
            assert resp1.json()["csrf_token"] == resp2.json()["csrf_token"]
