"""최신 U+ 가이드의 환경·예약·모니터링 계약 회귀 테스트."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import cast
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from starlette.datastructures import UploadFile

from app.models import Attachment
from app.msghub.client import MsghubClient
from app.msghub.schemas import UploadFileResponse
from app.routes.campaigns import upload_attachment
from app.routes.setup import TestMsghubBody as _TestMsghubBody
from app.services.compose import parse_reserve_time


def test_only_official_msghub_environments_are_accepted():
    with pytest.raises(ValidationError):
        _TestMsghubBody(msghubApiKey="key", msghubApiPwd="pwd", msghubEnv="sandbox")
    with pytest.raises(ValueError, match="production.*qa"):
        MsghubClient(cast(object, "sandbox"), "key", "pwd")


def test_reservation_cannot_exceed_thirty_days():
    future_kst = (datetime.now(UTC) + timedelta(days=31, hours=9)).strftime("%Y-%m-%d %H:%M")
    with pytest.raises(ValueError, match="최대 30일"):
        parse_reserve_time(future_kst)


async def test_health_check_uses_official_endpoint(monkeypatch):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"code": "10000", "message": "성공"})

    client = MsghubClient("qa", "key", "pwd")
    await client.aclose()
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(client._token_mgr, "get_token", AsyncMock(return_value="token"))
    try:
        assert await client.health_check() is True
    finally:
        await client.aclose()
    [request] = requests
    assert request.method == "PUT"
    assert request.url.path == "/client/v1/healthCheck"
    assert request.headers["Authorization"] == "Bearer token"


async def test_attachment_is_registered_for_mms_and_rcs(
    db_session, sample_user, monkeypatch,
):
    """한 원본을 채널별 endpoint에 등록하고 두 fileId를 따로 보관한다."""
    class Client:
        calls: list[str] = []

        async def upload_file(self, channel, file_id, file_bytes, content_type):
            self.calls.append(channel)
            return UploadFileResponse(
                file_id=f"{channel}-id", file_exp_dt="2026-12-31T23:59:59", ch=channel,
            )

    client = Client()
    monkeypatch.setattr("app.main.get_msghub_client", lambda: client)
    monkeypatch.setattr(
        "app.routes.campaigns.preprocess_mms_image", lambda raw: (b"jpeg", 100, 100),
    )
    response = await upload_attachment(
        file=UploadFile(filename="notice.png", file=BytesIO(b"raw")),
        user=sample_user,
        db=db_session,
    )
    attachment = db_session.get(Attachment, response["data"]["attachmentId"])
    assert client.calls == ["mms", "rcs"]
    assert attachment.msghub_file_id == "mms-id"
    assert attachment.msghub_rcs_file_id == "rcs-id"
