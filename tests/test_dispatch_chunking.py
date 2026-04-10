"""dispatch_campaign 청크 분할 테스트 — 250건 → 3개 청크(100/100/50)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ncp.client import ListResponse, SendResponse
from app.services.compose import CHUNK_SIZE


class TestDispatchChunking:
    def _make_ncp_client(self, call_tracker: list):
        """send_sms 호출을 추적하는 mock NCP 클라이언트."""
        client = MagicMock()

        async def fake_send_sms(from_number, content, to_numbers, message_type="SMS", subject=None, reserve_time=None, reserve_time_zone=None):
            call_tracker.append(len(to_numbers))
            return SendResponse(
                request_id=f"REQ-{len(call_tracker):04d}",
                request_time="2026-04-08T12:00:00",
                status_code="202",
                status_name="success",
            )

        async def fake_list_by_request_id(request_id):
            return ListResponse(
                request_id=request_id,
                status_code="200",
                status_name="success",
                messages=[],
            )

        client.send_sms = fake_send_sms
        client.list_by_request_id = fake_list_by_request_id
        return client

    @pytest.mark.asyncio
    async def test_250_recipients_creates_3_chunks(
        self, session_factory, sample_user, sample_caller
    ):
        """250건 발송 시 3개 청크(100/100/50)가 모두 처리된다."""
        from app.services.compose import dispatch_campaign

        call_tracker: list[int] = []
        ncp_client = self._make_ncp_client(call_tracker)

        recipients = [f"010{i:08d}" for i in range(250)]

        db = session_factory()
        try:
            campaign = await dispatch_campaign(
                db=db,
                ncp_client=ncp_client,
                created_by=sample_user.sub,
                caller_number=sample_caller.number,
                content="250건 테스트 발송",
                recipients=recipients,
                message_type="SMS",
            )
        finally:
            db.close()

        # send_sms가 정확히 3번 호출되어야 함
        assert len(call_tracker) == 3, f"청크 수 불일치: {call_tracker}"

        # 각 청크 크기 확인 (100/100/50)
        assert call_tracker[0] == 100
        assert call_tracker[1] == 100
        assert call_tracker[2] == 50

    @pytest.mark.asyncio
    async def test_100_recipients_creates_1_chunk(
        self, session_factory, sample_user, sample_caller
    ):
        """정확히 100건이면 1개 청크."""
        from app.services.compose import dispatch_campaign

        call_tracker: list[int] = []
        ncp_client = self._make_ncp_client(call_tracker)

        recipients = [f"010{i:08d}" for i in range(100)]

        db = session_factory()
        try:
            await dispatch_campaign(
                db=db,
                ncp_client=ncp_client,
                created_by=sample_user.sub,
                caller_number=sample_caller.number,
                content="100건 테스트",
                recipients=recipients,
                message_type="SMS",
            )
        finally:
            db.close()

        assert len(call_tracker) == 1
        assert call_tracker[0] == 100

    @pytest.mark.asyncio
    async def test_101_recipients_creates_2_chunks(
        self, session_factory, sample_user, sample_caller
    ):
        """101건이면 2개 청크(100/1)."""
        from app.services.compose import dispatch_campaign

        call_tracker: list[int] = []
        ncp_client = self._make_ncp_client(call_tracker)

        recipients = [f"010{i:08d}" for i in range(101)]

        db = session_factory()
        try:
            await dispatch_campaign(
                db=db,
                ncp_client=ncp_client,
                created_by=sample_user.sub,
                caller_number=sample_caller.number,
                content="101건 테스트",
                recipients=recipients,
                message_type="SMS",
            )
        finally:
            db.close()

        assert len(call_tracker) == 2
        assert call_tracker[0] == 100
        assert call_tracker[1] == 1

    @pytest.mark.asyncio
    async def test_chunk_size_constant_is_100(self):
        """CHUNK_SIZE 상수가 100인지 확인."""
        assert CHUNK_SIZE == 100

    @pytest.mark.asyncio
    async def test_partial_failure_continues_other_chunks(
        self, session_factory, sample_user, sample_caller
    ):
        """첫 번째 청크 실패해도 나머지 청크는 계속 처리된다."""
        from sqlalchemy import select

        from app.models import NcpRequest
        from app.services.compose import dispatch_campaign

        call_count = 0

        async def fail_first_succeed_rest(
            from_number, content, to_numbers, message_type="SMS", subject=None,
            reserve_time=None, reserve_time_zone=None,
        ):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("첫 번째 청크 실패")
            return SendResponse(
                request_id=f"REQ-{call_count:04d}",
                request_time="2026-04-08T12:00:00",
                status_code="202",
                status_name="success",
            )

        client = MagicMock()
        client.send_sms = fail_first_succeed_rest
        client.list_by_request_id = AsyncMock(
            return_value=ListResponse(
                request_id="REQ", status_code="200", status_name="success", messages=[]
            )
        )

        recipients = [f"010{i:08d}" for i in range(150)]  # 2청크: 100+50

        db = session_factory()
        try:
            campaign = await dispatch_campaign(
                db=db,
                ncp_client=client,
                created_by=sample_user.sub,
                caller_number=sample_caller.number,
                content="부분 실패 테스트",
                recipients=recipients,
                message_type="SMS",
            )

            # 2개 청크 모두 NcpRequest 레코드 있어야 함
            ncp_reqs = list(
                db.execute(
                    select(NcpRequest).where(NcpRequest.campaign_id == campaign.id)
                ).scalars().all()
            )
            assert len(ncp_reqs) == 2

            # 캠페인 상태는 PARTIAL_FAILED
            assert campaign.state == "PARTIAL_FAILED"
        finally:
            db.close()
