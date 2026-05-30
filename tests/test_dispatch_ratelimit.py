"""29002(CPS 초과) 레이트리밋 재시도 경로 — 중복 발송 없음 (C3 검증).

29002 는 요청 단위 CPS(Calls Per Second) 레이트리밋으로 HTTP 400 최상위 code 다.
_raise_for_response 가 body["code"](요청 결과)만 보고 MsghubRateLimited 를 raise 하며,
요청 전체가 ingress 에서 거부돼 접수된 수신자가 0이다(수신자 단위 부분수락은 HTTP 200 +
data[].code 경로 — 별개). 따라서 30초 후 -fb 직접 SMS 재시도는 수신자당 메시지를 정확히
1건만 만든다(중복 없음). 공식 스펙: doc.msghub.uplus.co.kr 결과코드 29002.
"""
from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.models import Message
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import MsghubRateLimited, SendResponse, SendResultItem
from app.services.compose import dispatch_campaign


class _RateLimitThenSmsClient:
    """첫 send_rcs 는 29002(MsghubRateLimited) → 재시도 send_sms 성공."""

    def __init__(self):
        self.rcs_calls = 0
        self.sms_calls = 0

    async def send_rcs(self, **kwargs):
        self.rcs_calls += 1
        raise MsghubRateLimited("[29002] CPS 초과", code="29002", status_code=400)

    async def send_sms(self, *, callback, msg, recv_list):
        self.sms_calls += 1
        items = [
            SendResultItem(
                cli_key=r.cli_key, msg_key=f"mk-{r.cli_key}",
                phone=r.phone, code=SUCCESS_CODE, message="성공",
            )
            for r in recv_list
        ]
        return SendResponse(code="10000", message="OK", items=items)


@pytest.mark.asyncio
async def test_rate_limited_retry_no_duplicate(db_session, sample_user, sample_caller, monkeypatch):
    """29002 → 직접 SMS 재시도. 수신자당 메시지 정확히 1건(중복 없음)."""
    async def _instant_sleep(_seconds):
        return None
    # 30초 백오프를 즉시 통과 (테스트 속도)
    monkeypatch.setattr("app.services.compose.asyncio.sleep", _instant_sleep)

    recipients = ["01000000001", "01000000002", "01000000003"]
    client = _RateLimitThenSmsClient()

    campaign = await dispatch_campaign(
        db=db_session,
        msghub_client=client,
        created_by=sample_user.sub,
        caller_number=sample_caller.number,
        content="안내 메시지",
        recipients=recipients,
        message_type="SMS",
    )

    # 첫 RCS 1회 → 29002, 재시도 SMS 1회 (재시도 1회만)
    assert client.rcs_calls == 1
    assert client.sms_calls == 1

    # 수신자당 메시지 정확히 1건 — 중복 발송 없음 (29002 는 전체거부라 접수분 0)
    total = db_session.execute(
        select(func.count()).select_from(Message).where(Message.campaign_id == campaign.id)
    ).scalar()
    assert total == len(recipients)

    # 재시도 경로는 원본 키 충돌 회피용 -fb cliKey 사용
    cli_keys = db_session.execute(
        select(Message.cli_key).where(Message.campaign_id == campaign.id)
    ).scalars().all()
    assert all(k.endswith("-fb") for k in cli_keys)

    # 재시도 SMS 전건 접수 성공 → 실패 0, 전건 pending(배달 리포트 대기)
    assert campaign.fail_count == 0
    assert campaign.pending_count == len(recipients)
