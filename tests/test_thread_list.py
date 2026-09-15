"""대화방 목록(list_threads) — 페이지 번호만 본문을 조회해도 응답이 같고, 쿼리 수가 번호 수와 무관하다.

예전 구현은 메시지를 주고받은 모든 번호(대량 발송 수신자 포함)마다 마지막 본문을 쿼리한 뒤
잘랐다(로컬 측정 2만 번호 ≈ 2.5초, 새로고침마다 반복). 지금은 집계값으로 정렬·자른 뒤 페이지
번호만 묶어 조회한다. _legacy_list_threads 는 바꾸기 직전(405a254) 구현을 그대로 옮긴 비교
기준이다 — ISO·msghub 원본 시각이 섞이고 시각 동률·NULL·여러 발신번호가 있는 데이터에서 두
구현의 결과가 필드 단위로 같아야 한다.
"""
from __future__ import annotations

import random
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import Engine, event, func, select
from sqlalchemy.orm import Session

from app.models import Campaign, Message, MoMessage, MsghubRequest, ThreadRead
from app.routes.threads import api_list_threads
from app.services import chat
from app.services.chat import ChatThread, _parse_ts_for_sort, list_threads, thread_unread
from app.util.time import KST

_CALLERS = ["0212345678", "025771000", "CHATBOT_0123"]
_BASE = datetime(2026, 6, 1, 3, 0, tzinfo=UTC)


# ── 비교 기준: 바꾸기 직전 구현 (수정하지 말 것) ───────────────────────────────


def _legacy_list_threads(
    db: Session, limit: int = 50, offset: int = 0
) -> tuple[list[ChatThread], int]:
    """대화방 목록을 최근 활동순으로 반환한다."""
    # MT 측 — campaigns.caller_number + messages.to_number로 그룹
    mt_rows = db.execute(
        select(
            Campaign.caller_number.label("caller"),
            Message.to_number.label("phone"),
            func.max(
                func.coalesce(Message.complete_time, Message.report_dt)
            ).label("last_t"),
            func.count().label("cnt"),
        )
        .join(Campaign, Campaign.id == Message.campaign_id)
        .group_by(Campaign.caller_number, Message.to_number)
    ).all()

    # MO 측 — mo_callback + mo_number로 그룹
    mo_rows = db.execute(
        select(
            MoMessage.mo_callback.label("caller"),
            MoMessage.mo_number.label("phone"),
            func.max(
                func.coalesce(MoMessage.mo_recv_dt, MoMessage.received_at)
            ).label("last_t"),
            func.count().label("cnt"),
        )
        .where(MoMessage.mo_callback.is_not(None))
        .group_by(MoMessage.mo_callback, MoMessage.mo_number)
    ).all()

    threads: dict[str, dict] = {}

    def _touch(phone: str) -> dict:
        return threads.setdefault(
            phone,
            {
                "caller": "",
                "phone": phone,
                "mt_last_t": "",
                "mt_count": 0,
                "mo_last_t": "",
                "mo_count": 0,
                "caller_last_t": "",  # 대표 caller 선정용 최신 활동 시각
            },
        )

    def _maybe_set_caller(t: dict, caller: str, ts: str) -> None:
        """더 최근(ts) 활동의 caller 를 대표로 채택."""
        if caller and ts >= t["caller_last_t"]:
            t["caller"] = caller
            t["caller_last_t"] = ts

    for r in mt_rows:
        if not r.caller or not r.phone:
            continue
        t = _touch(r.phone)
        t["mt_last_t"] = r.last_t or ""
        t["mt_count"] += r.cnt
        _maybe_set_caller(t, r.caller, r.last_t or "")
    for r in mo_rows:
        if not r.caller or not r.phone:
            continue
        t = _touch(r.phone)
        # 같은 phone 에 여러 mo_callback 이 있으면 최신 것으로 갱신.
        if (r.last_t or "") >= t["mo_last_t"]:
            t["mo_last_t"] = r.last_t or ""
        t["mo_count"] += r.cnt
        _maybe_set_caller(t, r.caller, r.last_t or "")

    read_at_map: dict[str, str] = {}
    for r in db.execute(
        select(ThreadRead.phone, ThreadRead.read_at)
    ).all():
        prev = read_at_map.get(r.phone, "")
        if (r.read_at or "") > prev:
            read_at_map[r.phone] = r.read_at or ""

    # 마지막 메시지 상세를 가져와 ChatThread로 빌드
    built: list[ChatThread] = []
    for phone, t in threads.items():
        caller = t["caller"]  # 대표(최근) caller
        last_mt_t = t["mt_last_t"]
        last_mo_t = t["mo_last_t"]
        if last_mo_t > last_mt_t:
            last_t = last_mo_t
            last_dir = "IN"
            mo = db.execute(
                select(MoMessage.mo_msg)
                .where(MoMessage.mo_number == phone)
                .order_by(
                    func.coalesce(MoMessage.mo_recv_dt, MoMessage.received_at).desc()
                )
                .limit(1)
            ).scalar_one_or_none()
            last_body = mo or ""
        else:
            last_t = last_mt_t
            last_dir = "OUT"
            last_body_row = db.execute(
                select(Campaign.content)
                .join(Message, Message.campaign_id == Campaign.id)
                .where(Message.to_number == phone)
                .order_by(
                    func.coalesce(Message.complete_time, Message.report_dt).desc()
                )
                .limit(1)
            ).scalar_one_or_none()
            last_body = last_body_row or ""

        # 안읽음 = 고객(MO) 최종 메시지가 팀 마지막 읽음 시각 이후.
        read_at = read_at_map.get(phone, "")
        unread = thread_unread(last_mo_t, read_at)

        built.append(
            ChatThread(
                caller=caller,
                phone=phone,
                last_timestamp=last_t,
                last_body=last_body,
                last_direction=last_dir,
                unread=unread,
                mo_count=t["mo_count"],
                mt_count=t["mt_count"],
            )
        )

    # last_timestamp 도 ISO 와 msghub 원본 섞여있어 parse 해서 정렬.
    built.sort(key=lambda t: _parse_ts_for_sort(t.last_timestamp), reverse=True)
    total = len(built)
    return built[offset : offset + limit], total


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
    db.add(MoMessage(
        mo_key=key, mo_number=phone, mo_callback=caller, mo_type="message", mo_msg=body,
        mo_recv_dt=recv_dt, raw_payload="{}", received_at=received_at,
    ))
    db.flush()


def _stamp(rng: random.Random) -> str | None:
    """시각 문자열 — 같은 순간을 운영 DB 에 섞여 있는 포맷 중 하나로 쓴다.

    포맷이 섞이면 문자열 대소와 실제 시각 순서가 어긋난다(ISO '2026-..' 는 원본 '2026..'
    보다 늘 작다). 순간 후보를 좁혀 대화방 사이·한 번호 안의 시각 동률이 자주 나게 한다.
    """
    roll = rng.random()
    if roll < 0.1:
        return None  # 리포트 전
    if roll < 0.13:
        return "N/A"  # 파싱 불가 — 정렬 키 0.0
    dt = _BASE + timedelta(minutes=rng.choice([0, 5, 30, 90, 540, 541]))
    kst = dt.astimezone(KST)
    return rng.choice([
        kst.strftime("%Y%m%d%H%M%S"),       # msghub 리포트 complete_time·report_dt (KST)
        kst.strftime("%Y-%m-%d %H:%M:%S"),  # msghub moRecvDt (오프셋 없음 = KST)
        dt.isoformat(),                     # 우리가 기록하는 시각 (+00:00)
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


def _seed_edge_threads(db: Session) -> None:
    """무작위로는 드물게 나오는 경우를 항상 넣는다."""
    # 같은 시각의 발송 2건(발신번호 다름) — 본문 동률
    _add_mt(db, caller=_CALLERS[1], phone="01099990001", content="동률 발송 A", complete_time="20260601120000")
    _add_mt(db, caller=_CALLERS[0], phone="01099990001", content="동률 발송 B", complete_time="20260601120000")
    # 같은 시각의 회신 2건 — 본문 동률
    _add_mo(db, key="edge-1", caller=_CALLERS[2], phone="01099990002", body="동률 회신 A", recv_dt="20260601130000")
    _add_mo(db, key="edge-2", caller=_CALLERS[2], phone="01099990002", body="동률 회신 B", recv_dt="20260601130000")
    # 리포트 전 발송만 2건 — 기준 시각이 전부 NULL
    _add_mt(db, caller=_CALLERS[0], phone="01099990003", content="대기 A")
    _add_mt(db, caller=_CALLERS[0], phone="01099990003", content="대기 B")
    # 가장 늦은 회신의 mo_callback 이 NULL — 집계엔 빠져도 본문 후보다
    _add_mo(db, key="edge-3", caller=_CALLERS[0], phone="01099990004", body="집계된 회신", recv_dt="20260601100000")
    _add_mo(db, key="edge-4", caller=None, phone="01099990004", body="콜백 없는 회신", recv_dt="20260601110000")
    db.commit()


# ── 예전 구현과 같은 응답 ──────────────────────────────────────────────────────


@pytest.mark.parametrize("chunk", [500, 3], ids=["one-chunk", "many-chunks"])
@pytest.mark.parametrize("seed", range(4))
def test_matches_legacy_on_mixed_format_data(db_session, sample_user, monkeypatch, seed, chunk):
    monkeypatch.setattr(chat, "_IN_CHUNK", chunk)  # IN 절을 나눠 조회해도 합친 결과가 같아야 한다
    _seed_random_threads(db_session, seed)
    _seed_edge_threads(db_session)

    everything, total = _legacy_list_threads(db_session, limit=200)
    assert total == len(everything)  # 전부 한 페이지 — 모든 대화방을 필드 단위로 비교한다
    # 비교가 헛돌지 않게: 두 방향이 다 있고, 정렬 키 동률(안정 정렬 순서)이 있고, 문자열
    # 순서로 정렬하면 달라지는(포맷이 섞인) 데이터여야 한다.
    assert {t.last_direction for t in everything} == {"IN", "OUT"}
    keys = [_parse_ts_for_sort(t.last_timestamp) for t in everything]
    assert len(set(keys)) < len(keys)
    assert sorted(everything, key=lambda t: t.last_timestamp, reverse=True) != everything

    for limit, offset in [(200, 0), (50, 0), (10, 0), (7, 13), (25, 40), (10, total - 4), (10, total + 5)]:
        assert list_threads(db_session, limit=limit, offset=offset) == _legacy_list_threads(
            db_session, limit=limit, offset=offset
        ), f"limit={limit} offset={offset}"


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

    with _count_queries(db_engine) as statements:
        _legacy_list_threads(db_session, limit=200)
    assert len(statements) == 3 + 240  # 예전: 번호마다 본문 쿼리 1회
