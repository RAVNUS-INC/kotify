"""대화방 팀 공유 읽음 추적 테스트.

"안읽음"을 "미답(답장 안 함)"이 아니라 "마지막 고객(MO) 메시지가 팀 read_at
이후"로 판정한다. 대화방을 열면(api_mark_read) read_at 이 갱신되어 팀 전체에게
읽음 처리되고, 새 MO 가 오면 다시 안읽음이 된다.
"""
from __future__ import annotations

from sqlalchemy import func, select

from app.models import MoMessage, ThreadRead
from app.routes.threads import api_mark_read
from app.services.chat import list_threads, thread_unread

_CALLER = "0212345678"
_PHONE = "01099998888"


def _make_mo(db, *, recv_dt, mo_key, caller=_CALLER, phone=_PHONE, msg="안녕하세요"):
    """고객 수신(MO) 1건 생성 — list_threads 가 inbound 스레드로 인식."""
    db.add(MoMessage(
        mo_key=mo_key,
        mo_number=phone,
        mo_callback=caller,
        mo_type="message",
        mo_msg=msg,
        mo_recv_dt=recv_dt,
        raw_payload="{}",
        received_at=recv_dt,
    ))
    db.commit()


def _thread(db, phone=_PHONE):
    threads, _ = list_threads(db)
    return next(t for t in threads if t.phone == phone)


# ── thread_unread 헬퍼 (혼합 포맷) ────────────────────────────────────────────


def test_thread_unread_helper_iso():
    assert thread_unread("2026-05-30T14:00:00+00:00", "2026-05-30T13:00:00+00:00") is True
    assert thread_unread("2026-05-30T12:00:00+00:00", "2026-05-30T13:00:00+00:00") is False


def test_thread_unread_helper_no_read_or_no_mo():
    assert thread_unread("2026-05-30T12:00:00+00:00", None) is True   # 한 번도 안 읽음
    assert thread_unread("2026-05-30T12:00:00+00:00", "") is True
    assert thread_unread("", "2026-05-30T13:00:00+00:00") is False    # 고객 메시지 없음
    assert thread_unread(None, None) is False


def test_thread_unread_helper_mixed_format():
    # msghub 네이티브 20260530140000(KST=05:00Z) vs ISO 04:00Z → mo 가 더 최근 → 안읽음.
    # 문자열 비교였다면 '2026-..'<'202605..' 로 뒤집혔을 케이스 — epoch 비교 검증.
    assert thread_unread("20260530140000", "2026-05-30T04:00:00+00:00") is True
    assert thread_unread("20260530120000", "2026-05-30T06:00:00+00:00") is False  # 12:00KST=03:00Z<06:00Z


# ── list_threads 읽음 판정 (now 비의존: 양쪽 시각 직접 지정) ───────────────────


def test_unread_before_any_read(db_session):
    """한 번도 안 읽은 고객 메시지는 안읽음이다."""
    _make_mo(db_session, recv_dt="2026-05-30T12:00:00+00:00", mo_key="mo-a")
    assert _thread(db_session).unread is True


def test_not_unread_after_read(db_session):
    """read_at 이 마지막 MO 이후면 안읽음 아니다."""
    _make_mo(db_session, recv_dt="2026-05-30T12:00:00+00:00", mo_key="mo-b")
    db_session.add(ThreadRead(caller=_CALLER, phone=_PHONE, read_at="2026-05-30T13:00:00+00:00"))
    db_session.commit()
    assert _thread(db_session).unread is False


def test_new_mo_after_read_is_unread_again(db_session):
    """읽은 뒤 새 MO 가 오면 다시 안읽음."""
    _make_mo(db_session, recv_dt="2026-05-30T12:00:00+00:00", mo_key="mo-c1")
    db_session.add(ThreadRead(caller=_CALLER, phone=_PHONE, read_at="2026-05-30T13:00:00+00:00"))
    db_session.commit()
    _make_mo(db_session, recv_dt="2026-05-30T14:00:00+00:00", mo_key="mo-c2")  # 읽음 이후
    assert _thread(db_session).unread is True


def test_unread_clears_with_msghub_kst_recv_dt(db_session):
    """회귀: msghub moRecvDt('2026-05-30 11:36:38' = KST 11:36 = UTC 02:36)를
    UTC 03:00 에 읽으면 unread 해제돼야 한다.

    이전엔 naive 를 UTC 로 파싱해 MO 를 UTC 11:36(9h 늦게)로 계산 → read_at(UTC
    03:00)보다 항상 최신 → 읽어도 unread 유지(프로덕션 버그). KST 로 파싱하면
    MO(UTC 02:36) < read(UTC 03:00) → 읽음 처리.
    """
    _make_mo(db_session, recv_dt="2026-05-30 11:36:38", mo_key="mo-kst")  # 공백 KST
    db_session.add(ThreadRead(caller=_CALLER, phone=_PHONE, read_at="2026-05-30T03:00:00+00:00"))
    db_session.commit()
    assert _thread(db_session).unread is False


# ── api_mark_read 통합 (전체 루프) ────────────────────────────────────────────


def test_mark_read_clears_unread_and_upserts(db_session):
    """열람(mark_read) → 읽음 처리 + read_at upsert(중복 행 없음)."""
    # MO 는 과거(2026-01-01)로 둬 실행 시각과 무관하게 now > mo 보장.
    _make_mo(db_session, recv_dt="2026-01-01T00:00:00+00:00", mo_key="mo-d")
    assert _thread(db_session).unread is True

    res = api_mark_read(f"{_CALLER}:{_PHONE}", db_session)
    assert res["data"]["unread"] is False
    assert _thread(db_session).unread is False  # read_at(now) > mo(과거)

    # 재호출은 upsert — 행이 늘지 않음
    api_mark_read(f"{_CALLER}:{_PHONE}", db_session)
    count = db_session.execute(
        select(func.count()).select_from(ThreadRead)
        .where(ThreadRead.caller == _CALLER, ThreadRead.phone == _PHONE)
    ).scalar()
    assert count == 1
