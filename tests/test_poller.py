"""Poller.run_once 동작 검증."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ncp.client import ListResponse, MessageItem
from app.services.poller import Poller, _backoff_interval

# ── backoff 스케줄 ────────────────────────────────────────────────────────────


class TestBackoffInterval:
    """NCP 공식 권장: 5s → 15s → 30s → 1m → 5m → 30m."""

    def test_poll_count_0(self):
        assert _backoff_interval(0) == 5

    def test_poll_count_1(self):
        assert _backoff_interval(1) == 15

    def test_poll_count_2(self):
        assert _backoff_interval(2) == 30

    def test_poll_count_3(self):
        assert _backoff_interval(3) == 60

    def test_poll_count_4(self):
        assert _backoff_interval(4) == 300

    def test_poll_count_9(self):
        assert _backoff_interval(9) == 300

    def test_poll_count_10(self):
        assert _backoff_interval(10) == 1800

    def test_poll_count_99(self):
        # 70분 cutoff가 먼저 끊겠지만 스케줄 자체는 유지
        assert _backoff_interval(99) == 1800


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

    def test_force_refresh_queue(self, session_factory):
        """강제 새로고침 큐 동작 확인."""
        poller = Poller(
            db_factory=session_factory,
            ncp_client_factory=lambda: None,
        )
        assert poller.add_force_refresh(42) is True
        assert 42 in poller._force_refresh


# ── I4: force_refresh 쿨다운 ──────────────────────────────────────────────────


class TestForceRefreshCooldown:
    """10초 쿨다운으로 연타 방어."""

    def _make(self, session_factory):
        return Poller(
            db_factory=session_factory,
            ncp_client_factory=lambda: None,
        )

    def test_second_call_within_cooldown_ignored(self, session_factory):
        """10초 내 재요청은 False 반환 + 큐 상태 유지."""
        poller = self._make(session_factory)
        assert poller.add_force_refresh(1) is True
        # 바로 다시 호출
        assert poller.add_force_refresh(1) is False

    def test_different_campaigns_not_affected(self, session_factory):
        """쿨다운은 campaign_id 단위로 독립."""
        poller = self._make(session_factory)
        assert poller.add_force_refresh(1) is True
        assert poller.add_force_refresh(2) is True
        assert poller.add_force_refresh(1) is False
        assert poller.add_force_refresh(2) is False

    def test_call_after_cooldown_accepted(self, session_factory):
        """쿨다운 경과 후엔 재수락."""
        from datetime import UTC, datetime, timedelta

        poller = self._make(session_factory)
        assert poller.add_force_refresh(42) is True
        # 마지막 수락 시각을 11초 전으로 되돌림 (시간 이동 시뮬레이션)
        poller._force_refresh_at[42] = datetime.now(UTC) - timedelta(seconds=11)
        assert poller.add_force_refresh(42) is True


# ── 70분 cutoff sweep ─────────────────────────────────────────────────────────


class TestCutoffSweep:
    """DELIVERY_UNCONFIRMED 전환 로직 검증.

    ncp_request.sent_at 기준 70분 초과된 미완료 메시지는 폴링 대상에서 제거된다.
    """

    def _make_poller(self, session_factory, ncp_client=None):
        from unittest.mock import MagicMock
        if ncp_client is None:
            ncp_client = MagicMock()
            ncp_client.list_by_request_id = AsyncMock()
        return Poller(
            db_factory=session_factory,
            ncp_client_factory=lambda: ncp_client,
        )

    def _seed(self, session_factory, sample_user, sample_caller, sent_at_iso: str, msg_status: str = "PROCESSING"):
        """campaign + ncp_request + message 한 세트 생성. msg_id 반환."""
        from datetime import UTC, datetime

        from app.models import Campaign, Message, NcpRequest

        now = datetime.now(UTC).isoformat()
        s = session_factory()
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
            s.add(campaign)
            s.flush()

            req = NcpRequest(
                campaign_id=campaign.id,
                chunk_index=0,
                request_id="REQ-STALE",
                request_time=sent_at_iso,
                http_status=202,
                status_code="202",
                status_name="success",
                sent_at=sent_at_iso,  # ← cutoff 판정 기준
            )
            s.add(req)
            s.flush()

            msg = Message(
                campaign_id=campaign.id,
                ncp_request_id=req.id,
                to_number="01012345678",
                to_number_raw="010-1234-5678",
                message_id="MSG-STALE",
                status=msg_status,
                poll_count=5,
            )
            s.add(msg)
            s.flush()
            msg_id = msg.id
            campaign_id = campaign.id
            s.commit()
            return msg_id, campaign_id
        finally:
            s.close()

    @pytest.mark.asyncio
    async def test_cutoff_expires_old_stuck_message(
        self, session_factory, sample_user, sample_caller
    ):
        """sent_at이 71분 전이고 아직 PROCESSING인 메시지는 DELIVERY_UNCONFIRMED로 전환."""
        from datetime import UTC, datetime, timedelta

        from app.models import Campaign, Message

        old_sent_at = (datetime.now(UTC) - timedelta(minutes=71)).isoformat()
        msg_id, campaign_id = self._seed(session_factory, sample_user, sample_caller, old_sent_at)

        poller = self._make_poller(session_factory)
        await poller.run_once()

        v = session_factory()
        try:
            msg = v.get(Message, msg_id)
            assert msg is not None
            assert msg.status == "DELIVERY_UNCONFIRMED"
            assert msg.result_message == "70분 동안 NCP로부터 수신 확인을 받지 못했습니다"
            # 우리는 성공/실패를 모르므로 result_status는 건드리지 않음
            assert msg.result_status is None

            # 캠페인 집계: fail_count에 포함되어야 함
            c = v.get(Campaign, campaign_id)
            assert c.fail_count == 1
            assert c.pending_count == 0
        finally:
            v.close()

    @pytest.mark.asyncio
    async def test_cutoff_does_not_affect_recent_message(
        self, session_factory, sample_user, sample_caller
    ):
        """sent_at이 5분 전인 메시지는 cutoff 영향 받지 않음."""
        from datetime import UTC, datetime, timedelta

        from app.models import Message

        recent_sent_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
        msg_id, _ = self._seed(session_factory, sample_user, sample_caller, recent_sent_at)

        # NCP mock이 PROCESSING 응답만 돌려준다고 가정 (아직 미완료)
        processing_resp = ListResponse(
            request_id="REQ-STALE",
            status_code="200",
            status_name="success",
            messages=[
                MessageItem(
                    message_id="MSG-STALE",
                    to="01012345678",
                    status="PROCESSING",
                    status_name=None,
                    status_code=None,
                )
            ],
        )
        from unittest.mock import MagicMock
        client = MagicMock()
        client.list_by_request_id = AsyncMock(return_value=processing_resp)

        poller = self._make_poller(session_factory, client)
        await poller.run_once()

        v = session_factory()
        try:
            msg = v.get(Message, msg_id)
            assert msg is not None
            assert msg.status == "PROCESSING"  # 여전히 미완료 (cutoff 미도달)
        finally:
            v.close()

    @pytest.mark.asyncio
    async def test_cutoff_boundary_just_under_70min(
        self, session_factory, sample_user, sample_caller
    ):
        """69분 경과: 아직 cutoff 전이므로 살아있어야 함."""
        from datetime import UTC, datetime, timedelta

        from app.models import Message

        sent_at = (datetime.now(UTC) - timedelta(minutes=69)).isoformat()
        msg_id, _ = self._seed(session_factory, sample_user, sample_caller, sent_at)

        # NCP는 여전히 PROCESSING 응답
        processing_resp = ListResponse(
            request_id="REQ-STALE",
            status_code="200",
            status_name="success",
            messages=[
                MessageItem(
                    message_id="MSG-STALE",
                    to="01012345678",
                    status="PROCESSING",
                    status_name=None,
                    status_code=None,
                )
            ],
        )
        from unittest.mock import MagicMock
        client = MagicMock()
        client.list_by_request_id = AsyncMock(return_value=processing_resp)

        poller = self._make_poller(session_factory, client)
        await poller.run_once()

        v = session_factory()
        try:
            msg = v.get(Message, msg_id)
            assert msg.status == "PROCESSING"
        finally:
            v.close()

    @pytest.mark.asyncio
    async def test_unmatched_messages_still_advance_poll_count(
        self, session_factory, sample_user, sample_caller
    ):
        """C3: NCP 응답에 빠진 메시지도 poll_count/last_polled_at이 증가해야 한다.

        그렇지 않으면 해당 메시지의 poll_count가 0에 고정되고 backoff도 5초에
        묶여 5초마다 반복 폴링하는 핫루프가 발생한다.
        """
        from datetime import UTC, datetime, timedelta

        from app.models import Campaign, Message, NcpRequest

        recent_sent_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()

        # 한 ncp_request에 2개 메시지 — NCP는 그 중 1개만 반환한다고 가정
        s = session_factory()
        try:
            campaign = Campaign(
                created_by=sample_user.sub,
                caller_number=sample_caller.number,
                message_type="SMS",
                content="테스트",
                total_count=2,
                ok_count=0,
                fail_count=0,
                pending_count=2,
                state="DISPATCHED",
                created_at=recent_sent_at,
            )
            s.add(campaign)
            s.flush()

            req = NcpRequest(
                campaign_id=campaign.id,
                chunk_index=0,
                request_id="REQ-PARTIAL",
                request_time=recent_sent_at,
                http_status=202,
                status_code="202",
                status_name="success",
                sent_at=recent_sent_at,
            )
            s.add(req)
            s.flush()

            present_msg = Message(
                campaign_id=campaign.id,
                ncp_request_id=req.id,
                to_number="01011111111",
                to_number_raw="010-1111-1111",
                message_id="MSG-PRESENT",
                status="PROCESSING",
                poll_count=0,
            )
            missing_msg = Message(
                campaign_id=campaign.id,
                ncp_request_id=req.id,
                to_number="01022222222",
                to_number_raw="010-2222-2222",
                message_id="MSG-MISSING",
                status="PROCESSING",
                poll_count=0,
            )
            s.add_all([present_msg, missing_msg])
            s.flush()
            present_id = present_msg.id
            missing_id = missing_msg.id
            s.commit()
        finally:
            s.close()

        # NCP는 1건만 COMPLETED로 반환 (missing_msg는 응답에서 빠짐)
        partial_resp = ListResponse(
            request_id="REQ-PARTIAL",
            status_code="200",
            status_name="success",
            messages=[
                MessageItem(
                    message_id="MSG-PRESENT",
                    to="01011111111",
                    status="COMPLETED",
                    status_name="success",
                    status_code="0",
                )
            ],
        )
        from unittest.mock import MagicMock
        client = MagicMock()
        client.list_by_request_id = AsyncMock(return_value=partial_resp)

        poller = self._make_poller(session_factory, client)
        await poller.run_once()

        v = session_factory()
        try:
            present = v.get(Message, present_id)
            missing = v.get(Message, missing_id)

            # 매칭된 메시지는 정상 업데이트
            assert present.status == "COMPLETED"
            assert present.poll_count == 1

            # 누락된 메시지도 poll_count는 증가해야 함 (핫루프 방지)
            assert missing.status == "PROCESSING"  # 아직 non-final
            assert missing.poll_count == 1
            assert missing.last_polled_at is not None
        finally:
            v.close()

    @pytest.mark.asyncio
    async def test_cutoff_skips_already_final(
        self, session_factory, sample_user, sample_caller
    ):
        """이미 COMPLETED인 메시지는 cutoff 영향 없음 (덮어쓰지 않음)."""
        from datetime import UTC, datetime, timedelta

        from app.models import Message

        old_sent_at = (datetime.now(UTC) - timedelta(minutes=200)).isoformat()
        msg_id, _ = self._seed(
            session_factory, sample_user, sample_caller, old_sent_at, msg_status="COMPLETED"
        )

        # 기존에 success로 완료된 상태로 만들기
        s = session_factory()
        try:
            m = s.get(Message, msg_id)
            m.result_status = "success"
            m.result_code = "0"
            m.result_message = "완료"
            s.commit()
        finally:
            s.close()

        poller = self._make_poller(session_factory)
        await poller.run_once()

        v = session_factory()
        try:
            msg = v.get(Message, msg_id)
            assert msg.status == "COMPLETED"  # 건드리지 않음
            assert msg.result_status == "success"
            assert msg.result_message == "완료"  # cutoff 메시지로 덮어쓰지 않음
        finally:
            v.close()
