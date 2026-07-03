"""대화방 병합 회귀 — 같은 고객의 발송방/회신방이 하나로 묶여야 한다.

버그: mo_callback(회신측 우리번호)이 원본 형식(하이픈 등)으로 저장돼,
campaigns.caller_number(숫자만)와 달라 스레드 키 (caller, phone) 가 갈렸다.
→ 같은 고객이 "발송방"과 "회신방" 2개로 분리.

수정: webhook 수신 시 mo_callback 을 숫자만으로 통일. 그 결과 list_threads
그룹핑에서 같은 (caller, phone) 로 병합된다.
"""
from __future__ import annotations

import asyncio

from app.models import Campaign, Message, MsghubRequest
from app.routes.webhook import receive_mo
from app.security.settings_store import SettingsStore
from app.services.chat import list_threads


def _setup_token(db):
    SettingsStore(db).set(
        "msghub.webhook_token", "wtok", is_secret=True, updated_by="test"
    )
    db.commit()


def _mo_request(body):
    from unittest.mock import AsyncMock, MagicMock

    request = MagicMock()
    request.json = AsyncMock(return_value=body)
    request.client = MagicMock()
    request.client.host = "10.0.0.1"
    return request


def _make_outbound(db, *, caller, phone, created_at="2026-06-01T00:00:00+00:00"):
    """caller 번호로 phone 에게 보낸 발송(MT) 1건. caller_number 는 숫자만."""
    c = Campaign(
        created_by="test-sub-001", caller_number=caller, message_type="short",
        content="안내드립니다", total_count=1, pending_count=0, state="DISPATCHED",
        created_at=created_at,
    )
    db.add(c)
    db.flush()
    req = MsghubRequest(campaign_id=c.id, chunk_index=0, sent_at=created_at)
    db.add(req)
    db.flush()
    db.add(Message(
        campaign_id=c.id, msghub_request_id=req.id,
        to_number=phone, to_number_raw=phone, status="DELIVERED",
    ))
    db.commit()


def test_outbound_and_reply_merge_into_one_thread(db_session, sample_user):
    """발송(caller=숫자) 후 회신(moCallback=하이픈)이 와도 대화방 1개."""
    _setup_token(db_session)
    caller_digits = "025771000"
    phone = "01012345678"

    # 1) 우리가 먼저 발송 (caller_number 는 숫자만 저장)
    _make_outbound(db_session, caller=caller_digits, phone=phone)

    # 2) 고객이 회신 — msghub 는 moCallback 을 하이픈 형식으로 보냄
    body = {"moCnt": 1, "moLst": [{
        "moKey": "r1", "moNumber": "010-1234-5678",
        "moCallback": "02-577-1000",  # 하이픈 — 정규화 안 하면 발송방과 갈림
        "moMsg": "네 확인했습니다",
    }]}
    resp = asyncio.run(receive_mo("wtok", _mo_request(body), db_session))
    assert resp.status_code == 200

    # 3) 대화방 목록 — 발송방·회신방이 하나로 병합돼야 한다.
    threads, total = list_threads(db_session)
    assert total == 1, f"대화방이 {total}개로 쪼개짐 (기대: 1개)"
    t = threads[0]
    assert t.caller == caller_digits  # 숫자만으로 통일
    assert t.phone == phone
    # 발송(MT)과 회신(MO)이 같은 방에 집계됐는지
    assert t.mt_count == 1
    assert t.mo_count == 1
    # 최신이 회신이므로 IN 방향
    assert t.last_direction == "IN"


def test_reply_callback_stored_as_digits(db_session):
    """webhook 이 mo_callback 을 숫자만으로 저장한다(원본 하이픈 제거)."""
    from sqlalchemy import select

    from app.models import MoMessage

    _setup_token(db_session)
    body = {"moCnt": 1, "moLst": [{
        "moKey": "r2", "moNumber": "010-1234-5678",
        "moCallback": "02-577-1000", "moMsg": "hi",
    }]}
    asyncio.run(receive_mo("wtok", _mo_request(body), db_session))

    mo = db_session.execute(select(MoMessage)).scalars().one()
    assert mo.mo_callback == "025771000"  # 숫자만
    assert mo.mo_number == "01012345678"


def test_rcs_bidirectional_reply_merges_by_phone(db_session, sample_user):
    """RCS 양방향 회신(mo_callback=chatbotId)도 발송방과 한 방으로 묶인다.

    RCS 양방향은 회신 payload 의 chatbotId 가 mo_callback 에 저장돼, 발신번호
    (caller_number)와 값 자체가 다르다. 정규화로는 못 합치므로 phone(고객번호)
    단위 그룹핑으로 하나의 대화방이 되어야 한다.
    """
    _setup_token(db_session)
    phone = "01012345678"
    send_number = "025771000"

    # 1) 우리가 발신번호로 발송
    _make_outbound(db_session, caller=send_number, phone=phone)

    # 2) 고객이 RCS 양방향으로 회신 — msgKey 형식 → callback=chatbotId
    body = {"rcsBiCnt": 1, "rcsBiLst": [{
        "msgKey": "rcs-1", "phone": "010-1234-5678",
        "chatbotId": "CHATBOT_0123",  # 발신번호와 완전히 다른 값
        "eventType": "message",
        "contentInfo": {"textMessage": "RCS 양방향 회신입니다"},
    }]}
    resp = asyncio.run(receive_mo("wtok", _mo_request(body), db_session))
    assert resp.status_code == 200

    # 3) chatbotId ≠ 발신번호지만, phone 이 같으니 대화방 1개.
    threads, total = list_threads(db_session)
    assert total == 1, f"RCS 양방향 회신이 별도 방으로 분리됨 ({total}개)"
    t = threads[0]
    assert t.phone == phone
    assert t.mt_count == 1  # 발송
    assert t.mo_count == 1  # RCS 회신
    assert t.last_direction == "IN"


# ── _norm_to_number: 발송 to_number 정규화 (하이픈 재유입 방지) ───────────────


def test_norm_to_number_strips_hyphens():
    """하이픈/공백 입력을 숫자만으로. to_number 그룹핑 키 통일."""
    from app.services.compose import _norm_to_number

    assert _norm_to_number("010-7171-2463") == "01071712463"
    assert _norm_to_number("010 7171 2463") == "01071712463"
    assert _norm_to_number("01071712463") == "01071712463"  # 멱등
    # 휴대폰 패턴 아니어도 숫자만 fallback (normalize_phone None → 숫자추출)
    assert _norm_to_number("02-577-1000") == "025771000"


def test_hyphen_outbound_merges_with_reply(db_session, sample_user):
    """하이픈으로 저장된 과거 발송도, to_number 를 숫자로 정리하면 회신과 병합.

    회귀 재현: 발송 to_number='010-7171-2463'(하이픈) + 회신 mo_number=
    '01071712463'(숫자) → 정리 전엔 대화방 2개. list_threads 는 저장값 기준이라,
    발송측이 숫자로 저장돼야(=_norm_to_number 적용 또는 0016 마이그레이션) 병합된다.
    여기서는 발송을 정규화된 값으로 저장해 병합을 확인한다(수정 후 동작).
    """
    _setup_token(db_session)
    phone = "01071712463"
    # 수정 후 저장 경로가 보장하는 상태: to_number 는 숫자만
    _make_outbound(db_session, caller="025771000", phone=phone)

    body = {"moCnt": 1, "moLst": [{
        "moKey": "h1", "moNumber": "010-7171-2463",  # 회신은 하이픈으로 와도
        "moCallback": "025771000", "moMsg": "확인했습니다",
    }]}
    asyncio.run(receive_mo("wtok", _mo_request(body), db_session))

    threads, total = list_threads(db_session)
    assert total == 1, f"하이픈 발송이 회신과 분리됨 ({total}개)"
    assert threads[0].mt_count == 1
    assert threads[0].mo_count == 1
