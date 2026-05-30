"""답장 길이 검증 배선 테스트 (H2).

validate_reply_content 가 90바이트 초과 답장을 차단하고, send_reply 가 이를
호출해 발송(dispatch_campaign) 전에 막는지 검증한다. 이전엔 검증이 미호출이라
긴 답장이 조용히 단방향 LMS 로 강등되어 고객이 답장할 수 없었다.
"""
from __future__ import annotations

import pytest

from app.services.chat import send_reply, validate_reply_content

# ── validate_reply_content 단위 ──────────────────────────────────────────────


def test_validate_accepts_short_reply():
    result = validate_reply_content("안녕하세요, 문의 감사합니다.")
    assert result["ok"] is True


def test_validate_rejects_over_90_bytes():
    result = validate_reply_content("가" * 50)  # 90바이트 초과 → LMS 강등 대상
    assert result["ok"] is False
    assert "90" in result["error"]


def test_message_body_rejects_empty():
    """빈 답장은 라우트 입력 모델(MessageCreateBody)이 차단한다.

    (validate_reply_content 의 책임은 '길이 초과'이지 '빈 값'이 아님 — 책임 분리)
    """
    from pydantic import ValidationError

    from app.routes.threads import MessageCreateBody

    with pytest.raises(ValidationError):
        MessageCreateBody(text="   ")


# ── send_reply 배선 (발송 전 차단) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_reply_blocks_long_before_dispatch(db_session, sample_user, monkeypatch):
    """90바이트 초과 답장은 dispatch_campaign 호출 전에 ValueError 로 차단된다."""
    dispatched: list[int] = []

    async def _fake_dispatch(**kwargs):
        dispatched.append(1)
        return None

    monkeypatch.setattr("app.services.chat.dispatch_campaign", _fake_dispatch)

    with pytest.raises(ValueError, match="90"):
        await send_reply(
            db=db_session,
            msghub_client=None,  # type: ignore[arg-type]
            user=sample_user,
            caller="0212345678",
            phone="01011112222",
            content="가" * 50,
        )

    assert dispatched == []  # 검증에서 막혀 발송이 시도되지 않음
