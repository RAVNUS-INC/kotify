"""웹훅 유실 대비 발송 결과 재조정 (C5).

배달 리포트는 웹훅에 100% 의존하므로, 웹훅이 유실되면(네트워크/콘솔 오설정/
배포 다운타임) 해당 Message 가 영구 PENDING/REG/ING 으로 남고 캠페인 비용·성공
집계가 갱신되지 않는다. 주기적으로 미완료 메시지를 msghub `query_sent` 로 능동
조회해 상태를 보정한다.

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
from app.services.report import process_sent_query

if TYPE_CHECKING:
    from app.msghub.client import MsghubClient

log = logging.getLogger(__name__)

_KST = ZoneInfo("Asia/Seoul")
_PENDING_STATUSES = ("PENDING", "REG", "ING")
_QUERY_BATCH = 10  # query_sent 1회 최대 10건 (msghub 제약)


def _req_dt_kst(sent_at_iso: str) -> str:
    """발송 시각(UTC ISO) → msghub reqDt 'YYYY-MM-DD' (KST 기준).

    TODO(확인 필요): query_sent 의 reqDt 가 KST 인지 UTC 인지 msghub 실측 확인.
    현재는 발송이 KST 기준이라 가정. 자정 근처 메시지는 ±1일 보정이 필요할 수 있다.
    """
    dt = datetime.fromisoformat(sent_at_iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(_KST).strftime("%Y-%m-%d")


async def reconcile_pending_messages(
    db: Session,
    client: MsghubClient,
    older_than_minutes: int = 10,
    max_messages: int = 200,
) -> int:
    """미완료 메시지를 msghub 에서 조회해 상태를 보정한다. 처리 건수 반환.

    Args:
        db: SQLAlchemy 세션.
        client: msghub 클라이언트.
        older_than_minutes: 발송 후 이 시간 이상 경과한 미완료 건만 대상
            (웹훅이 도착할 시간을 충분히 준 뒤 조회).
        max_messages: 1회 재조정 상한 (msghub 호출 폭주 방지).
    """
    cutoff = (datetime.now(UTC) - timedelta(minutes=older_than_minutes)).isoformat()

    rows = db.execute(
        select(Message.cli_key, MsghubRequest.sent_at)
        .join(MsghubRequest, Message.msghub_request_id == MsghubRequest.id)
        .where(
            Message.status.in_(_PENDING_STATUSES),
            Message.cli_key.is_not(None),
            MsghubRequest.sent_at < cutoff,
        )
        .limit(max_messages)
    ).all()

    if not rows:
        return 0

    total = 0
    for i in range(0, len(rows), _QUERY_BATCH):
        batch = rows[i : i + _QUERY_BATCH]
        cli_keys = [(r.cli_key, _req_dt_kst(r.sent_at)) for r in batch]
        try:
            raw_items = await client.query_sent(cli_keys)
        except Exception:
            log.exception("query_sent 실패 — 이 배치 skip (다음 주기 재시도)")
            continue
        processed = process_sent_query(db, raw_items)
        db.commit()
        total += processed

    if total:
        log.info("웹훅 재조정: 미완료 %d건 상태 보정", total)
    return total
