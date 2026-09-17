"""웹훅 유실 대비 발송 결과 재조정 (C5).

배달 리포트는 웹훅에 100% 의존하므로, 웹훅이 유실되면(네트워크/콘솔 오설정/
배포 다운타임) 해당 Message 가 영구 PENDING/REG/ING 으로 남고 캠페인 비용·성공
집계가 갱신되지 않는다. 주기적으로 미완료 메시지를 msghub `query_sent` 로 능동
조회해 상태를 보정한다.

청크 요청이 예외(응답 타임아웃 등)라 실패로 기록한 메시지(compose._record_failed_chunk)도
조회한다. msghub 가 실제로 접수했으면 그 리포트가 요청 응답을 기다리는 사이(행을 기록하기 전)
올 수 있다. 웹훅은 400 으로 재전송을 받지만(report.awaiting_record), msghub 의 재시도 횟수·중단
조건은 문서에 없어(간격 기본 10초·보관 72시간만 있다) 재전송이 끝내 오지 않을 수 있다.

`process_sent_query` 가 idempotent(이미 DONE 이면 skip)하므로 주기 중복 실행에
안전하다. 단일 uvicorn 워커(--workers 1) 전제이므로 lifespan 백그라운드 태스크가
중복 없이 단일 실행된다.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Message, MsghubRequest
from app.services import events
from app.services.report import process_sent_query
from app.util.time import parse_mixed_ts

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Row

    from app.msghub.client import MsghubClient

log = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")
# FB_PENDING: 양방향 실패 후 접수된 -fb 대체 SMS 의 리포트 대기 (routes.webhook._send_sms_fallback).
# 그 리포트 웹훅이 유실되면 다른 경로로는 확정되지 않는다.
_PENDING_STATUSES = ("PENDING", "REG", "ING", "FB_PENDING")
_QUERY_BATCH = 10  # query_sent 1회 최대 10건 (msghub 제약)
# 요청 예외로 실패 기록한 메시지는 발송(요청·예약) 시각부터 이 기간 안에서만 조회한다. 조회는 한 번
# 답을 받으면 끝나고(process_sent_query), 조회 자체가 계속 실패하는 경우(msghub 장애, 문서와 다른
# 응답)에도 호출이 끝없이 쌓이지 않게 하는 상한이다.
_FAILED_QUERY_WINDOW = timedelta(hours=24)


def _req_dt_kst(sent_at_iso: str) -> str:
    """발송 시각(UTC ISO) → msghub reqDt 'YYYY-MM-DD' (KST 기준).

    TODO(확인 필요): query_sent 의 reqDt 가 KST 인지 UTC 인지 msghub 실측 확인.
    현재는 발송이 KST 기준이라 가정. 자정 근처 메시지는 ±1일 보정이 필요할 수 있다.
    """
    dt = datetime.fromisoformat(sent_at_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(_KST).strftime("%Y-%m-%d")


def _query_req_dt(cli_key: str, status: str, report_dt: str | None, sent_at: str) -> str:
    """메시지의 현재 cliKey 를 msghub 에 요청한 날짜 (query_sent reqDt).

    FB_PENDING 행의 -fb cliKey 는 발송 요청(MsghubRequest.sent_at)이 아니라, 양방향 실패
    리포트를 처리하며 곧바로 보낸 대체 SMS 의 키다. 실패 리포트는 RCS 만료 등으로 날짜가
    바뀐 뒤에 오기도 하므로 그 리포트 시각(report_dt)의 날짜를 쓴다.
    """
    if status == "FB_PENDING" and cli_key.endswith("-fb"):
        dt = parse_mixed_ts(report_dt)
        if dt is not None:
            return dt.astimezone(_KST).strftime("%Y-%m-%d")
    return _req_dt_kst(sent_at)


async def reconcile_pending_messages(
    db: Session,
    client: MsghubClient,
    older_than_minutes: int = 10,
    max_messages: int = 200,
    max_failed_messages: int = 100,
) -> int:
    """미완료 메시지와 요청 예외로 실패 기록한 메시지를 msghub 에서 조회해 상태를 보정한다. 처리 건수 반환.

    요청 예외 실패는 미완료 조회를 마친 뒤 따로 고르고 따로 조회한다. 상한을 나눠 쓰면 실패 행이
    미완료 확정을 밀어내고, 같은 조회 요청에 섞으면 msghub 가 접수하지 않은 키 때문에 조회가 통째로
    거부될 때 미완료 확정까지 막힌다 — 그런 키의 응답은 문서에 없다(키별 상태 INVALID_KEY 로 보지만
    실측 전이다).

    Args:
        db: SQLAlchemy 세션.
        client: msghub 클라이언트.
        older_than_minutes: 발송 후 이 시간 이상 경과한 건만 대상
            (웹훅이 도착할 시간을 충분히 준 뒤 조회).
        max_messages: 미완료 메시지 1회 재조정 상한 (msghub 호출 폭주 방지).
        max_failed_messages: 요청 예외로 실패 기록한 메시지 1회 조회 상한.
    """
    now = datetime.now(UTC)
    cutoff = (now - timedelta(minutes=older_than_minutes)).isoformat()

    pending = db.execute(
        select(Message.cli_key, Message.status, Message.report_dt, MsghubRequest.sent_at)
        .join(MsghubRequest, Message.msghub_request_id == MsghubRequest.id)
        .where(
            Message.status.in_(_PENDING_STATUSES),
            Message.cli_key.is_not(None),
            MsghubRequest.sent_at < cutoff,
        )
        .limit(max_messages)
    ).all()
    settled = await _query_and_apply(db, client, pending)
    if settled:
        log.info("웹훅 재조정: 미완료 %d건 상태 보정", settled)

    # 요청 예외 실패 — compose._record_failed_chunk 가 남긴 행(응답 코드 없는 요청, result_code 없음)만.
    # 수신자 단위 거부(item 코드가 있는 FAILED)는 msghub 가 접수하지 않아 리포트가 오지 않으므로 조회하지
    # 않는다. 조회가 결과를 주지 않은(INVALID_KEY·OVER_DATE) 행은 result_code 에 그 답이 남아 다시 고르지 않는다.
    # 예약 요청의 sent_at 은 예약 시각이라, 예약이 실행되기 전엔 고르지 않는다.
    failed = db.execute(
        select(Message.cli_key, Message.status, Message.report_dt, MsghubRequest.sent_at)
        .join(MsghubRequest, Message.msghub_request_id == MsghubRequest.id)
        .where(
            Message.status == "FAILED",
            Message.result_code.is_(None),
            Message.cli_key.is_not(None),
            MsghubRequest.response_code.is_(None),
            MsghubRequest.error_body.is_not(None),
            MsghubRequest.sent_at < cutoff,
            MsghubRequest.sent_at >= (now - _FAILED_QUERY_WINDOW).isoformat(),
        )
        .order_by(Message.id)
        .limit(max_failed_messages)
    ).all()
    recovered = await _query_and_apply(db, client, failed)
    if recovered:
        log.warning(
            "웹훅 재조정: 요청 예외로 실패 기록한 %d건이 msghub 에서 결과가 확인돼 상태 보정", recovered,
        )
    return settled + recovered


async def _query_and_apply(db: Session, client: MsghubClient, rows: Sequence[Row]) -> int:
    """행들을 10건씩 query_sent 로 조회해 결과를 반영·커밋한다. 확정(DONE) 건수 반환."""
    total = 0
    try:
        for i in range(0, len(rows), _QUERY_BATCH):
            batch = rows[i : i + _QUERY_BATCH]
            cli_keys = [
                (r.cli_key, _query_req_dt(r.cli_key, r.status, r.report_dt, r.sent_at))
                for r in batch
            ]
            try:
                raw_items = await client.query_sent(cli_keys)
            except Exception:
                log.exception("query_sent 실패 — 이 배치 skip (다음 주기 재시도)")
                continue
            processed = process_sent_query(db, raw_items)
            db.commit()
            total += processed
    finally:
        if total:
            # 커밋된 배치 뒤 — 리포트 웹훅과 같은 이벤트·창으로 열린 대화방의 대기 라벨을
            # 갱신한다. 뒤 배치가 예외(DB 잠김 등)로 끊겨도 앞서 커밋된 확정분은 알린다 — 이미
            # DONE 이라 다음 주기엔 잡히지 않는다. REG→ING 같은 대기 안 이동은 total 에 안 잡힌다.
            # 미완료 확정과 요청 예외 실패 복구(reconcile_pending_messages 의 두 조회) 모두 여기서 알린다.
            events.publish_throttled("thread.updated")
    return total
