"""수신자 1,000명 제한 테스트."""
from __future__ import annotations

import pytest

from app.services.compose import (
    MAX_RECIPIENTS_PER_CAMPAIGN,
    dedupe_recipients,
    dispatch_campaign,
)


def _make_numbers(n: int) -> list[str]:
    """n개의 더미 전화번호를 생성한다."""
    return [f"010{str(i).zfill(8)}" for i in range(n)]


@pytest.mark.asyncio
async def test_dispatch_campaign_raises_on_too_many_recipients(monkeypatch):
    """1,001명 수신자로 dispatch_campaign 호출 시 ValueError 발생."""
    recipients = _make_numbers(MAX_RECIPIENTS_PER_CAMPAIGN + 1)

    with pytest.raises(ValueError, match=str(MAX_RECIPIENTS_PER_CAMPAIGN)):
        await dispatch_campaign(
            db=None,  # type: ignore[arg-type]
            msghub_client=None,  # type: ignore[arg-type]
            created_by="test-sub",
            caller_number="0212345678",
            content="테스트",
            recipients=recipients,
            message_type="SMS",
        )


def test_max_recipients_constant():
    """MAX_RECIPIENTS_PER_CAMPAIGN이 1000임을 확인."""
    assert MAX_RECIPIENTS_PER_CAMPAIGN == 1000


def test_exactly_at_limit_does_not_raise_immediately():
    """정확히 1,000명은 제한 초과 오류를 즉시 내지 않아야 한다.

    (발신번호 검증에서 걸릴 수 있으므로 ValueError가 발생해도
    메시지에 'MAX_RECIPIENTS_PER_CAMPAIGN'이 포함되어선 안 됨)
    """
    # 1000명은 MAX 이하이므로 제한 초과 ValueError는 나지 않아야 한다.
    # 실제 DB/NCP가 없으므로 AttributeError 등 다른 예외가 발생할 수 있다.
    import asyncio

    async def _run():
        recipients = _make_numbers(MAX_RECIPIENTS_PER_CAMPAIGN)
        try:
            await dispatch_campaign(
                db=None,  # type: ignore[arg-type]
                msghub_client=None,  # type: ignore[arg-type]
                created_by="test-sub",
                caller_number="0212345678",
                content="테스트",
                recipients=recipients,
                message_type="SMS",
            )
        except ValueError as exc:
            # 1,000명 초과 메시지가 아니어야 함
            assert str(MAX_RECIPIENTS_PER_CAMPAIGN) not in str(exc) or "최대" not in str(exc)
        except Exception:
            pass  # DB 없으면 다른 예외 — 정상

    asyncio.run(_run())


# ── C2: 수신자 중복 제거 회귀 테스트 ──────────────────────────────────────────


def test_dedupe_recipients_preserves_order_removes_dups():
    """중복 번호는 첫 등장 순서로 1건만 남는다 (C2 중복발송 방지)."""
    result = dedupe_recipients(
        ["01011112222", "01033334444", "01011112222", "01055556666", "01033334444"]
    )
    assert result == ["01011112222", "01033334444", "01055556666"]


def test_dedupe_recipients_empty():
    """빈 목록은 빈 목록을 반환한다."""
    assert dedupe_recipients([]) == []


def test_dedupe_recipients_no_duplicates_keeps_order():
    """중복이 없으면 원본 순서를 그대로 유지한다."""
    nums = _make_numbers(5)
    assert dedupe_recipients(nums) == nums


@pytest.mark.asyncio
async def test_dispatch_dedupes_before_limit_check():
    """중복 포함 1,002개(고유 1,000개)는 한도 초과로 막히지 않아야 한다.

    dedup 이 한도 판정 전에 수행되므로 고유 1,000개면 한도를 통과하고,
    이후 단계(발신번호 검증 등, db=None)에서 다른 예외가 발생한다.
    """
    uniq = _make_numbers(MAX_RECIPIENTS_PER_CAMPAIGN)
    recipients = uniq + [uniq[0], uniq[1]]  # 1,002개, 고유 1,000개

    try:
        await dispatch_campaign(
            db=None,  # type: ignore[arg-type]
            msghub_client=None,  # type: ignore[arg-type]
            created_by="test-sub",
            caller_number="0212345678",
            content="테스트",
            recipients=recipients,
            message_type="SMS",
        )
    except ValueError as exc:
        assert str(MAX_RECIPIENTS_PER_CAMPAIGN) not in str(exc)
    except Exception:
        pass  # db=None → 다른 예외 정상


@pytest.mark.asyncio
async def test_dispatch_dedup_still_enforces_limit():
    """중복 제거 후에도 1,001개(고유)면 한도 초과 ValueError 가 발생한다."""
    recipients = _make_numbers(MAX_RECIPIENTS_PER_CAMPAIGN + 1)  # 1,001 고유
    with pytest.raises(ValueError, match=str(MAX_RECIPIENTS_PER_CAMPAIGN)):
        await dispatch_campaign(
            db=None,  # type: ignore[arg-type]
            msghub_client=None,  # type: ignore[arg-type]
            created_by="test-sub",
            caller_number="0212345678",
            content="테스트",
            recipients=recipients,
            message_type="SMS",
        )
