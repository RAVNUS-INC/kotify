"""대화방 목록(list_threads) — 포맷이 섞인 시각을 실제 시각으로 비교하고, 쿼리 수가 번호 수와 무관하다.

시각 저장 포맷(2026-09-15 확인): msghub 리포트 rptDt·MO moRecvDt 는 오프셋 없는 KST
'yyyy-MM-ddTHH:mm:ss'(공식 문서·운영 캡처 tests/test_msghub_schemas.py)이고, 값이 비면 우리가 기록한
UTC ISO(report._now_iso()·received_at, 마이크로초 포함)가 들어간다. 파서가 받는 공백 구분
moRecvDt(구 문서)와 14자리 yyyyMMddHHmmss 도 함께 쓴다. 문자열 대소로 비교하면 KST 벽시계와 UTC
가 9시간 어긋나고, 같은 날짜면 공백이 'T' 보다, '2026-..' 이 '2026..' 보다 늘 작다 — 아래 시각은
문자열 순서와 실제 순서가 반대가 되게 골랐다.
"""
from __future__ import annotations

import random
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, event, literal, select
from sqlalchemy.orm import Session

from app.models import Campaign, Message, MoMessage, MsghubRequest, ThreadRead
from app.routes.threads import api_list_threads
from app.services import chat
from app.services.chat import ChatThread, _ts_rank, _ts_shape, list_threads
from app.util.time import KST

_CALLERS = ["0212345678", "025771000", "CHATBOT_0123"]
_PHONE = "01012345678"
_BASE = datetime(2026, 6, 1, 3, 0, tzinfo=UTC)


# ── 데이터 헬퍼 ───────────────────────────────────────────────────────────────


def _add_mt(db, *, caller, phone, content, complete_time=None, report_dt=None):
    """caller 로 phone 에게 보낸 발송 1건. 캠페인마다 본문이 달라 잘못 고른 본문이 드러난다."""
    c = Campaign(
        created_by="test-sub-001", caller_number=caller, message_type="short",
        content=content, total_count=1, state="DONE",
        created_at="2026-06-01T00:00:00+00:00",
    )
    db.add(c)
    db.flush()
    req = MsghubRequest(campaign_id=c.id, chunk_index=0, sent_at="2026-06-01T00:00:00+00:00")
    db.add(req)
    db.flush()
    db.add(Message(
        campaign_id=c.id, msghub_request_id=req.id, to_number=phone, to_number_raw=phone,
        status="DONE" if complete_time else "PENDING",
        complete_time=complete_time, report_dt=report_dt,
    ))
    db.flush()  # id 가 추가한 순서대로 — 시각 동률은 id 로 풀린다


def _add_mo(db, *, key, caller, phone, body, recv_dt, received_at="2026-06-01T00:00:00+00:00"):
    """moRecvDt 가 없던 회신은 recv_dt=None — 목록은 received_at(UTC) 으로 대신 비교한다."""
    db.add(MoMessage(
        mo_key=key, mo_number=phone, mo_callback=caller, mo_type="message", mo_msg=body,
        mo_recv_dt=recv_dt, raw_payload="{}", received_at=received_at,
    ))
    db.flush()


def _only_thread(db: Session) -> ChatThread:
    threads, total = list_threads(db, limit=200)
    assert total == len(threads) == 1
    return threads[0]


# ── 방향·마지막 시각·미리보기 ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("mt", "mo", "expected"),
    [
        pytest.param(
            {"complete_time": "2026-06-01T12:00:00"},                               # KST 12:00
            {"recv_dt": None, "received_at": "2026-06-01T03:10:00.123456+00:00"},  # KST 12:10
            ("IN", "2026-06-01T03:10:00.123456+00:00", "회신"),
            id="utc-received_at-reply-after-report",
        ),
        pytest.param(
            {"complete_time": "2026-06-01T12:00:00"},  # KST 12:00
            {"recv_dt": "2026-06-01 12:10:00"},        # KST 12:10, 공백 구분
            ("IN", "2026-06-01 12:10:00", "회신"),
            id="space-separated-reply-after-report",
        ),
        pytest.param(
            {"complete_time": "20260601120000"},  # KST 12:00, 14자리
            {"recv_dt": "2026-06-01T12:10:00"},   # KST 12:10
            ("IN", "2026-06-01T12:10:00", "회신"),
            id="iso-reply-after-native-report",
        ),
        pytest.param(
            {"report_dt": "2026-06-01T03:20:00.500000+00:00"},  # KST 12:20, 개별 조회 결과는 report_dt 만
            {"recv_dt": "2026-06-01T12:10:00"},                 # KST 12:10
            ("OUT", "2026-06-01T03:20:00.500000+00:00", "발송"),
            id="utc-report-after-reply",
        ),
        pytest.param(
            {"complete_time": "2026-06-01T03:20:00+00:00"},  # KST 12:20
            {"recv_dt": "20260601121000"},                   # KST 12:10
            ("OUT", "2026-06-01T03:20:00+00:00", "발송"),
            id="native-reply-before-iso-report",
        ),
    ],
)
def test_direction_and_preview_follow_real_time(db_session, sample_user, mt, mo, expected):
    """실제로 더 늦은 쪽이 마지막 활동 — 고객 회신이 늦으면 IN 이고 미리보기·시각도 회신 것이다.

    예전엔 문자열로 비교해 늦게 온 회신이 우리 발송에 가려 목록 미리보기·순서가 발송 기준이었다.
    """
    _add_mt(db_session, caller=_CALLERS[0], phone=_PHONE, content="발송", **mt)
    _add_mo(db_session, key="mo", caller=_CALLERS[0], phone=_PHONE, body="회신", **mo)
    db_session.commit()

    t = _only_thread(db_session)

    assert (t.last_direction, t.last_timestamp, t.last_body) == expected


@pytest.mark.parametrize("later", [0, 1], ids=["first-caller-later", "second-caller-later"])
def test_latest_send_across_callers(db_session, sample_user, later):
    """발신번호가 여럿이면 그중 가장 늦은 발송이 기준 — 발신번호별 집계 행의 순서와 무관하다.

    예전엔 발신번호별 행을 차례로 덮어써 마지막 행이 이겼다. 더 이른 발송 행이 마지막에 오면
    그보다 늦은 회신이 마지막 활동으로 보였다.
    """
    times = ["2026-06-01T12:00:00", "2026-06-01T09:00:00"]
    if later:
        times.reverse()
    _add_mt(db_session, caller=_CALLERS[0], phone=_PHONE, content="0번 발송", complete_time=times[0])
    _add_mt(db_session, caller=_CALLERS[1], phone=_PHONE, content="1번 발송", complete_time=times[1])
    _add_mo(db_session, key="mo", caller=_CALLERS[0], phone=_PHONE, body="회신",
            recv_dt="2026-06-01T10:00:00")
    db_session.commit()

    t = _only_thread(db_session)

    assert (t.last_direction, t.last_timestamp, t.last_body) == ("OUT", "2026-06-01T12:00:00", f"{later}번 발송")
    assert t.caller == _CALLERS[later]
    assert (t.mt_count, t.mo_count) == (2, 1)


def test_latest_reply_across_callbacks(db_session, sample_user):
    """회신 경로(mo_callback)가 여럿이면 실제로 가장 늦은 회신 — 대표 caller 도 그 경로다."""
    _add_mt(db_session, caller=_CALLERS[0], phone=_PHONE, content="발송", complete_time="2026-06-01T11:00:00")
    _add_mo(db_session, key="sms", caller=_CALLERS[0], phone=_PHONE, body="문자 회신",
            recv_dt="2026-06-01T12:10:00")  # KST 12:10
    _add_mo(db_session, key="rcs", caller=_CALLERS[2], phone=_PHONE, body="RCS 회신",
            recv_dt=None, received_at="2026-06-01T03:20:00.654321+00:00")  # KST 12:20
    db_session.commit()

    t = _only_thread(db_session)

    assert (t.last_direction, t.last_timestamp, t.last_body) == (
        "IN", "2026-06-01T03:20:00.654321+00:00", "RCS 회신",
    )
    assert t.caller == _CALLERS[2]
    assert (t.mt_count, t.mo_count) == (1, 2)


def test_representative_caller_is_latest_activity(db_session, sample_user):
    """대표 caller(답장 발송·읽음 처리에 쓰임)는 실제로 가장 늦은 활동의 발신번호다."""
    _add_mo(db_session, key="rcs", caller=_CALLERS[2], phone=_PHONE, body="RCS 회신",
            recv_dt="2026-06-01T12:00:00")  # KST 12:00
    _add_mt(db_session, caller=_CALLERS[0], phone=_PHONE, content="문자 발송",
            report_dt="2026-06-01T03:30:00.500000+00:00")  # KST 12:30
    db_session.commit()

    t = _only_thread(db_session)

    assert (t.caller, t.last_direction, t.last_body) == (_CALLERS[0], "OUT", "문자 발송")


@pytest.mark.parametrize("direction", ["OUT", "IN"])
@pytest.mark.parametrize(
    ("stamps", "latest"),
    [
        pytest.param(
            [
                "2026-06-01T12:00:00",               # KST 12:00
                "2026-06-01 12:05:00",               # KST 12:05
                "2026-06-01T03:10:00.250000+00:00",  # KST 12:10 — 가장 늦다
                "20260601113000",                    # KST 11:30 — 문자열로는 가장 크다
            ],
            2,
            id="listed-shapes",
        ),
        pytest.param(
            [
                "2026-06-01T12:00:00",      # KST 12:00
                "2026-06-01T12:50:00.123",  # KST 12:50 — 목록에 없는 모양, 아래보다 문자열이 크다
                "2026-06-01T04:00:00Z",     # KST 13:00 — 목록에 없는 모양, 가장 늦다
                "20260601113000",           # KST 11:30
            ],
            2,
            id="unlisted-shapes",
        ),
    ],
)
def test_latest_within_one_caller_across_formats(db_session, sample_user, direction, stamps, latest):
    """같은 (발신번호, 번호) 안에서도 실제로 가장 늦은 행 — SQL 문자열 max 가 아니다.

    리포트·수신 시각이 비어 대체된 UTC 값도, 모양 목록에 없는 표기도 각자 후보가 된다.
    """
    for n, stamp in enumerate(stamps):
        if direction == "OUT":
            _add_mt(db_session, caller=_CALLERS[0], phone=_PHONE, content=f"발송 {n}", complete_time=stamp)
        elif stamp.endswith("+00:00"):  # moRecvDt 가 비어 received_at 으로 대체된 회신
            _add_mo(db_session, key=f"mo-{n}", caller=_CALLERS[2], phone=_PHONE, body=f"회신 {n}",
                    recv_dt=None, received_at=stamp)
        else:
            _add_mo(db_session, key=f"mo-{n}", caller=_CALLERS[2], phone=_PHONE, body=f"회신 {n}",
                    recv_dt=stamp)
    db_session.commit()

    t = _only_thread(db_session)

    body = f"발송 {latest}" if direction == "OUT" else f"회신 {latest}"
    assert (t.last_direction, t.last_timestamp, t.last_body) == (direction, stamps[latest], body)
    assert t.mt_count + t.mo_count == len(stamps)


def test_same_instant_prefers_earlier_row(db_session, sample_user):
    """같은 순간이면 먼저 저장된(id 가 작은) 행의 본문이다 — 표기가 달라도.

    발송과 회신이 같은 순간이면 미리보기는 발송(OUT)이고 대표 caller 는 회신 경로다 — 답장이 그
    회신의 replyId 세션(_fresh_reply_id 는 mo_callback 으로 찾는다)을 쓸 수 있게.
    """
    phone_mt, phone_mo, phone_both = "01000000001", "01000000002", "01000000003"
    _add_mt(db_session, caller=_CALLERS[0], phone=phone_mt, content="먼저 저장된 발송",
            complete_time="2026-06-01T03:00:00+00:00")
    _add_mt(db_session, caller=_CALLERS[1], phone=phone_mt, content="나중 저장된 발송",
            complete_time="20260601120000")  # 같은 순간(KST 12:00)
    _add_mo(db_session, key="mo-1", caller=_CALLERS[2], phone=phone_mo, body="먼저 온 회신",
            recv_dt="2026-06-01T12:00:00")
    _add_mo(db_session, key="mo-2", caller=_CALLERS[2], phone=phone_mo, body="나중 온 회신",
            recv_dt="2026-06-01T12:00:00")
    _add_mt(db_session, caller=_CALLERS[0], phone=phone_both, content="발송", complete_time="2026-06-01T12:00:00")
    _add_mo(db_session, key="mo-3", caller=_CALLERS[2], phone=phone_both, body="회신",
            recv_dt=None, received_at="2026-06-01T03:00:00+00:00")
    db_session.commit()

    threads = {t.phone: t for t in list_threads(db_session, limit=200)[0]}

    assert {phone: (t.last_direction, t.last_body) for phone, t in threads.items()} == {
        phone_mt: ("OUT", "먼저 저장된 발송"),
        phone_mo: ("IN", "먼저 온 회신"),
        phone_both: ("OUT", "발송"),
    }
    assert threads[phone_both].caller == _CALLERS[2]


def test_threads_without_time_sort_last(db_session, sample_user):
    """리포트 전(시각 없음)만 있는 대화방은 맨 뒤다. 파싱할 수 없는 시각은 그 바로 앞.

    시각이 없어도 대표 caller 는 정해진다 — 대화방 id 가 'caller:phone' 이다.
    """
    phone_real, phone_garbage, phone_pending = "01000000001", "01000000002", "01000000003"
    _add_mt(db_session, caller=_CALLERS[1], phone=phone_pending, content="대기 A")
    _add_mt(db_session, caller=_CALLERS[1], phone=phone_pending, content="대기 B")
    _add_mo(db_session, key="mo", caller=_CALLERS[2], phone=phone_garbage, body="회신", recv_dt="N/A")
    _add_mt(db_session, caller=_CALLERS[0], phone=phone_real, content="발송", complete_time="20260101090000")
    db_session.commit()

    threads, total = list_threads(db_session, limit=200)

    assert total == 3
    assert [(t.phone, t.last_direction, t.last_timestamp, t.last_body, t.caller) for t in threads] == [
        (phone_real, "OUT", "20260101090000", "발송", _CALLERS[0]),
        (phone_garbage, "IN", "N/A", "회신", _CALLERS[2]),
        (phone_pending, "OUT", "", "대기 A", _CALLERS[1]),
    ]


def test_unread_follows_last_reply_even_when_we_sent_after(db_session, sample_user):
    """안읽음은 방향과 무관하게 마지막 회신이 팀 읽음 시각 이후인가다 — 회신 뒤 발송이 있어도 같다."""
    phone_unread, phone_read = "01000000001", "01000000002"
    for phone, read_at in [
        (phone_unread, "2026-06-01T02:30:00.100000+00:00"),  # KST 11:30 — 회신 전에 읽음
        (phone_read, "2026-06-01T03:10:00.100000+00:00"),    # KST 12:10 — 회신 뒤에 읽음
    ]:
        _add_mo(db_session, key=f"mo-{phone}", caller=_CALLERS[0], phone=phone, body="회신",
                recv_dt="2026-06-01T12:00:00")  # KST 12:00
        _add_mt(db_session, caller=_CALLERS[0], phone=phone, content="발송",
                complete_time="2026-06-01T12:30:00")  # KST 12:30 — 방향은 OUT
        db_session.add(ThreadRead(caller=_CALLERS[0], phone=phone, read_at=read_at))
    db_session.commit()

    threads, _ = list_threads(db_session, limit=200)

    assert {t.phone: (t.last_direction, t.unread) for t in threads} == {
        phone_unread: ("OUT", True),
        phone_read: ("OUT", False),
    }


def test_reply_without_callback_is_body_candidate_but_not_counted(db_session, sample_user):
    """mo_callback 이 없는 회신은 집계(방향·시각·건수)엔 빠지지만 미리보기 본문 후보다 (기존 규칙)."""
    _add_mt(db_session, caller=_CALLERS[0], phone=_PHONE, content="발송", complete_time="2026-06-01T11:00:00")
    _add_mo(db_session, key="counted", caller=_CALLERS[0], phone=_PHONE, body="집계된 회신",
            recv_dt="2026-06-01T12:00:00")
    _add_mo(db_session, key="no-callback", caller=None, phone=_PHONE, body="콜백 없는 회신",
            recv_dt=None, received_at="2026-06-01T03:10:00.100000+00:00")  # KST 12:10
    db_session.commit()

    t = _only_thread(db_session)

    assert (t.last_direction, t.last_timestamp, t.last_body, t.mo_count) == (
        "IN", "2026-06-01T12:00:00", "콜백 없는 회신", 1,
    )


def test_orders_by_real_time_across_formats_and_picks_latest_body(db_session, sample_user):
    """문자열로는 원본 KST 가 ISO 보다 늘 크지만 목록은 실제 시각순이다.

    본문은 id 가 아니라 기준 시각이 가장 늦은 행에서 온다 — 리포트가 늦게 오면 먼저 저장된
    발송이 나중에 완료될 수 있다.
    """
    phone_out, phone_iso, phone_kst = "01000000001", "01000000002", "01000000003"
    _add_mt(db_session, caller=_CALLERS[0], phone=phone_out, content="최근 발송",
            complete_time="20260601130000")  # KST 13:00 = 04:00Z
    _add_mt(db_session, caller=_CALLERS[0], phone=phone_out, content="이전 발송",
            complete_time="20260601090000")  # id 는 더 크지만 00:00Z
    _add_mo(db_session, key="iso", caller=_CALLERS[0], phone=phone_iso, body="ISO 회신",
            recv_dt=None, received_at="2026-06-01T04:30:00+00:00")
    _add_mo(db_session, key="kst", caller=_CALLERS[2], phone=phone_kst, body="KST 회신",
            recv_dt="2026-06-01 12:45:00")  # 오프셋 없음 = KST → 03:45Z
    db_session.commit()

    threads, total = list_threads(db_session, limit=2)

    assert total == 3
    assert [(t.phone, t.last_direction, t.last_body) for t in threads] == [
        (phone_iso, "IN", "ISO 회신"),    # 04:30Z
        (phone_out, "OUT", "최근 발송"),  # 04:00Z
    ]


def test_known_time_formats_share_a_shape_key(db_session):
    """저장되는 포맷은 모양 키로 묶여 번호당 후보 행이 모양 수만큼만 생긴다.

    모양 목록에 없는 표기는 문자열마다 따로 묶인다 — 결과는 같고 행만 늘어나므로 운영 포맷이
    목록에서 빠지면 결과 테스트로는 드러나지 않는다.
    """
    def shape(raw: str) -> str:
        return db_session.execute(select(_ts_shape(literal(raw)))).scalar_one()

    utc = datetime(2026, 6, 1, 3, 0, tzinfo=UTC)
    same_shape_pairs = [
        ("2026-06-01T12:00:00", "2026-12-31T23:59:59"),  # msghub rptDt·moRecvDt
        (utc.replace(microsecond=123456).isoformat(), (utc + timedelta(days=9)).replace(microsecond=1).isoformat()),
        (utc.isoformat(), (utc + timedelta(hours=9)).isoformat()),  # 마이크로초 0 인 isoformat()
        ("2026-06-01 12:00:00", "2027-01-01 00:00:00"),
        ("20260601120000", "20270101000000"),
    ]
    keys = [shape(a) for a, _ in same_shape_pairs]
    for (a, b), key in zip(same_shape_pairs, keys, strict=True):
        assert shape(b) == key != "~" + a
    assert len(set(keys)) == len(keys)
    assert shape("2026-06-01T03:00:00Z") == "~2026-06-01T03:00:00Z"


# ── 페이지·IN 절 나눔 ──────────────────────────────────────────────────────────


def _stamp(rng: random.Random) -> str | None:
    """시각 문자열 — 같은 순간을 저장될 수 있는 포맷 중 하나로 쓴다. 순간 후보를 좁혀 동률이 자주 난다."""
    roll = rng.random()
    if roll < 0.1:
        return None  # 리포트 전
    if roll < 0.13:
        return "N/A"  # 파싱 불가
    dt = _BASE + timedelta(minutes=rng.choice([0, 5, 30, 90, 540, 541]), microseconds=rng.choice([0, 250000]))
    kst = dt.astimezone(KST)
    return rng.choice([
        kst.strftime("%Y-%m-%dT%H:%M:%S"),  # msghub rptDt·moRecvDt (KST)
        kst.strftime("%Y-%m-%d %H:%M:%S"),  # moRecvDt 공백 구분 (KST)
        kst.strftime("%Y%m%d%H%M%S"),       # yyyyMMddHHmmss (KST)
        dt.isoformat(),                     # 우리가 기록하는 시각 (UTC)
        dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
    ])


def _seed_random_threads(db: Session, seed: int, phones: int = 60) -> None:
    """재현 가능한 무작위 대화 이력. 행을 섞어 넣어 id 순서가 번호·시각 순서와 무관하다."""
    rng = random.Random(seed)
    rows = []
    for i in range(phones):
        phone = f"0101234{i:04d}"
        for _ in range(rng.randint(0, 3)):
            rows.append(("mt", phone, rng.choice([*_CALLERS, ""]), _stamp(rng), _stamp(rng)))
        for _ in range(rng.randint(0, 3)):
            received_at = _stamp(rng) or "2026-06-01T03:00:00+00:00"
            rows.append(("mo", phone, rng.choice([*_CALLERS, "", None]), _stamp(rng), received_at))
        for caller in rng.sample(_CALLERS, rng.randint(0, 2)):
            minutes = rng.choice([0, 20, 60, 600])
            db.add(ThreadRead(
                caller=caller, phone=phone, read_at=(_BASE + timedelta(minutes=minutes)).isoformat()
            ))
    rng.shuffle(rows)
    for n, (kind, phone, caller, ts, ts2) in enumerate(rows):
        if kind == "mt":
            _add_mt(db, caller=caller, phone=phone, content=f"발송 {n}", complete_time=ts, report_dt=ts2)
        else:
            body = None if n % 9 == 0 else f"회신 {n}"
            _add_mo(db, key=f"mo-{n}", caller=caller, phone=phone, body=body, recv_dt=ts, received_at=ts2)
    db.commit()


@pytest.mark.parametrize("seed", range(3))
def test_pages_and_in_chunks_match_full_list(db_session, sample_user, monkeypatch, seed):
    """페이지는 전체 목록의 같은 구간이고(본문은 페이지 번호만 조회), IN 절을 나눠 조회해도 같다."""
    _seed_random_threads(db_session, seed)
    everything, total = list_threads(db_session, limit=10_000)
    assert total == len(everything) > 0
    assert {t.last_direction for t in everything} == {"IN", "OUT"}
    ranks = [_ts_rank(t.last_timestamp) for t in everything]
    assert ranks == sorted(ranks, reverse=True)  # 실제 시각순

    monkeypatch.setattr(chat, "_IN_CHUNK", 3)
    assert list_threads(db_session, limit=10_000) == (everything, total)
    for limit, offset in [(50, 0), (10, 0), (7, 13), (25, 40), (10, total - 4), (10, total + 5)]:
        page = list_threads(db_session, limit=limit, offset=offset)
        assert page == (everything[offset : offset + limit], total), f"limit={limit} offset={offset}"


# ── 쿼리 수 ────────────────────────────────────────────────────────────────────


@contextmanager
def _count_queries(engine: Engine) -> Iterator[list[str]]:
    statements: list[str] = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", _record)


def _seed_bulk_recipients(db: Session, start: int, count: int) -> None:
    """대량 발송 1건의 수신자들 — 3번호마다 더 늦은 회신이 있어 목록에 IN·OUT 이 섞인다."""
    c = Campaign(
        created_by="test-sub-001", caller_number=_CALLERS[0], message_type="short",
        content="공지", total_count=count, state="DONE", created_at="2026-06-01T00:00:00+00:00",
    )
    db.add(c)
    db.flush()
    req = MsghubRequest(campaign_id=c.id, chunk_index=0, sent_at="2026-06-01T00:00:00+00:00")
    db.add(req)
    db.flush()
    for i in range(start, start + count):
        phone = f"0105555{i:04d}"
        mm, ss = divmod(i, 60)
        db.add(Message(
            campaign_id=c.id, msghub_request_id=req.id, to_number=phone, to_number_raw=phone,
            status="DONE", complete_time=f"2026060112{mm:02d}{ss:02d}",
        ))
        if i % 3 == 0:
            db.add(MoMessage(
                mo_key=f"bulk-{i}", mo_number=phone, mo_callback=_CALLERS[0], mo_msg="네",
                mo_recv_dt=f"2026060113{mm:02d}{ss:02d}", raw_payload="{}",
                received_at="2026-06-01T04:00:00+00:00",
            ))
    db.commit()


def test_query_count_does_not_grow_with_phones(db_engine, db_session, sample_user):
    """새로고침마다 도는 목록 쿼리 수가 번호 수와 무관하다 — 페이지(200) 밖 번호는 본문을 안 읽는다."""
    service: dict[int, int] = {}
    route: dict[int, int] = {}
    seeded = 0
    for phones in (6, 240):
        _seed_bulk_recipients(db_session, start=seeded, count=phones - seeded)
        seeded = phones

        with _count_queries(db_engine) as statements:
            threads, total = list_threads(db_session, limit=200)
        service[phones] = len(statements)
        assert total == phones
        assert {t.last_direction for t in threads} == {"IN", "OUT"}  # 본문 조회 2종이 모두 돈다

        with _count_queries(db_engine) as statements:
            rows = api_list_threads(q=None, unread=None, db=db_session)["data"]
        route[phones] = len(statements)
        assert len(rows) == min(phones, 200)

    assert service[6] == service[240] == 5  # 집계 2 + 읽음 1 + 본문 MO·MT 각 1
    assert route[6] == route[240]
