"""Phase B2/B3 예약 발송 테스트.

- parse_reserve_time: 포맷/타임존/과거 시각 검증
- dispatch_campaign 예약 경로: state=RESERVED, sent_at=미래UTC, send_sms에 reserve 파라미터 전달
- NCPClient.send_sms: reserve 파라미터가 request body에 포함되는지
- NCPClient.cancel_reservation / get_reserve_status: HTTP 호출 검증
- Poller._poll_reservations: reserveStatus → campaign.state 전환 매핑
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.ncp.client import (
    NCPBadRequest,
    NCPClient,
    ReserveStatusResponse,
    SendResponse,
)
from app.services.compose import parse_reserve_time


# ── parse_reserve_time ───────────────────────────────────────────────────────


class TestParseReserveTime:
    def _future_local(self, hours: int = 2) -> str:
        """현재로부터 N시간 뒤의 로컬(KST) 문자열."""
        from zoneinfo import ZoneInfo
        kst = ZoneInfo("Asia/Seoul")
        dt = datetime.now(kst) + timedelta(hours=hours)
        return dt.strftime("%Y-%m-%d %H:%M")

    def test_parses_valid_future_time(self):
        local = self._future_local(hours=3)
        ncp, utc_iso = parse_reserve_time(local, "Asia/Seoul")
        assert ncp == local
        assert utc_iso.endswith("+00:00")
        # UTC ISO는 파싱 가능해야 함
        parsed = datetime.fromisoformat(utc_iso)
        assert parsed.tzinfo is not None

    def test_datetime_local_T_separator_accepted(self):
        """HTML datetime-local 인풋은 'T' 구분자를 쓴다."""
        local = self._future_local(hours=3).replace(" ", "T")
        ncp, _ = parse_reserve_time(local, "Asia/Seoul")
        # 내부적으로 공백 포맷으로 정규화됨
        assert " " in ncp and "T" not in ncp

    def test_past_time_raises(self):
        with pytest.raises(ValueError, match="10분 이후"):
            parse_reserve_time("2020-01-01 00:00", "Asia/Seoul")

    def test_within_min_lead_raises(self):
        """현재 + 5분은 최소 리드타임(10분) 미달."""
        from zoneinfo import ZoneInfo
        kst = ZoneInfo("Asia/Seoul")
        dt = datetime.now(kst) + timedelta(minutes=5)
        with pytest.raises(ValueError, match="10분 이후"):
            parse_reserve_time(dt.strftime("%Y-%m-%d %H:%M"), "Asia/Seoul")

    def test_bad_format_raises(self):
        with pytest.raises(ValueError, match="포맷 오류"):
            parse_reserve_time("not-a-date", "Asia/Seoul")

    def test_unknown_timezone_raises(self):
        with pytest.raises(ValueError, match="타임존"):
            parse_reserve_time("2099-01-01 00:00", "Bogus/Zone")

    def test_kst_to_utc_conversion(self):
        """KST 14:30 → UTC 05:30."""
        # 충분히 미래로
        ncp, utc_iso = parse_reserve_time("2099-06-15 14:30", "Asia/Seoul")
        parsed = datetime.fromisoformat(utc_iso)
        assert parsed.hour == 5 and parsed.minute == 30


# ── NCPClient.send_sms with reserve ──────────────────────────────────────────


class TestSendSmsReserve:
    @pytest.mark.asyncio
    async def test_reserve_params_in_body(self, monkeypatch):
        """reserve_time 지정 시 body에 reserveTime/reserveTimeZone이 포함된다."""
        client = NCPClient("ak", "sk", "svc-1")

        # signature.make_headers 를 고정값으로 대체 (테스트 안정성)
        monkeypatch.setattr(
            "app.ncp.client.make_headers",
            lambda *a, **k: {"x-ncp-apigw-timestamp": "0"},
        )

        captured: dict = {}

        async def fake_post(url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            return httpx.Response(
                202,
                json={
                    "requestId": "RES-ID-001",
                    "requestTime": "2099-01-01T00:00:00",
                    "statusCode": "202",
                    "statusName": "reserved",
                },
            )

        monkeypatch.setattr(client._client, "post", fake_post)

        resp = await client.send_sms(
            from_number="0212345678",
            content="예약 테스트",
            to_numbers=["01012345678"],
            reserve_time="2099-06-15 14:30",
            reserve_time_zone="Asia/Seoul",
        )
        assert isinstance(resp, SendResponse)
        assert resp.request_id == "RES-ID-001"
        assert captured["json"]["reserveTime"] == "2099-06-15 14:30"
        assert captured["json"]["reserveTimeZone"] == "Asia/Seoul"
        await client.aclose()

    @pytest.mark.asyncio
    async def test_reserve_params_absent_in_normal_send(self, monkeypatch):
        """즉시 발송 시 body에 reserve 필드가 포함되지 않는다."""
        client = NCPClient("ak", "sk", "svc-1")
        monkeypatch.setattr(
            "app.ncp.client.make_headers",
            lambda *a, **k: {"x-ncp-apigw-timestamp": "0"},
        )
        captured: dict = {}

        async def fake_post(url, json=None, headers=None):
            captured["json"] = json
            return httpx.Response(
                202,
                json={
                    "requestId": "R",
                    "requestTime": "t",
                    "statusCode": "202",
                    "statusName": "ok",
                },
            )

        monkeypatch.setattr(client._client, "post", fake_post)
        await client.send_sms(
            from_number="0212345678",
            content="hi",
            to_numbers=["01011112222"],
        )
        assert "reserveTime" not in captured["json"]
        assert "reserveTimeZone" not in captured["json"]
        await client.aclose()

    @pytest.mark.asyncio
    async def test_reserve_partial_params_rejected(self):
        """reserve_time / reserve_time_zone 은 함께 있어야 한다."""
        client = NCPClient("ak", "sk", "svc-1")
        with pytest.raises(ValueError, match="함께"):
            await client.send_sms(
                from_number="0212345678",
                content="x",
                to_numbers=["01011112222"],
                reserve_time="2099-06-15 14:30",
            )
        await client.aclose()


# ── NCPClient.cancel_reservation / get_reserve_status ────────────────────────


class TestReserveManagement:
    @pytest.mark.asyncio
    async def test_cancel_reservation_204(self, monkeypatch):
        client = NCPClient("ak", "sk", "svc-1")
        monkeypatch.setattr(
            "app.ncp.client.make_headers",
            lambda *a, **k: {"x-ncp-apigw-timestamp": "0"},
        )
        captured: dict = {}

        async def fake_delete(url, headers=None):
            captured["url"] = url
            return httpx.Response(204)

        monkeypatch.setattr(client._client, "delete", fake_delete)
        # 예외 없이 완료
        await client.cancel_reservation("RES-ID-001")
        assert "/reservations/RES-ID-001" in captured["url"]
        await client.aclose()

    @pytest.mark.asyncio
    async def test_cancel_reservation_400_raises(self, monkeypatch):
        client = NCPClient("ak", "sk", "svc-1")
        monkeypatch.setattr(
            "app.ncp.client.make_headers",
            lambda *a, **k: {"x-ncp-apigw-timestamp": "0"},
        )

        async def fake_delete(url, headers=None):
            return httpx.Response(400, json={"errorMessage": "not READY"})

        monkeypatch.setattr(client._client, "delete", fake_delete)
        with pytest.raises(NCPBadRequest):
            await client.cancel_reservation("RES-ID-002")
        await client.aclose()

    @pytest.mark.asyncio
    async def test_get_reserve_status_parses_response(self, monkeypatch):
        client = NCPClient("ak", "sk", "svc-1")
        monkeypatch.setattr(
            "app.ncp.client.make_headers",
            lambda *a, **k: {"x-ncp-apigw-timestamp": "0"},
        )

        async def fake_get(url, headers=None):
            return httpx.Response(
                200,
                json={
                    "reserveId": "RES-1",
                    "reserveTimeZone": "Asia/Seoul",
                    "reserveTime": "2099-06-15 14:30",
                    "reserveStatus": "READY",
                },
            )

        monkeypatch.setattr(client._client, "get", fake_get)
        resp = await client.get_reserve_status("RES-1")
        assert isinstance(resp, ReserveStatusResponse)
        assert resp.reserve_status == "READY"
        assert resp.reserve_time == "2099-06-15 14:30"
        await client.aclose()


# ── dispatch_campaign 예약 경로 ───────────────────────────────────────────────


class TestDispatchReserved:
    @pytest.mark.asyncio
    async def test_reserved_campaign_state_and_fields(
        self, session_factory, sample_user, sample_caller
    ):
        """예약 캠페인: state=RESERVED, reserve_time/timezone 저장."""
        from app.services.compose import dispatch_campaign

        # Mock client that records reserve params
        recorded: dict = {}

        async def fake_send(
            from_number, content, to_numbers, message_type="SMS",
            subject=None, reserve_time=None, reserve_time_zone=None,
            file_ids=None,
        ):
            recorded["reserve_time"] = reserve_time
            recorded["reserve_time_zone"] = reserve_time_zone
            return SendResponse(
                request_id="RES-REQ-0001",
                request_time="2099-01-01T00:00:00",
                status_code="202",
                status_name="success",
            )

        client = MagicMock()
        client.send_sms = fake_send
        # 예약 경로에서는 list_by_request_id가 호출되지 않아야 한다.
        client.list_by_request_id = AsyncMock(
            side_effect=AssertionError("list should not be called in reserve path")
        )

        db = session_factory()
        try:
            # 현재 + 3시간 (최소 리드타임 10분 통과)
            from zoneinfo import ZoneInfo
            kst = ZoneInfo("Asia/Seoul")
            future_local = (datetime.now(kst) + timedelta(hours=3)).strftime(
                "%Y-%m-%d %H:%M"
            )

            campaign = await dispatch_campaign(
                db=db,
                ncp_client=client,
                created_by=sample_user.sub,
                caller_number=sample_caller.number,
                content="예약 공지입니다",
                recipients=["01012345678", "01087654321"],
                message_type="SMS",
                reserve_time_local=future_local,
                reserve_timezone="Asia/Seoul",
            )

            assert campaign.state == "RESERVED"
            assert campaign.reserve_time == future_local
            assert campaign.reserve_timezone == "Asia/Seoul"
            assert recorded["reserve_time"] == future_local
            assert recorded["reserve_time_zone"] == "Asia/Seoul"

            # NcpRequest.sent_at 는 예약 실행 시각(UTC, 미래)
            from sqlalchemy import select

            from app.models import NcpRequest
            req = db.execute(
                select(NcpRequest).where(NcpRequest.campaign_id == campaign.id)
            ).scalar_one()
            sent_dt = datetime.fromisoformat(req.sent_at)
            assert sent_dt > datetime.now(UTC) + timedelta(hours=2, minutes=30)

            # 메시지는 PENDING 상태로 생성됨
            from app.models import Message
            msgs = list(
                db.execute(
                    select(Message).where(Message.campaign_id == campaign.id)
                ).scalars().all()
            )
            assert len(msgs) == 2
            assert all(m.status == "PENDING" for m in msgs)
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_reserved_path_skips_list_call(
        self, session_factory, sample_user, sample_caller
    ):
        """예약 경로에서는 list_by_request_id 가 호출되지 않는다."""
        from app.services.compose import dispatch_campaign

        client = MagicMock()

        async def fake_send(**kwargs):
            return SendResponse(
                request_id="RES-REQ-0002",
                request_time="2099-01-01T00:00:00",
                status_code="202",
                status_name="success",
            )

        client.send_sms = fake_send
        list_mock = AsyncMock()
        client.list_by_request_id = list_mock

        db = session_factory()
        try:
            from zoneinfo import ZoneInfo
            kst = ZoneInfo("Asia/Seoul")
            future_local = (datetime.now(kst) + timedelta(hours=3)).strftime(
                "%Y-%m-%d %H:%M"
            )

            await dispatch_campaign(
                db=db,
                ncp_client=client,
                created_by=sample_user.sub,
                caller_number=sample_caller.number,
                content="x",
                recipients=["01012345678"],
                message_type="SMS",
                reserve_time_local=future_local,
                reserve_timezone="Asia/Seoul",
            )
            list_mock.assert_not_called()
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_reserve_timezone_required_with_time(
        self, session_factory, sample_user, sample_caller
    ):
        from app.services.compose import dispatch_campaign

        db = session_factory()
        try:
            with pytest.raises(ValueError, match="reserve_timezone"):
                await dispatch_campaign(
                    db=db,
                    ncp_client=MagicMock(),
                    created_by=sample_user.sub,
                    caller_number=sample_caller.number,
                    content="x",
                    recipients=["01011112222"],
                    message_type="SMS",
                    reserve_time_local="2099-06-15 14:30",
                    reserve_timezone=None,
                )
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_reserve_all_chunks_fail_becomes_reserve_failed(
        self, session_factory, sample_user, sample_caller
    ):
        """예약 등록이 전부 실패하면 state=RESERVE_FAILED."""
        from app.services.compose import dispatch_campaign

        client = MagicMock()

        async def fake_send(**kwargs):
            raise RuntimeError("NCP down")

        client.send_sms = fake_send
        client.list_by_request_id = AsyncMock()

        db = session_factory()
        try:
            from zoneinfo import ZoneInfo
            kst = ZoneInfo("Asia/Seoul")
            future_local = (datetime.now(kst) + timedelta(hours=3)).strftime(
                "%Y-%m-%d %H:%M"
            )
            campaign = await dispatch_campaign(
                db=db,
                ncp_client=client,
                created_by=sample_user.sub,
                caller_number=sample_caller.number,
                content="x",
                recipients=["01011112222"],
                message_type="SMS",
                reserve_time_local=future_local,
                reserve_timezone="Asia/Seoul",
            )
            assert campaign.state == "RESERVE_FAILED"
        finally:
            db.close()


# ── Phase B3: Poller._poll_reservations ─────────────────────────────────────


def _make_reserved_campaign(
    db, user_sub: str, caller_number: str, *, request_id: str = "RES-1",
    exec_hours_from_now: float = 2.0,
):
    """테스트 헬퍼: RESERVED 캠페인 + NcpRequest + Message 1건 생성."""
    from app.models import Campaign, Message, NcpRequest

    exec_utc = datetime.now(UTC) + timedelta(hours=exec_hours_from_now)
    campaign = Campaign(
        created_by=user_sub,
        caller_number=caller_number,
        message_type="SMS",
        content="예약 테스트",
        total_count=1,
        ok_count=0,
        fail_count=0,
        pending_count=1,
        state="RESERVED",
        created_at=datetime.now(UTC).isoformat(),
        reserve_time=exec_utc.strftime("%Y-%m-%d %H:%M"),
        reserve_timezone="Asia/Seoul",
    )
    db.add(campaign)
    db.flush()

    ncp_req = NcpRequest(
        campaign_id=campaign.id,
        chunk_index=0,
        request_id=request_id,
        request_time=datetime.now(UTC).isoformat(),
        http_status=202,
        status_code="202",
        status_name="success",
        sent_at=exec_utc.isoformat(),  # 예약 실행 시각 (UTC)
    )
    db.add(ncp_req)
    db.flush()

    msg = Message(
        campaign_id=campaign.id,
        ncp_request_id=ncp_req.id,
        to_number="01011112222",
        to_number_raw="01011112222",
        status="PENDING",
    )
    db.add(msg)
    db.commit()
    return campaign


class TestPollerReservations:
    """_poll_reservations 의 reserveStatus → campaign.state 매핑 검증."""

    def _make_client(self, reserve_status: str) -> MagicMock:
        from app.ncp.client import ReserveStatusResponse
        client = MagicMock()
        client.list_by_request_id = AsyncMock(return_value=None)

        async def fake_status(reserve_id):
            return ReserveStatusResponse(
                reserve_id=reserve_id,
                reserve_timezone="Asia/Seoul",
                reserve_time="2099-06-15 14:30",
                reserve_status=reserve_status,
            )

        client.get_reserve_status = fake_status
        return client

    def _make_poller(self, session_factory, client):
        from app.services.poller import Poller
        return Poller(
            db_factory=session_factory,
            ncp_client_factory=lambda: client,
        )

    @pytest.mark.asyncio
    async def test_ready_keeps_reserved(
        self, session_factory, sample_user, sample_caller
    ):
        """READY 상태면 RESERVED 유지."""
        db = session_factory()
        try:
            c = _make_reserved_campaign(db, sample_user.sub, sample_caller.number)
            cid = c.id
        finally:
            db.close()

        client = self._make_client("READY")
        poller = self._make_poller(session_factory, client)
        await poller.run_once()

        verify = session_factory()
        try:
            from app.models import Campaign
            assert verify.get(Campaign, cid).state == "RESERVED"
        finally:
            verify.close()

    @pytest.mark.asyncio
    async def test_done_transitions_to_dispatching(
        self, session_factory, sample_user, sample_caller
    ):
        """DONE → DISPATCHING (정상 폴링 루프로 이관)."""
        db = session_factory()
        try:
            c = _make_reserved_campaign(db, sample_user.sub, sample_caller.number)
            cid = c.id
        finally:
            db.close()

        client = self._make_client("DONE")
        poller = self._make_poller(session_factory, client)
        await poller.run_once()

        verify = session_factory()
        try:
            from app.models import Campaign
            assert verify.get(Campaign, cid).state == "DISPATCHING"
        finally:
            verify.close()

    @pytest.mark.asyncio
    async def test_processing_transitions_to_dispatching(
        self, session_factory, sample_user, sample_caller
    ):
        """PROCESSING 역시 DISPATCHING 로 전환."""
        db = session_factory()
        try:
            c = _make_reserved_campaign(db, sample_user.sub, sample_caller.number)
            cid = c.id
        finally:
            db.close()

        client = self._make_client("PROCESSING")
        poller = self._make_poller(session_factory, client)
        await poller.run_once()

        verify = session_factory()
        try:
            from app.models import Campaign
            assert verify.get(Campaign, cid).state == "DISPATCHING"
        finally:
            verify.close()

    @pytest.mark.asyncio
    async def test_canceled_transitions_to_reserve_canceled(
        self, session_factory, sample_user, sample_caller
    ):
        db = session_factory()
        try:
            c = _make_reserved_campaign(db, sample_user.sub, sample_caller.number)
            cid = c.id
        finally:
            db.close()

        client = self._make_client("CANCELED")
        poller = self._make_poller(session_factory, client)
        await poller.run_once()

        verify = session_factory()
        try:
            from app.models import Campaign
            assert verify.get(Campaign, cid).state == "RESERVE_CANCELED"
        finally:
            verify.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", ["FAIL", "STALE", "SKIP"])
    async def test_failed_states_transition_to_reserve_failed(
        self, session_factory, sample_user, sample_caller, status
    ):
        db = session_factory()
        try:
            c = _make_reserved_campaign(db, sample_user.sub, sample_caller.number)
            cid = c.id
        finally:
            db.close()

        client = self._make_client(status)
        poller = self._make_poller(session_factory, client)
        await poller.run_once()

        verify = session_factory()
        try:
            from app.models import Campaign
            assert verify.get(Campaign, cid).state == "RESERVE_FAILED"
        finally:
            verify.close()

    @pytest.mark.asyncio
    async def test_normal_poll_skips_reserved_campaigns(
        self, session_factory, sample_user, sample_caller
    ):
        """RESERVED 캠페인의 messages 는 정상 폴링 루프(list_by_request_id)가 건들지 않는다."""
        db = session_factory()
        try:
            c = _make_reserved_campaign(db, sample_user.sub, sample_caller.number)
            cid = c.id
        finally:
            db.close()

        # READY 유지 → normal poll 에서 list_by_request_id 가 호출되지 않아야 함
        client = self._make_client("READY")
        list_mock = AsyncMock()
        client.list_by_request_id = list_mock

        poller = self._make_poller(session_factory, client)
        await poller.run_once()

        list_mock.assert_not_called()

        verify = session_factory()
        try:
            from app.models import Campaign
            assert verify.get(Campaign, cid).state == "RESERVED"
        finally:
            verify.close()
