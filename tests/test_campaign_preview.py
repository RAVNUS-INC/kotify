"""발송 전 비용 미리보기는 실제 서버 발송 정책과 단가표를 사용한다."""

from __future__ import annotations

import pytest

from app.routes.campaigns import CampaignPreviewBody, preview_campaign


def _preview(message: str, recipients: list[str], channel: str = "rcs", attachment: bool = False):
    return preview_campaign(
        CampaignPreviewBody(
            message=message,
            recipients=recipients,
            sendChannel=channel,
            hasAttachment=attachment,
        )
    )["data"]


def test_preview_uses_euc_kr_boundary_and_rcs_range():
    result = _preview("가" * 45, ["01012345678"])

    assert result == {
        "byteLength": 90,
        "maxBytes": 2000,
        "valid": True,
        "error": None,
        "recipientCount": 1,
        "channel": "SMS",
        "costMin": 9,
        "costMax": 17,
    }


def test_preview_rejects_unsupported_character_without_fake_length():
    result = _preview("안내🙂", ["01012345678"])

    assert result["valid"] is False
    assert result["byteLength"] is None
    assert result["costMin"] is None
    assert "EUC-KR" in result["error"]


@pytest.mark.parametrize(
    ("message", "channel", "cost"),
    [("a" * 91, "rcs", (27, 27)), ("a" * 91, "sms", (27, 27)), ("공지", "sms", (9, 9))],
)
def test_preview_uses_selected_channel_for_direct_messages(message, channel, cost):
    result = _preview(message, ["01012345678"], channel)

    assert result["valid"] is True
    assert (result["costMin"], result["costMax"]) == cost


def test_preview_image_uses_mms_price_and_deduplicates_recipients():
    result = _preview(
        "이미지 안내",
        ["01012345678", "01012345678"],
        attachment=True,
    )

    assert result["channel"] == "MMS"
    assert result["recipientCount"] == 1
    assert (result["costMin"], result["costMax"]) == (85, 85)
