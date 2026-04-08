"""dispatch_campaign 통합 테스트 — mock NCP 클라이언트 사용."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ncp.client import ListResponse, MessageItem, SendResponse
from app.services.compose import validate_message


# ── validate_message ──────────────────────────────────────────────────────────


class TestValidateMessage:
    def test_short_message_is_sms(self):
        result = validate_message("안녕하세요")
        assert result["ok"] is True
        assert result["message_type"] == "SMS"
        assert result["byte_len"] > 0

    def test_long_message_is_lms(self):
        # 한글 46자 = 92 byte → LMS
        result = validate_message("가" * 46)
        assert result["ok"] is True
        assert result["message_type"] == "LMS"

    def test_emoji_returns_error(self):
        result = validate_message("안녕 😊")
        assert result["ok"] is False
        assert result["error"] is not None

    def test_too_long_returns_error(self):
        result = validate_message("가" * 1001)
        assert result["ok"] is False
        assert result["error"] is not None

    def test_empty_is_sms(self):
        result = validate_message("")
        assert result["ok"] is True
        assert result["message_type"] == "SMS"
        assert result["byte_len"] == 0

    def test_explicit_type_override(self):
        result = validate_message("안녕하세요", message_type="LMS")
        assert result["ok"] is True
        assert result["message_type"] == "LMS"


# ── dispatch_campaign ─────────────────────────────────────────────────────────


class TestDispatchCampaign:
    @pytest.mark.asyncio
    async def test_dispatch_creates_campaign(self, session_factory, sample_user, sample_caller, mock_ncp_client):
        """정상 발송 시 Campaign이 생성됨."""
        from app.services.compose import dispatch_campaign

        db = session_factory()
        try:
            recipients = [f"010{i:08d}" for i in range(3)]
            campaign = await dispatch_campaign(
                db=db,
                ncp_client=mock_ncp_client,
                created_by=sample_user.sub,
                caller_number=sample_caller.number,
                content="테스트 공지입니다",
                recipients=recipients,
                message_type="SMS",
            )

            assert campaign.id is not None
            assert campaign.total_count == 3
            assert campaign.state in ("DISPATCHED", "DISPATCHING", "COMPLETED", "PARTIAL_FAILED")
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_dispatch_invalid_caller_raises(self, session_factory, sample_user):
        """비활성 발신번호는 ValueError."""
        from app.services.compose import dispatch_campaign

        db = session_factory()
        try:
            with pytest.raises(ValueError, match="활성 목록"):
                await dispatch_campaign(
                    db=db,
                    ncp_client=MagicMock(),
                    created_by=sample_user.sub,
                    caller_number="0200000000",  # 등록 안 된 번호
                    content="테스트",
                    recipients=["01012345678"],
                    message_type="SMS",
                )
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_dispatch_empty_recipients_raises(self, session_factory, sample_user, sample_caller):
        """빈 수신자 목록은 ValueError."""
        from app.services.compose import dispatch_campaign

        db = session_factory()
        try:
            with pytest.raises(ValueError, match="비어"):
                await dispatch_campaign(
                    db=db,
                    ncp_client=MagicMock(),
                    created_by=sample_user.sub,
                    caller_number=sample_caller.number,
                    content="테스트",
                    recipients=[],
                    message_type="SMS",
                )
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_dispatch_ncp_failure_marks_failed(self, session_factory, sample_user, sample_caller):
        """NCP 호출 실패 시 campaign state가 FAILED."""
        from app.services.compose import dispatch_campaign

        failing_client = MagicMock()

        async def raise_error(*args, **kwargs):
            raise RuntimeError("NCP 연결 실패")

        failing_client.send_sms = raise_error
        failing_client.list_by_request_id = AsyncMock(return_value=ListResponse(
            request_id="none", status_code="200", status_name="success", messages=[]
        ))

        db = session_factory()
        try:
            campaign = await dispatch_campaign(
                db=db,
                ncp_client=failing_client,
                created_by=sample_user.sub,
                caller_number=sample_caller.number,
                content="테스트",
                recipients=["01012345678"],
                message_type="SMS",
            )
            assert campaign.state == "FAILED"
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_dispatch_creates_ncp_requests(self, session_factory, sample_user, sample_caller, mock_ncp_client):
        """청크 수만큼 NcpRequest 레코드가 생성됨."""
        from sqlalchemy import select
        from app.models import NcpRequest
        from app.services.compose import dispatch_campaign

        db = session_factory()
        try:
            recipients = [f"010{i:08d}" for i in range(5)]
            campaign = await dispatch_campaign(
                db=db,
                ncp_client=mock_ncp_client,
                created_by=sample_user.sub,
                caller_number=sample_caller.number,
                content="공지",
                recipients=recipients,
                message_type="SMS",
            )

            ncp_reqs = list(
                db.execute(
                    select(NcpRequest).where(NcpRequest.campaign_id == campaign.id)
                ).scalars().all()
            )
            # 5명 → 1청크
            assert len(ncp_reqs) == 1
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_dispatch_creates_messages(self, session_factory, sample_user, sample_caller, mock_ncp_client):
        """수신자 수만큼 Message 레코드가 생성됨."""
        from sqlalchemy import select
        from app.models import Message
        from app.services.compose import dispatch_campaign

        db = session_factory()
        try:
            recipients = ["01012345678", "01087654321"]
            campaign = await dispatch_campaign(
                db=db,
                ncp_client=mock_ncp_client,
                created_by=sample_user.sub,
                caller_number=sample_caller.number,
                content="공지",
                recipients=recipients,
                message_type="SMS",
            )

            msgs = list(
                db.execute(
                    select(Message).where(Message.campaign_id == campaign.id)
                ).scalars().all()
            )
            assert len(msgs) == 2
        finally:
            db.close()
