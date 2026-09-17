"""그룹 최근 발송 시각(lastCampaignAt) — 멤버에게 간 발송 중 실제로 가장 늦은 시각을 KST 로 보인다.

complete_time 은 msghub rptDt 원본(오프셋 없는 KST 'yyyy-MM-ddTHH:mm:ss')이고 rptDt 가 비면 UTC
ISO(report._now_iso())가 들어간다. SQL max() 는 문자열 대소라 같은 순간의 KST 벽시계가 UTC 보다
9시간 늦어 보인다 — 고르는 규칙을 보는 경우는 실제로 더 늦은 쪽이 UTC 이고 차이가 9시간 안이 되게
골랐고, 나머지는 표시 시각(오프셋 없는 값을 KST 로 읽는지)을 본다.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import Engine, event

from app.models import Campaign, Message, MsghubRequest
from app.routes.groups import get_group_route, list_groups_route
from app.services.contacts import create_contact
from app.services.groups import add_members, create_group

_USER = "test-sub-001"


def _group(db, name: str, phones: tuple[str, ...]) -> int:
    g = create_group(db, name=name, created_by=_USER)
    ids = [
        create_contact(db, name=f"{name}-{i}", created_by=_USER, phone=phone).id
        for i, phone in enumerate(phones)
    ]
    add_members(db, group_id=g.id, contact_ids=ids, added_by=_USER)
    return g.id


def _add_mt(db, *, phone: str, reported_at: str) -> None:
    """phone 에게 보낸 발송 1건 — 웹훅 리포트라 complete_time·report_dt 가 같은 값이다."""
    c = Campaign(
        created_by=_USER, caller_number="0212345678", message_type="short",
        content="공지", total_count=1, state="DONE", created_at="2026-06-01T00:00:00+00:00",
    )
    db.add(c)
    db.flush()
    req = MsghubRequest(campaign_id=c.id, chunk_index=0, sent_at="2026-06-01T00:00:00+00:00")
    db.add(req)
    db.flush()
    db.add(Message(
        campaign_id=c.id, msghub_request_id=req.id, to_number=phone, to_number_raw=phone,
        status="DONE", complete_time=reported_at, report_dt=reported_at,
    ))
    db.flush()


def _last_campaign_at(db) -> dict[str, str | None]:
    return {r["name"]: r.get("lastCampaignAt") for r in list_groups_route(q=None, db=db)["data"]}


@pytest.mark.parametrize(
    ("stamps", "expected"),
    [
        pytest.param(("2026-06-01T09:00:00", "2026-06-01T12:00:00"), "2026-06-01 12:00", id="kst-only"),
        pytest.param(("2026-06-01T12:00:00", "2026-06-01T03:30:00.250000+00:00"), "2026-06-01 12:30",
                     id="utc-fallback-after-kst"),
        pytest.param(("2026-06-01T12:40:00", "2026-06-01T03:30:00.250000+00:00"), "2026-06-01 12:40",
                     id="kst-after-utc-fallback"),
    ],
)
def test_last_campaign_at_is_latest_send_in_kst(db_session, sample_user, stamps, expected):
    """목록·상세 모두 실제로 가장 늦은 발송 시각이다.

    예전엔 문자열 max 로 골라 rptDt 가 비어 UTC 로 기록된 더 늦은 발송을 놓쳤고, 고른 msghub 값도
    UTC 로 읽어 9시간 늦게 보였다.
    """
    phones = ("01011112222", "01033334444")
    gid = _group(db_session, "영업팀", phones)
    for phone, stamp in zip(phones, stamps, strict=True):
        _add_mt(db_session, phone=phone, reported_at=stamp)
    db_session.commit()

    assert _last_campaign_at(db_session) == {"영업팀": expected}
    assert get_group_route(f"g-{gid}", db=db_session)["data"]["lastCampaignAt"] == expected


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


def test_query_count_does_not_grow_with_groups(db_engine, db_session, sample_user):
    """그룹마다 조회하지 않는다 — 목록 쿼리 수가 그룹·발송 수와 무관하고, 그룹마다 제 멤버의 최신 발송이다."""
    counts: dict[int, int] = {}
    expected: dict[str, str] = {}
    for groups in (2, 20):
        for i in range(len(expected), groups):
            name = f"그룹{i:02d}"
            phones = (f"0101000{i:04d}", f"0102000{i:04d}")
            _group(db_session, name, phones)
            # KST 12:00 msghub 값과, 그보다 늦은 KST 12:ii:30 의 UTC 대체값
            _add_mt(db_session, phone=phones[0], reported_at="2026-06-01T12:00:00")
            _add_mt(db_session, phone=phones[1], reported_at=f"2026-06-01T03:{i:02d}:30.500000+00:00")
            expected[name] = f"2026-06-01 12:{i:02d}"
        db_session.commit()

        with _count_queries(db_engine) as statements:
            last = _last_campaign_at(db_session)
        counts[groups] = len(statements)
        assert last == expected

    assert counts[2] == counts[20]
