"""Phase C: MMS + 첨부 파일 업로드 테스트.

- image.py: 전처리 단위 테스트 (포맷 변환, 리사이즈, 품질 압축)
- NCPClient.upload_attachment: HTTP body/응답 파싱 검증
- NCPClient.send_sms with file_ids: MMS body에 files 필드 포함
- dispatch_campaign MMS 경로: attachment 검증, campaign_id 연결
"""
from __future__ import annotations

import io
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from PIL import Image

from app.ncp.client import NCPClient, SendResponse, UploadFileResponse
from app.services.image import (
    NCP_MMS_MAX_BYTES,
    NCP_MMS_MAX_HEIGHT,
    NCP_MMS_MAX_WIDTH,
    ImageProcessingError,
    preprocess_mms_image,
)


# ── image.preprocess_mms_image ──────────────────────────────────────────────


def _png_bytes(size: tuple[int, int], color, mode: str = "RGB") -> bytes:
    img = Image.new(mode, size, color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _jpeg_bytes(size: tuple[int, int], color, quality: int = 95) -> bytes:
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


class TestImagePreprocessing:
    def test_small_jpeg_passes_through(self):
        raw = _jpeg_bytes((100, 100), (200, 100, 50))
        out, w, h = preprocess_mms_image(raw)
        assert w == 100 and h == 100
        assert out[:3] == b"\xff\xd8\xff"  # JPEG magic
        assert len(out) <= NCP_MMS_MAX_BYTES

    def test_png_converted_to_jpeg(self):
        raw = _png_bytes((200, 150), (255, 0, 0))
        out, w, h = preprocess_mms_image(raw)
        assert out[:3] == b"\xff\xd8\xff"
        assert (w, h) == (200, 150)

    def test_rgba_alpha_flattened_to_white_background(self):
        """RGBA 이미지가 그대로 RGB로 변환되면 알파가 검정으로 떨어진다.
        흰 배경에 합성되어야 시각적으로 자연스럽다."""
        # 완전 투명 픽셀로 200x200 → 흰 배경에 합성되면 결과는 거의 흰색
        img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        out, _, _ = preprocess_mms_image(buf.getvalue())

        result = Image.open(io.BytesIO(out))
        assert result.mode == "RGB"
        # 좌상단 픽셀이 흰색 근처여야 함 (JPEG 압축 손실 감안)
        r, g, b = result.getpixel((0, 0))
        assert r > 240 and g > 240 and b > 240

    def test_large_image_is_downscaled(self):
        raw = _jpeg_bytes((3000, 2000), (10, 50, 200))
        _, w, h = preprocess_mms_image(raw)
        assert w <= NCP_MMS_MAX_WIDTH
        assert h <= NCP_MMS_MAX_HEIGHT
        # 종횡비 유지 검증 (3:2)
        assert abs((w / h) - (3000 / 2000)) < 0.01

    def test_size_under_limit(self):
        """1500x1440 단색 이미지는 충분히 300KB 이내에 들어간다."""
        raw = _jpeg_bytes((1500, 1440), (128, 128, 128))
        out, _, _ = preprocess_mms_image(raw)
        assert len(out) <= NCP_MMS_MAX_BYTES

    def test_invalid_input_raises(self):
        with pytest.raises(ImageProcessingError):
            preprocess_mms_image(b"not an image")

    def test_empty_input_raises(self):
        with pytest.raises(ImageProcessingError):
            preprocess_mms_image(b"")


# ── NCPClient.upload_attachment / send_sms with file_ids ────────────────────


class TestNCPClientMMS:
    @pytest.mark.asyncio
    async def test_upload_attachment_base64_body(self, monkeypatch):
        client = NCPClient("ak", "sk", "svc-1")
        monkeypatch.setattr(
            "app.ncp.client.make_headers",
            lambda *a, **k: {"x-ncp-apigw-timestamp": "0"},
        )
        captured: dict = {}

        async def fake_post(url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            return httpx.Response(
                200,
                json={
                    "fileId": "FILE-001",
                    "fileName": json["fileName"],
                    "fileSize": 1024,
                    "createTime": "2099-01-01T00:00:00",
                    "expireTime": "2099-01-07T00:00:00",
                },
            )

        monkeypatch.setattr(client._client, "post", fake_post)

        resp = await client.upload_attachment("image.jpg", b"\xff\xd8\xff" + b"\x00" * 100)
        assert isinstance(resp, UploadFileResponse)
        assert resp.file_id == "FILE-001"
        assert resp.expire_time == "2099-01-07T00:00:00"
        # body 에 fileBody (base64) 가 들어있어야 함
        assert "fileBody" in captured["json"]
        import base64

        decoded = base64.b64decode(captured["json"]["fileBody"])
        assert decoded == b"\xff\xd8\xff" + b"\x00" * 100
        assert "/files" in captured["url"]
        await client.aclose()

    @pytest.mark.asyncio
    async def test_send_sms_mms_with_file_ids(self, monkeypatch):
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
                    "requestId": "REQ-MMS-001",
                    "requestTime": "2099-01-01T00:00:00",
                    "statusCode": "202",
                    "statusName": "success",
                },
            )

        monkeypatch.setattr(client._client, "post", fake_post)
        resp = await client.send_sms(
            from_number="0212345678",
            content="MMS 테스트",
            to_numbers=["01012345678"],
            message_type="MMS",
            subject="제목",
            file_ids=["FILE-001"],
        )
        assert isinstance(resp, SendResponse)
        assert captured["json"]["type"] == "MMS"
        assert captured["json"]["files"] == [{"fileId": "FILE-001"}]
        assert captured["json"]["subject"] == "제목"
        await client.aclose()

    @pytest.mark.asyncio
    async def test_file_ids_rejected_for_non_mms(self):
        client = NCPClient("ak", "sk", "svc-1")
        with pytest.raises(ValueError, match="MMS"):
            await client.send_sms(
                from_number="0212345678",
                content="x",
                to_numbers=["01012345678"],
                message_type="SMS",
                file_ids=["FILE-001"],
            )
        await client.aclose()


# ── dispatch_campaign MMS 경로 ───────────────────────────────────────────────


def _make_attachment(db, user_sub: str, *, ncp_file_id: str = "FILE-001") -> int:
    """테스트 헬퍼: 업로드 완료 상태의 Attachment 1건 생성."""
    from app.models import Attachment

    att = Attachment(
        campaign_id=None,
        ncp_file_id=ncp_file_id,
        original_filename="test.jpg",
        stored_filename="aaa.jpg",
        content_blob=b"\xff\xd8\xff" + b"\x00" * 100,
        file_size_bytes=103,
        width=300,
        height=200,
        uploaded_by=user_sub,
        uploaded_at=datetime.now(UTC).isoformat(),
        ncp_expires_at=None,
    )
    db.add(att)
    db.commit()
    return att.id


class TestDispatchMMS:
    @pytest.mark.asyncio
    async def test_mms_dispatch_links_attachment(
        self, session_factory, sample_user, sample_caller
    ):
        from app.models import Attachment
        from app.services.compose import dispatch_campaign

        db = session_factory()
        try:
            att_id = _make_attachment(db, sample_user.sub)
        finally:
            db.close()

        recorded_file_ids: list[list[str] | None] = []

        async def fake_send(**kwargs):
            recorded_file_ids.append(kwargs.get("file_ids"))
            return SendResponse(
                request_id="REQ-MMS-1",
                request_time="2099-01-01T00:00:00",
                status_code="202",
                status_name="success",
            )

        client = MagicMock()
        client.send_sms = fake_send
        # NCP가 즉시 list_by_request_id 결과 반환
        from app.ncp.client import ListResponse
        client.list_by_request_id = AsyncMock(
            return_value=ListResponse(
                request_id="REQ-MMS-1",
                status_code="200",
                status_name="success",
                messages=[],
            )
        )

        db = session_factory()
        try:
            campaign = await dispatch_campaign(
                db=db,
                ncp_client=client,
                created_by=sample_user.sub,
                caller_number=sample_caller.number,
                content="MMS 본문",
                recipients=["01011112222"],
                message_type="MMS",
                subject="MMS 제목",
                attachment_id=att_id,
            )
            assert campaign.message_type == "MMS"

            # attachment 가 campaign 에 연결되어야 함
            att = db.get(Attachment, att_id)
            assert att.campaign_id == campaign.id
        finally:
            db.close()

        # NCP send_sms 에 file_ids 가 전달되었는지 확인
        assert recorded_file_ids[0] == ["FILE-001"]

    @pytest.mark.asyncio
    async def test_mms_without_attachment_rejected(
        self, session_factory, sample_user, sample_caller
    ):
        from app.services.compose import dispatch_campaign

        db = session_factory()
        try:
            with pytest.raises(ValueError, match="첨부 파일이 필요"):
                await dispatch_campaign(
                    db=db,
                    ncp_client=MagicMock(),
                    created_by=sample_user.sub,
                    caller_number=sample_caller.number,
                    content="x",
                    recipients=["01011112222"],
                    message_type="MMS",
                )
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_attachment_owned_by_other_user_rejected(
        self, session_factory, sample_user, sample_caller, db_session
    ):
        from app.models import User
        from app.services.compose import dispatch_campaign

        # 다른 사용자가 올린 첨부
        other_user = User(
            sub="other-sub",
            email="other@example.com",
            name="다른 사용자",
            roles='["sender"]',
            created_at=datetime.now(UTC).isoformat(),
            last_login_at=datetime.now(UTC).isoformat(),
        )
        db_session.add(other_user)
        db_session.commit()

        db = session_factory()
        try:
            att_id = _make_attachment(db, "other-sub", ncp_file_id="OTHER")
        finally:
            db.close()

        db = session_factory()
        try:
            with pytest.raises(ValueError, match="권한"):
                await dispatch_campaign(
                    db=db,
                    ncp_client=MagicMock(),
                    created_by=sample_user.sub,
                    caller_number=sample_caller.number,
                    content="x",
                    recipients=["01011112222"],
                    message_type="MMS",
                    attachment_id=att_id,
                )
        finally:
            db.close()

    @pytest.mark.asyncio
    async def test_attachment_id_with_non_mms_type_rejected(
        self, session_factory, sample_user, sample_caller
    ):
        from app.services.compose import dispatch_campaign

        db = session_factory()
        try:
            att_id = _make_attachment(db, sample_user.sub, ncp_file_id="X")
        finally:
            db.close()

        db = session_factory()
        try:
            with pytest.raises(ValueError, match="MMS 메시지에만"):
                await dispatch_campaign(
                    db=db,
                    ncp_client=MagicMock(),
                    created_by=sample_user.sub,
                    caller_number=sample_caller.number,
                    content="x",
                    recipients=["01011112222"],
                    message_type="LMS",  # 일부러 LMS
                    attachment_id=att_id,
                )
        finally:
            db.close()
