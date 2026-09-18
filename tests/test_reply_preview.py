"""EUC-KR 답장 사전 검증은 실제 전송 정책을 사용하며 외부 요청을 하지 않는다."""
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from app.auth.deps import require_setup_complete, require_user
from app.routes.threads import router
from app.services.chat import validate_reply_content


@pytest.fixture
def preview_app(sample_user, monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_user] = lambda: sample_user
    app.dependency_overrides[require_setup_complete] = lambda: None

    def forbidden_provider(*args, **kwargs):
        pytest.fail("답장 사전 검증이 공급자/발송 경로를 호출했습니다")

    monkeypatch.setattr("app.main.get_msghub_client", forbidden_provider)
    monkeypatch.setattr("app.services.chat.send_reply", forbidden_provider)
    monkeypatch.setattr("app.services.chat.dispatch_campaign", forbidden_provider)
    monkeypatch.setattr("app.services.chat.dispatch_chat_reply", forbidden_provider)
    return app


@pytest.mark.parametrize(
    ("text", "byte_length", "valid"),
    [
        ("가" * 45, 90, True),
        ("가" * 46, 92, False),
        ("A" * 90, 90, True),
        ("A" * 91, 91, False),
        ("  \n안내  \t", 4, True),
        ("", 0, False),
        (" \n\t ", 0, False),
        ("가" * 1001, 2002, False),
        ("뷁" * 11, 88, True),  # EUC-KR 조합형 확장 음절은 한 글자에 8바이트.
        ("뷁" * 12, 96, False),
    ],
    ids=[
        "korean-45", "korean-46", "ascii-90", "ascii-91", "trimmed", "empty", "spaces",
        "over-lms", "extended-hangul-88", "extended-hangul-96",
    ],
)
async def test_preview_uses_trimmed_server_policy(preview_app, text, byte_length, valid):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=preview_app), base_url="http://test.local",
    ) as client:
        response = await client.post("/threads/validate-reply", json={"text": text})
    assert response.status_code == 200
    stripped = text.strip()
    result = validate_reply_content(stripped)
    assert response.json() == {"data": {
        "byteLength": byte_length, "maxBytes": 90, "valid": valid,
        "error": result.get("error") if stripped else None,
    }}


async def test_preview_unsupported_characters_have_no_fake_byte_count(preview_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=preview_app), base_url="http://test.local",
    ) as client:
        response = await client.post("/threads/validate-reply", json={"text": "안내🙂"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["byteLength"] is None
    assert data["maxBytes"] == 90
    assert data["valid"] is False
    assert "EUC-KR" in data["error"]
    assert "미지원" in data["error"]


async def test_preview_caps_input_with_consistent_envelope(preview_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=preview_app), base_url="http://test.local",
    ) as client:
        response = await client.post("/threads/validate-reply", json={"text": "A" * 4001})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["byteLength"] is None
    assert data["maxBytes"] == 90
    assert data["valid"] is False
    assert "4000" in data["error"]


@pytest.mark.parametrize("dependency", [require_user, require_setup_complete])
async def test_preview_keeps_router_access_gates(preview_app, dependency):
    def deny():
        raise HTTPException(status_code=403, detail="접근 불가")

    preview_app.dependency_overrides[dependency] = deny
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=preview_app), base_url="http://test.local",
    ) as client:
        response = await client.post("/threads/validate-reply", json={"text": "안내"})
    assert response.status_code == 403


async def test_preview_requires_csrf(preview_app, monkeypatch):
    monkeypatch.delenv("SMS_DISABLE_CSRF", raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=preview_app), base_url="http://test.local",
    ) as client:
        response = await client.post("/threads/validate-reply", json={"text": "안내"})
    assert response.status_code == 403
