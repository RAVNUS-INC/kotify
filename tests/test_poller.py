"""Poller.run_once 동작 검증."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ncp.client import ListResponse, MessageItem
from app.services.poller import Poller, _backoff_interval

# ── backoff 스케줄 ────────────────────────────────────────────────────────────


class TestBackoffInterval:
    def test_poll_count_0(self):
        assert _backoff_interval(0) == 5

    def test_poll_count_1(self):
        assert _backoff_interval(1) == 10

    def test_poll_count_2(self):
        assert _backoff_interval(2) == 30

    def test_poll_count_3(self):
        assert _backoff_interval(3) == 60

    def test_poll_count_4(self):
        assert _backoff_interval(4) == 300

    def test_poll_count_9(self):
        assert _backoff_interval(9) == 300

    def test_poll_count_10(self):
        assert _backoff_interval(10) == 900

    def test_poll_count_99(self):
        assert _backoff_interval(99) == 900


# ── Poller.run_once ───────────────────────────────────────────────────────────


class TestPollerRunOnce:
    """Poller 테스트는 session_factory를 사용해 독립적인 세션으로 검증."""

    def _make_poller(self, session_factory, ncp_client):
        return Poller(
            db_factory=session_factory,
            ncp_client_factory=lambda: ncp_client,
        )

    @pytest.mark.asyncio
    async def test_run_once_no_pending_messages(self, session_factory):
        """미완료 메시지가 없으면 아무것도 하지 않음."""
        ncp_client = MagicMock()
        ncp_client.list_by_request_id = AsyncMock()

        poller = self._make_poller(session_factory, ncp_client)
        await poller.run_once()

        # NCP 호출 없음
        ncp_client.list_by_request_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_once_updates_message_status(
        self, session_factory, sample_user, sample_caller, mock_ncp_client
    ):
        """미완료 메시지가 있으면 NCP 조회 후 상태 업데이트."""
        from app.models import Campaign, Message, NcpRequest

        now = datetime.now(UTC).isoformat()

        # 데이터 삽입 (sample_user, sample_caller는 db_session을 통해 이미 커밋됨)
        setup_session = session_factory()
        try:
            campaign = Campaign(
                created_by=sample_user.sub,
                caller_number=sample_caller.number,
                message_type="SMS",
                content="테스트",
                total_count=1,
                ok_count=0,
                fail_count=0,
                pending_count=1,
                state="DISPATCHED",
                created_at=now,
            )
            setup_session.add(campaign)
            setup_session.flush()

            ncp_req = NcpRequest(
                campaign_id=campaign.id,
                chunk_index=0,
                request_id="REQ-0001",
                request_time=now,
                http_status=202,
                status_code="202",
                status_name="success",
                sent_at=now,
            )
            setup_session.add(ncp_req)
            setup_session.flush()

            msg = Message(
                campaign_id=campaign.id,
                ncp_request_id=ncp_req.id,
                to_number="01012345678",
                to_number_raw="010-1234-5678",
                message_id="MSG-001",
                status="PENDING",
                poll_count=0,
            )
            setup_session.add(msg)
            setup_session.flush()
            msg_id = msg.id
            setup_session.commit()
        finally:
            setup_session.close()

        # NCP가 COMPLETED 반환하도록 설정
        completed_resp = ListResponse(
            request_id="REQ-0001",
            status_code="200",
            status_name="success",
            messages=[
                MessageItem(
                    message_id="MSG-001",
                    to="01012345678",
                    status="COMPLETED",
                    status_name="success",
                    status_code="0",
                )
            ],
        )
        mock_ncp_client.list_by_request_id = AsyncMock(return_value=completed_resp)

        poller = self._make_poller(session_factory, mock_ncp_client)
        await poller.run_once()

        # 새 세션으로 결과 조회
        verify_session = session_factory()
        try:
            updated_msg = verify_session.get(Message, msg_id)
            assert updated_msg is not None
            assert updated_msg.status == "COMPLETED"
            assert updated_msg.result_status == "success"
            assert updated_msg.poll_count >= 1
        finally:
            verify_session.close()

    @pytest.mark.asyncio
    async def test_run_once_no_ncp_client(self, session_factory):
        """NCP 클라이언트가 None이면 skip."""
        ncp_mock = MagicMock()
        ncp_mock.list_by_request_id = AsyncMock()

        poller = Poller(
            db_factory=session_factory,
            ncp_client_factory=lambda: None,
        )
        await poller.run_once()
        ncp_mock.list_by_request_id.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_once_timeout_messages(
        self, session_factory, sample_user, sample_caller
    ):
        """발송 후 1시간 초과된 메시지는 TIMEOUT 처리."""
        from app.models import Campaign, Message, NcpRequest

        two_hours_ago = (
            datetime.now(UTC) - timedelta(hours=2)
        ).isoformat()

        setup_session = session_factory()
        try:
            campaign = Campaign(
                created_by=sample_user.sub,
                caller_number=sample_caller.number,
                message_type="SMS",
                content="오래된 캠페인",
                total_count=1,
                ok_count=0,
                fail_count=0,
                pending_count=1,
                state="DISPATCHED",
                created_at=two_hours_ago,
            )
            setup_session.add(campaign)
            setup_session.flush()

            ncp_req = NcpRequest(
                campaign_id=campaign.id,
                chunk_index=0,
                request_id="REQ-OLD",
                request_time=two_hours_ago,
                http_status=202,
                status_code="202",
                status_name="success",
                sent_at=two_hours_ago,
            )
            setup_session.add(ncp_req)
            setup_session.flush()

            msg = Message(
                campaign_id=campaign.id,
                ncp_request_id=ncp_req.id,
                to_number="01099998888",
                to_number_raw="01099998888",
                message_id="MSG-OLD",
                status="PENDING",
                poll_count=5,
            )
            setup_session.add(msg)
            setup_session.flush()
            msg_id = msg.id
            setup_session.commit()
        finally:
            setup_session.close()

        ncp_client = MagicMock()
        ncp_client.list_by_request_id = AsyncMock()

        poller = self._make_poller(session_factory, ncp_client)
        await poller.run_once()

        verify_session = session_factory()
        try:
            updated_msg = verify_session.get(Message, msg_id)
            assert updated_msg is not None
            assert updated_msg.status == "TIMEOUT"
        finally:
            verify_session.close()

        # 타임아웃이면 NCP 조회 없이 처리
        ncp_client.list_by_request_id.assert_not_called()

    def test_force_refresh_queue(self, session_factory):
        """강제 새로고침 큐 동작 확인."""
        poller = Poller(
            db_factory=session_factory,
            ncp_client_factory=lambda: None,
        )
        poller.add_force_refresh(42)
        assert 42 in poller._force_refresh
