"""대화 목록·대시보드 최근 대화의 date·today — 목록 시각 문구(오늘·어제·날짜)의 재료.

목록은 마지막 메시지 시각을 time(HH:MM)만 내려 몇 주 전 대화와 오늘 대화가 같아 보였다. 행마다
마지막 메시지의 KST 달력 날짜(date)를, 응답마다 응답 시각의 KST 날짜(today)를 싣고 web 이 둘을
비교해 문구를 만든다. 저장 시각은 UTC ISO 와 오프셋 없는 KST(msghub rptDt·moRecvDt)가 섞여 있어
UTC 날짜로 자르거나 오프셋 없는 값을 UTC 로 읽으면 KST 자정 부근 대화가 다른 날로 밀린다.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.models import Campaign, Message, MoMessage, MsghubRequest
from app.routes.dashboard import get_dashboard
from app.routes.threads import api_get_thread, api_list_threads

_CALLER = "0212345678"


def _sent(db, author: str, phone: str, *, complete_time: str) -> None:
    """phone 에게 보낸 발송 1건 — 목록 시각은 complete_time 이 있으면 그 값이다."""
    campaign = Campaign(
        created_by=author, caller_number=_CALLER, message_type="short",
        content=f"{phone} 안내", total_count=1, state="DONE", created_at="2026-09-01T00:00:00+00:00",
    )
    db.add(campaign)
    db.flush()
    req = MsghubRequest(campaign_id=campaign.id, chunk_index=0, sent_at="2026-09-01T00:00:00+00:00")
    db.add(req)
    db.flush()
    db.add(Message(
        campaign_id=campaign.id, msghub_request_id=req.id, to_number=phone, to_number_raw=phone,
        status="DONE", complete_time=complete_time,
    ))
    db.commit()


def _received(db, phone: str, *, mo_recv_dt: str | None, received_at: str) -> None:
    db.add(MoMessage(
        mo_key=f"mo-{phone}", mo_number=phone, mo_callback=_CALLER, mo_msg=f"{phone} 회신",
        raw_payload="{}", mo_recv_dt=mo_recv_dt, received_at=received_at,
    ))
    db.commit()


def _seed_around_kst_midnight(db, author: str) -> None:
    """KST 9/26→9/27 자정 양쪽의 마지막 메시지를 저장 포맷별로 한 대화씩 둔다."""
    # moRecvDt 원본(오프셋 없는 KST) 9/26 23:59 — UTC 로 읽으면 9/27 08:59 가 된다.
    _received(db, "01000000001", mo_recv_dt="2026-09-26T23:59:40", received_at="2026-09-26T14:59:41+00:00")
    # UTC 날짜로는 아직 9/26 이지만 KST 로는 9/27 00:00.
    _sent(db, author, "01000000002", complete_time="2026-09-26T15:00:30+00:00")
    # moRecvDt 가 없어 received_at(UTC, 마이크로초 포함)으로 보완 — KST 9/26 23:59.
    _received(db, "01000000003", mo_recv_dt=None, received_at="2026-09-26T14:59:59.500000+00:00")
    # 14자리 yyyyMMddHHmmss(KST) 9/27 00:10.
    _sent(db, author, "01000000004", complete_time="20260927001000")
    # 해석할 수 없는 시각 — time 처럼 date 도 빈 문자열이고 web 은 시각 칸을 비운다.
    _received(db, "01000000005", mo_recv_dt="확인불가", received_at="2026-09-27T01:00:00+00:00")


_TIME_AND_DATE = {
    "01000000001": ("23:59", "2026-09-26"),
    "01000000002": ("00:00", "2026-09-27"),
    "01000000003": ("23:59", "2026-09-26"),
    "01000000004": ("00:10", "2026-09-27"),
    "01000000005": ("", ""),
}


def _now_is(monkeypatch, module: str, *instants: datetime) -> None:
    """module 이 쓰는 datetime.now 를 고정한다 — 부를 때마다 다음 시각, 마지막 시각은 계속 쓴다."""
    queue = list(instants)

    class _Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            current = queue.pop(0) if len(queue) > 1 else queue[0]
            return current.astimezone(tz)

    monkeypatch.setattr(f"{module}.datetime", _Fixed)


def test_list_rows_carry_kst_date_across_midnight_with_mixed_formats(db_session, sample_user):
    _seed_around_kst_midnight(db_session, sample_user.sub)

    rows = api_list_threads(db=db_session)["data"]

    assert {row["phone"]: (row["time"], row["date"]) for row in rows} == _TIME_AND_DATE


@pytest.mark.parametrize(("now_utc", "today"), [
    (datetime(2026, 9, 26, 14, 59, 59, tzinfo=UTC), "2026-09-26"),  # KST 23:59:59
    (datetime(2026, 9, 26, 15, 0, 0, tzinfo=UTC), "2026-09-27"),    # KST 00:00 — UTC 로는 아직 9/26
])
def test_list_today_is_kst_date_at_request_time(db_session, monkeypatch, now_utc, today):
    _now_is(monkeypatch, "app.routes.threads", now_utc)

    assert api_list_threads(db=db_session)["meta"]["today"] == today


def test_dashboard_inbox_reads_offsetless_kst_and_carries_today(db_session, sample_user, monkeypatch):
    # 대시보드는 오프셋 없는 msghub 시각을 UTC 로 읽어 9시간 늦게(23:59 → 08:59) 보였고
    # 14자리 시각은 비워 두었다. 목록과 같은 파서·같은 date 를 쓴다.
    _seed_around_kst_midnight(db_session, sample_user.sub)
    _now_is(monkeypatch, "app.routes.dashboard", datetime(2026, 9, 26, 15, 30, tzinfo=UTC))  # KST 9/27 00:30

    inbox = get_dashboard(db=db_session)["data"]["inbox"]

    assert inbox["today"] == "2026-09-27"
    assert {row["phone"]: (row["time"], row["date"]) for row in inbox["threads"]} == _TIME_AND_DATE


def test_dashboard_today_is_measured_after_reading_threads(db_session, monkeypatch):
    # 요청이 KST 자정 직전에 시작해 목록을 읽는 사이 날짜가 바뀌면 그 사이 기록된 대화는 새 날짜다.
    # 기준일을 요청 시작 시각으로 잡으면 그 대화가 내일 날짜로 보인다 — 목록처럼 읽은 뒤에 잰다.
    _now_is(
        monkeypatch, "app.routes.dashboard",
        datetime(2026, 9, 26, 14, 59, 59, tzinfo=UTC),  # 요청 시작 KST 23:59:59
        datetime(2026, 9, 26, 15, 0, 1, tzinfo=UTC),    # 목록을 읽은 뒤 KST 00:00:01
    )

    data = get_dashboard(db=db_session)["data"]

    assert (data["timeline"]["now"], data["inbox"]["today"]) == ("23:59", "2026-09-27")


def test_thread_detail_date_matches_its_last_message(db_session, sample_user):
    _sent(db_session, sample_user.sub, "01000000002", complete_time="2026-09-26T15:00:30+00:00")

    detail = api_get_thread(f"{_CALLER}:01000000002", db=db_session)["data"]

    last = detail["messages"][-1]
    assert (detail["time"], detail["date"]) == (last["time"], last["date"]) == ("00:00", "2026-09-27")
