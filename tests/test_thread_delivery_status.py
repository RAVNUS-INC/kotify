"""대화방 발신 메시지 전달 상태 — 실패한 답장이 전달된 답장과 똑같이 보이던 문제.

스레드 상세 메시지에 status(pending/sent/failed)를 싣는다. msghub 요청 단계 실패(FAILED)와
리포트 실패(DONE + 실패 코드)는 failed, 양방향 리포트 실패 후 SMS 대체 발송을 기다리는
FB_PENDING 은 아직 전달 중이라 pending 이다. 수신(IN) 메시지 shape 는 바뀌지 않는다.
"""
from __future__ import annotations

import pytest

from app.models import Campaign, Message, MoMessage, MsghubRequest
from app.msghub.codes import SUCCESS_CODE
from app.routes.threads import api_get_thread
from app.services.chat import delivery_status

_CALLER = "0212345678"
_PHONE = "01099998888"
_TID = f"{_CALLER}:{_PHONE}"

_RCS = "RPSSAXX001"   # 단방향 RCS
_CHAT = "RPCSAXX001"  # 양방향 CHAT
_REPORT_FAIL = "59999"


def _send(
    db,
    *,
    status,
    result_code=None,
    channel=None,
    cli_key="c1-0-0",
    rcs_messagebase_id=_RCS,
):
    """_PHONE 에게 보낸 답장 1건(Campaign + Message)."""
    c = Campaign(
        created_by="test-sub-001", caller_number=_CALLER, message_type="short",
        content="안내드립니다", total_count=1, state="DISPATCHED",
        created_at="2026-09-01T00:00:00+00:00", rcs_messagebase_id=rcs_messagebase_id,
    )
    db.add(c)
    db.flush()
    req = MsghubRequest(campaign_id=c.id, chunk_index=0, sent_at="2026-09-01T00:00:00+00:00")
    db.add(req)
    db.flush()
    db.add(Message(
        campaign_id=c.id, msghub_request_id=req.id, to_number=_PHONE, to_number_raw=_PHONE,
        status=status, result_code=result_code, channel=channel, cli_key=cli_key,
    ))
    db.commit()


def _receive(db):
    """_PHONE 이 보낸 회신(MO) 1건 — 발송 5분 뒤."""
    db.add(MoMessage(
        mo_key="mo-1", mo_number=_PHONE, mo_callback=_CALLER, mo_msg="네 확인했습니다",
        raw_payload="{}", received_at="2026-09-01T00:05:00+00:00",
    ))
    db.commit()


# ── delivery_status ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("status", "result_code", "cli_key", "expected"),
    [
        ("PENDING", None, "c1-0-0", "pending"),         # 예약 등 접수 응답에 item 없음
        ("REG", SUCCESS_CODE, "c1-0-0", "pending"),     # 10000 은 접수 응답 코드일 뿐
        ("ING", SUCCESS_CODE, "c1-0-0", "pending"),
        ("FB_PENDING", _REPORT_FAIL, "c1-0-0-fb", "pending"),  # 실패 코드가 남아도 대체 발송 중
        ("DONE", SUCCESS_CODE, "c1-0-0", "sent"),
        ("DONE", _REPORT_FAIL, "c1-0-0", "failed"),
        ("DONE", None, "c1-0-0", "failed"),             # 코드 없는 리포트 — 캠페인 집계와 같이 실패
        ("FAILED", None, "c1-0-0", "failed"),           # 청크 요청 자체 실패
        ("FAILED", "31101", "c1-0-0", "failed"),        # item 단위 거부(수신번호 에러)
        ("CANCELED", None, "c1-0-0", "cancelled"),      # 예약 취소 — 발송되지 않음
        ("CANCELED", None, None, "cancelled"),          # alembic 0017 이 옮긴 NCP 시절 예약 취소
        # NCP 시절 행 — 결과를 알 수 없음. PENDING 은 그때도 썼지만 cliKey 가 없다.
        ("PENDING", None, None, None),
        ("COMPLETED", "0", None, None),
        ("UNKNOWN", None, None, None),
    ],
)
def test_delivery_status_mapping(status, result_code, cli_key, expected):
    assert delivery_status(status, result_code, cli_key) == expected


# ── api_get_thread: 발신 메시지 status ───────────────────────────────────────


@pytest.mark.parametrize(
    ("row", "expected_kind", "expected_status"),
    [
        pytest.param(
            {"status": "REG", "result_code": SUCCESS_CODE},
            "rcs", "pending", id="accepted-awaiting-report",
        ),
        pytest.param(
            {"status": "DONE", "result_code": SUCCESS_CODE, "channel": "RCS"},
            "rcs", "sent", id="delivered",
        ),
        pytest.param(
            {"status": "FAILED", "result_code": "31101"},
            "rcs", "failed", id="msghub-request-rejected",
        ),
        pytest.param(
            {"status": "DONE", "result_code": _REPORT_FAIL, "channel": "RCS"},
            "rcs", "failed", id="report-failure-code",
        ),
        pytest.param(
            {
                "status": "FB_PENDING", "result_code": _REPORT_FAIL, "channel": "RCS",
                "cli_key": "c1-0-0-fb", "rcs_messagebase_id": _CHAT,
            },
            "sms", "pending", id="webhook-sms-fallback-in-flight",
        ),
        pytest.param(
            {
                "status": "FAILED", "result_code": _REPORT_FAIL, "channel": "RCS",
                "cli_key": "c1-0-0-fb", "rcs_messagebase_id": _CHAT,
            },
            "sms", "failed", id="webhook-sms-fallback-request-failed",
        ),
    ],
)
def test_thread_detail_outbound_status(
    db_session, sample_user, row, expected_kind, expected_status
):
    _send(db_session, **row)
    msg = api_get_thread(_TID, db=db_session)["data"]["messages"][-1]
    assert msg["side"] == "us"
    assert msg["kind"] == expected_kind  # 말풍선 라벨 예: "SMS · 대기"
    assert msg["status"] == expected_status


@pytest.mark.parametrize(
    ("status", "result_code"),
    [
        ("COMPLETED", "0"),  # NCP 완료 — 성공 여부 컬럼이 삭제됨
        ("PENDING", None),   # NCP 접수 후 결과를 못 받은 행 — 재조정 대상도 아니다
    ],
)
def test_thread_detail_omits_status_for_legacy_rows(
    db_session, sample_user, status, result_code
):
    """판정할 수 없는 NCP 시절 행(cliKey 없음)은 대기·실패로 단정하지 않고 status 를 생략한다."""
    _send(db_session, status=status, result_code=result_code, cli_key=None)
    msg = api_get_thread(_TID, db=db_session)["data"]["messages"][-1]
    assert "status" not in msg


def test_inbound_message_shape_is_unchanged(db_session, sample_user):
    _send(db_session, status="DONE", result_code=_REPORT_FAIL, channel="RCS")
    _receive(db_session)
    messages = api_get_thread(_TID, db=db_session)["data"]["messages"]
    inbound = [m for m in messages if m["side"] == "them"]
    assert len(inbound) == 1
    assert set(inbound[0]) == {"id", "side", "kind", "text", "time"}
