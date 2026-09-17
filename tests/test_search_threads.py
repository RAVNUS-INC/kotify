"""통합 검색 대화방 섹션 — 포맷이 섞인 시각을 실제 시각으로 비교하고 KST 로 보인다.

시각은 대화방 목록과 같은 기준이다: 발송은 coalesce(complete_time, report_dt), 회신은
coalesce(mo_recv_dt, received_at). msghub 원본(rptDt·moRecvDt)은 오프셋 없는 KST
'yyyy-MM-ddTHH:mm:ss'이고, 비었거나 우리가 기록한 값은 UTC ISO 다(report._now_iso(), 우리 수신
시각 received_at). 웹훅 리포트는 report_dt·complete_time 을 같은 값으로, 발송 결과 조회는
report_dt 만 채운다. 문자열 대소로는 같은 순간의 KST 벽시계가 UTC 보다 9시간 늦어 보인다 — 고르는
규칙을 보는 경우는 실제로 더 늦은 쪽이 UTC 이고 차이가 9시간 안이 되게 골랐고, 나머지는 반대
방향·표시 시각(오프셋 없는 값을 KST 로 읽는지)·시각 기준을 본다.
"""
from __future__ import annotations

import pytest

from app.models import Campaign, Message, MoMessage, MsghubRequest
from app.routes.search import search

_CALLER = "0212345678"
_PHONE = "01012345678"


def _add_mt(db, *, phone, content, report_dt, complete=True):
    """phone 에게 보낸 발송 1건. complete=False 는 발송 결과 조회로 report_dt 만 채워진 행이다."""
    c = Campaign(
        created_by="test-sub-001", caller_number=_CALLER, message_type="short",
        content=content, total_count=1, state="DONE", created_at="2026-06-01T00:00:00+00:00",
    )
    db.add(c)
    db.flush()
    req = MsghubRequest(campaign_id=c.id, chunk_index=0, sent_at="2026-06-01T00:00:00+00:00")
    db.add(req)
    db.flush()
    db.add(Message(
        campaign_id=c.id, msghub_request_id=req.id, to_number=phone, to_number_raw=phone,
        status="DONE", report_dt=report_dt, complete_time=report_dt if complete else None,
    ))
    db.flush()


def _add_mo(db, *, key, phone, body, recv_dt, received_at):
    """phone 이 보낸 회신 1건 — recv_dt 는 msghub moRecvDt(KST, 없으면 None), received_at 은 우리
    수신 시각(UTC)."""
    db.add(MoMessage(
        mo_key=key, mo_number=phone, mo_callback=_CALLER, mo_type="message", mo_msg=body,
        mo_recv_dt=recv_dt, raw_payload="{}", received_at=received_at,
    ))
    db.flush()


def _threads(db, user) -> list[dict]:
    return search(q="배송", user=user, db=db)["data"]["threads"]


@pytest.mark.parametrize(
    ("sends", "replies", "expected"),
    [
        pytest.param(
            [{"content": "배송 안내", "report_dt": "2026-06-01T12:00:00"}],  # KST 12:00
            [{"body": "배송 확인했습니다", "recv_dt": None,
              "received_at": "2026-06-01T03:10:01.123456+00:00"}],  # KST 12:10, moRecvDt 없음
            ("배송 확인했습니다", "2026-06-01 12:10", None),
            id="utc-reply-after-kst-report",
        ),
        pytest.param(
            [{"content": "배송 안내", "report_dt": "2026-06-01T12:20:00"}],  # KST 12:20
            [{"body": "배송 확인했습니다", "recv_dt": None,
              "received_at": "2026-06-01T03:10:01.123456+00:00"}],  # KST 12:10, moRecvDt 없음
            ("배송 안내", "2026-06-01 12:20", "배송 안내"),
            id="kst-report-after-utc-reply",
        ),
        pytest.param(
            [{"content": "배송 안내 1차", "report_dt": "2026-06-01T12:00:00"},  # KST 12:00
             {"content": "배송 안내 2차", "report_dt": "2026-06-01T03:30:00.250000+00:00"}],  # KST 12:30
            [],
            ("배송 안내 2차", "2026-06-01 12:30", "배송 안내 2차"),
            id="utc-fallback-report-after-kst-report",
        ),
        pytest.param(
            [{"content": "배송 안내", "report_dt": "2026-06-01T12:40:00", "complete": False}],  # KST 12:40
            [{"body": "배송 언제 오나요", "recv_dt": "2026-06-01T12:10:00",
              "received_at": "2026-06-01T03:10:01.123456+00:00"}],  # KST 12:10
            ("배송 안내", "2026-06-01 12:40", "배송 안내"),
            id="report_dt-only-send-after-reply",
        ),
        pytest.param(
            [{"content": "배송 안내", "report_dt": "2026-06-01T11:00:00"}],  # KST 11:00
            [{"body": "배송 문의", "recv_dt": "2026-06-01T10:00:00",  # KST 10:00 에 보낸 회신
              "received_at": "2026-06-01T03:00:00.500000+00:00"}],  # 웹훅은 KST 12:00 에 도착
            ("배송 안내", "2026-06-01 11:00", "배송 안내"),
            id="late-webhook-reply-before-send",
        ),
    ],
)
def test_thread_shows_latest_match_by_real_time(db_session, sample_user, sends, replies, expected):
    """한 대화방에 맞는 메시지가 여럿이면 실제로 가장 늦은 것이 미리보기·시각이다.

    예전엔 문자열로 비교해 오프셋 없는 KST 발송 시각이 9시간 늦어 보여, 더 늦은 고객 회신이나 UTC 로
    기록된 발송에 이겼다. report_dt 만 있는 발송은 시각이 빈 값이라 늘 졌고, 표시 시각은 오프셋 없는
    값을 UTC 로 읽어 9시간 늦었다. 회신은 대화방 목록처럼 고객이 보낸 시각(moRecvDt)이 기준이라
    웹훅이 늦게 온 회신이 그 사이의 발송을 이기지 않는다.
    """
    for kw in sends:
        _add_mt(db_session, phone=_PHONE, **kw)
    for i, kw in enumerate(replies):
        _add_mo(db_session, key=f"mo-{i}", phone=_PHONE, **kw)
    db_session.commit()

    threads = _threads(db_session, sample_user)

    assert len(threads) == 1
    assert (threads[0]["snippet"], threads[0]["time"], threads[0].get("campaignName")) == expected


def test_threads_ordered_by_real_time_across_formats(db_session, sample_user):
    """대화방끼리도 실제 시각순 — 문자열 순서로는 오프셋 없는 KST 두 방이 UTC 두 방보다 늘 앞이다."""
    _add_mt(db_session, phone="01000000001", content="배송 안내",
            report_dt="2026-06-01T12:00:00")  # KST 12:00
    _add_mt(db_session, phone="01000000002", content="배송 지연 안내",
            report_dt="2026-06-01T03:30:00.250000+00:00")  # KST 12:30, UTC 대체값
    _add_mo(db_session, key="mo-3", phone="01000000003", body="배송 문의", recv_dt=None,
            received_at="2026-06-01T02:15:00.100000+00:00")  # KST 11:15, moRecvDt 없음
    _add_mo(db_session, key="mo-4", phone="01000000004", body="배송 확인", recv_dt="2026-06-01T11:45:00",
            received_at="2026-06-01T02:45:01.500000+00:00")  # KST 11:45
    db_session.commit()

    threads = _threads(db_session, sample_user)

    assert [(t["phone"], t["time"]) for t in threads] == [
        ("01000000002", "2026-06-01 12:30"),
        ("01000000001", "2026-06-01 12:00"),
        ("01000000004", "2026-06-01 11:45"),
        ("01000000003", "2026-06-01 11:15"),
    ]
