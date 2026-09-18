"""발신 메타는 메시지를 만든 캠페인의 실제 작성자를 표시한다."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db import Base
from app.models import Campaign, Message, MoMessage, MsghubRequest, User
from app.routes.threads import MessageCreateBody, api_get_thread, api_post_message
from app.services.chat import get_thread

_CALLER = "0212345678"
_PHONE = "01099998888"
_NOW = "2026-09-01T00:00:00+00:00"


def _send(db, author, *, rcs=False, phones=(_PHONE,)):
    campaign = Campaign(
        created_by=author, caller_number=_CALLER, message_type="short",
        content="안내드립니다", total_count=len(phones), state="DISPATCHED",
        created_at=_NOW, rcs_messagebase_id="RPCSAXX001" if rcs else None,
    )
    db.add(campaign)
    db.flush()
    req = MsghubRequest(campaign_id=campaign.id, chunk_index=0, sent_at=_NOW)
    db.add(req)
    db.flush()
    for i, phone in enumerate(phones):
        db.add(Message(
            campaign_id=campaign.id, msghub_request_id=req.id,
            to_number=phone, to_number_raw=phone, status="REG",
            cli_key=f"c{campaign.id}-0-{i}", result_code="10000",
        ))
    db.commit()


@pytest.mark.parametrize("rcs", [False, True], ids=["sms", "rcs-chat"])
def test_outbound_uses_campaign_author_and_inbound_omits_name(db_session, sample_user, rcs):
    sample_user.display_name = "  가상 담당자  "
    db_session.commit()
    _send(db_session, sample_user.sub, rcs=rcs)
    db_session.add(MoMessage(
        mo_key="inbound-1", mo_number=_PHONE, mo_callback=_CALLER,
        mo_msg="확인했습니다", raw_payload="{}", received_at=_NOW,
    ))
    db_session.commit()

    messages = api_get_thread(f"{_CALLER}:{_PHONE}", db=db_session)["data"]["messages"]
    outbound = next(m for m in messages if m["side"] == "us")
    assert outbound["senderName"] == "가상 담당자"
    assert outbound["kind"] == ("rcs" if rcs else "sms")
    assert outbound["status"] == "pending"
    assert "senderName" not in next(m for m in messages if m["side"] == "them")


def test_bulk_messages_retain_their_campaign_author_without_per_message_queries(
    db_session, db_engine, sample_user,
):
    other = User(
        sub="bulk-author", name="단체 작성자", display_name="단체 담당자",
        email="bulk@example.invalid", roles='["sender"]', created_at=_NOW, last_login_at=_NOW,
    )
    db_session.add(other)
    db_session.commit()
    _send(db_session, other.sub, phones=(_PHONE, "01011112222", "01033334444"))
    for _ in range(4):
        _send(db_session, sample_user.sub)
    statements = []

    def capture(_connection, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(db_engine, "before_cursor_execute", capture)
    try:
        messages = get_thread(db_session, _CALLER, _PHONE)
    finally:
        event.remove(db_engine, "before_cursor_execute", capture)

    assert [m.sender_name for m in messages] == ["단체 담당자", *(["테스트 사용자"] * 4)]
    assert len(statements) == 2  # MT + MO. 작성자 수에 비례하는 조회 없음.


@pytest.mark.parametrize(
    ("display_name", "name", "expected"),
    [
        (None, "  이전 사용자 이름 ", "이전 사용자 이름"),
        ("  ", "  ", "알 수 없음"),
        ("test@example.com", "실제 이름", "실제 이름"),
        (None, "test@example.com", "알 수 없음"),
        (None, "test-sub-001", "알 수 없음"),
    ],
)
def test_sender_fallback_never_uses_email_or_subject(
    db_session, sample_user, display_name, name, expected,
):
    sample_user.display_name = display_name
    sample_user.name = name
    db_session.commit()
    _send(db_session, sample_user.sub)
    message = get_thread(db_session, _CALLER, _PHONE)[0]
    assert message.sender_name == expected


def test_missing_legacy_author_preserves_message_with_unknown_name():
    # 외래키 검증 전 생성된 과거 데이터에 사용자가 없는 경우를 별도 임시 DB로 검증.
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            _send(db, "missing-legacy-user")
            messages = get_thread(db, _CALLER, _PHONE)
            assert len(messages) == 1
            assert messages[0].sender_name == "알 수 없음"
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_post_message_returns_current_author_name(db_session, sample_user, monkeypatch):
    sample_user.display_name = "답장 담당자"

    async def fake_send(**kwargs):
        assert kwargs["user"].sub == sample_user.sub
        return SimpleNamespace(id=42)

    monkeypatch.setattr("app.main.get_msghub_client", lambda: object())
    monkeypatch.setattr("app.services.chat.send_reply", fake_send)
    response = await api_post_message(
        f"{_CALLER}:{_PHONE}", MessageCreateBody(text="안내", sendChannel="sms"),
        user=sample_user, db=db_session,
    )
    assert response["data"]["message"]["senderName"] == "답장 담당자"
