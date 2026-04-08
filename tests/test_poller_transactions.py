"""Poller 트랜잭션 경계 테스트 — 한 청크 실패 시 다른 청크 영향 없음."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from app.ncp.client import ListResponse, MessageItem
from app.services.poller import Poller


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class TestPollerTransactions:
    def _make_poller(self, session_factory, ncp_client):
        return Poller(
            db_factory=session_factory,
            ncp_client_factory=lambda: ncp_client,
        )

    def _setup_two_chunks(self, session_factory, sample_user, sample_caller):
        """두 개의 NcpRequest + 각각 1개의 Message 준비."""
        from app.models import Campaign, Message, NcpRequest

        now = _now_iso()
        setup_session = session_factory()
        try:
            campaign = Campaign(
                created_by=sample_user.sub,
                caller_number=sample_caller.number,
                message_type="SMS",
                content="트랜잭션 테스트",
                total_count=2,
                ok_count=0,
                fail_count=0,
                pending_count=2,
                state="DISPATCHED",
                created_at=now,
            )
            setup_session.add(campaign)
            setup_session.flush()

            ncp_req1 = NcpRequest(
                campaign_id=campaign.id,
                chunk_index=0,
                request_id="REQ-TX-001",
                request_time=now,
                http_status=202,
                status_code="202",
                status_name="success",
                sent_at=now,
            )
            ncp_req2 = NcpRequest(
                campaign_id=campaign.id,
                chunk_index=1,
                request_id="REQ-TX-002",
                request_time=now,
                http_status=202,
                status_code="202",
                status_name="success",
                sent_at=now,
            )
            setup_session.add(ncp_req1)
            setup_session.add(ncp_req2)
            setup_session.flush()

            msg1 = Message(
                campaign_id=campaign.id,
                ncp_request_id=ncp_req1.id,
                to_number="01011111111",
                to_number_raw="01011111111",
                message_id="MSG-TX-001",
                status="PENDING",
                poll_count=0,
            )
            msg2 = Message(
                campaign_id=campaign.id,
                ncp_request_id=ncp_req2.id,
                to_number="01022222222",
                to_number_raw="01022222222",
                message_id="MSG-TX-002",
                status="PENDING",
                poll_count=0,
            )
            setup_session.add(msg1)
            setup_session.add(msg2)
            setup_session.flush()

            campaign_id = campaign.id
            msg1_id = msg1.id
            msg2_id = msg2.id
            setup_session.commit()
        finally:
            setup_session.close()

        return campaign_id, msg1_id, msg2_id

    @pytest.mark.asyncio
    async def test_chunk1_failure_does_not_affect_chunk2(
        self, session_factory, sample_user, sample_caller
    ):
        """첫 번째 청크 폴링 실패 시 두 번째 청크는 정상 처리됨."""
        from app.models import Message

        campaign_id, msg1_id, msg2_id = self._setup_two_chunks(
            session_factory, sample_user, sample_caller
        )

        call_count = 0

        async def selective_failure(request_id):
            nonlocal call_count
            call_count += 1
            if request_id == "REQ-TX-001":
                raise RuntimeError("첫 번째 청크 NCP 조회 실패")
            # 두 번째 청크는 정상
            return ListResponse(
                request_id=request_id,
                status_code="200",
                status_name="success",
                messages=[
                    MessageItem(
                        message_id="MSG-TX-002",
                        to="01022222222",
                        status="COMPLETED",
                        status_name="success",
                        status_code="0",
                    )
                ],
            )

        ncp_client = MagicMock()
        ncp_client.list_by_request_id = selective_failure

        poller = self._make_poller(session_factory, ncp_client)
        await poller.run_once()

        # 검증
        verify_session = session_factory()
        try:
            msg1 = verify_session.get(Message, msg1_id)
            msg2 = verify_session.get(Message, msg2_id)

            # msg1은 실패로 PENDING 유지
            assert msg1.status == "PENDING", f"msg1 상태: {msg1.status}"

            # msg2는 COMPLETED로 업데이트됨
            assert msg2.status == "COMPLETED", f"msg2 상태: {msg2.status}"
        finally:
            verify_session.close()

    @pytest.mark.asyncio
    async def test_both_chunks_succeed_independently(
        self, session_factory, sample_user, sample_caller
    ):
        """두 청크 모두 성공 시 각각 독립적으로 커밋됨."""
        from app.models import Message

        campaign_id, msg1_id, msg2_id = self._setup_two_chunks(
            session_factory, sample_user, sample_caller
        )

        async def always_success(request_id):
            to_num = "01011111111" if request_id == "REQ-TX-001" else "01022222222"
            msg_id = "MSG-TX-001" if request_id == "REQ-TX-001" else "MSG-TX-002"
            return ListResponse(
                request_id=request_id,
                status_code="200",
                status_name="success",
                messages=[
                    MessageItem(
                        message_id=msg_id,
                        to=to_num,
                        status="COMPLETED",
                        status_name="success",
                        status_code="0",
                    )
                ],
            )

        ncp_client = MagicMock()
        ncp_client.list_by_request_id = always_success

        poller = self._make_poller(session_factory, ncp_client)
        await poller.run_once()

        verify_session = session_factory()
        try:
            msg1 = verify_session.get(Message, msg1_id)
            msg2 = verify_session.get(Message, msg2_id)

            assert msg1.status == "COMPLETED"
            assert msg2.status == "COMPLETED"
        finally:
            verify_session.close()

    @pytest.mark.asyncio
    async def test_all_chunks_fail_independently(
        self, session_factory, sample_user, sample_caller
    ):
        """모든 청크 실패해도 루프는 정상 종료."""
        campaign_id, msg1_id, msg2_id = self._setup_two_chunks(
            session_factory, sample_user, sample_caller
        )

        async def always_fail(request_id):
            raise RuntimeError("NCP 조회 실패")

        ncp_client = MagicMock()
        ncp_client.list_by_request_id = always_fail

        poller = self._make_poller(session_factory, ncp_client)
        # 예외가 전파되지 않아야 함
        await poller.run_once()
