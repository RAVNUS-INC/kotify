"""MMS MO 첨부(컨텐츠) 가져오기.

msghub 는 MO 웹훅에 첨부 정보(contentCnt·contentInfoLst)만 주고 파일은 GET /mo/v1/file/{moKey} 로 따로
받아야 한다. 컨텐츠는 7일만 보관되므로(19-mo) 받아서 DB 에 보관한다(받은 팩스와 같은 방식). 웹훅 응답 뒤
백그라운드로 바로 받고(fetch_new), 실패하면 재조정 루프가 간격을 늘려 가며 7일 안에서 다시 받는다
(fetch_pending). 단일 uvicorn 워커 전제(services.report.awaiting_record 와 같음).
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import MoMessage
from app.msghub.schemas import MsghubAuthError, MsghubBadRequest, MsghubError
from app.util.time import parse_mixed_ts

if TYPE_CHECKING:
    from app.msghub.client import MsghubClient
    from app.msghub.schemas import MoItem

log = logging.getLogger(__name__)

# 받은 팩스 PDF 상한(app.pbx.sftp.MAX_BYTES 20MB)보다 작게 — MMS MO 는 보통 수백 KB 다.
MAX_CONTENT_BYTES = 10 * 1024 * 1024
RETENTION = timedelta(days=7)
MAX_ATTEMPTS = 12
_MAX_BACKOFF = timedelta(hours=6)
_BATCH = 20

PENDING = "PENDING"
FETCHED = "FETCHED"
FAILED = "FAILED"
EXPIRED = "EXPIRED"


def initial_status(item: MoItem, mo_key: str) -> str | None:
    """새 MO 의 첨부 가져오기 상태. 첨부가 없거나 받을 키가 없으면 None.

    컨텐츠 조회 API 는 MMS MO(moLst) 용이다. RCS 양방향 MO 의 fileMessage 는 형식이 문서에 없어 받지 않는다.
    moKey 없이 만든 대체 키(syn-)로는 조회할 수 없다.
    """
    if item.is_rcs or item.content_cnt <= 0 or not item.mo_key or mo_key != item.mo_key:
        return None
    return PENDING


def _backoff(attempts: int) -> timedelta:
    return min(timedelta(minutes=2 ** max(attempts - 1, 0)), _MAX_BACKOFF)


def _expired(mo: MoMessage, now: datetime) -> bool:
    received = parse_mixed_ts(mo.received_at)
    if received is None:
        return False
    if received.tzinfo is None:
        received = received.replace(tzinfo=UTC)
    return now - received > RETENTION


async def _fetch_one(db: Session, client: MsghubClient, mo: MoMessage, now: datetime) -> None:
    if _expired(mo, now):
        mo.content_fetch_status = EXPIRED
        mo.content_error = "보관 기간(7일)이 지나 받을 수 없음"
        return
    mo.content_fetch_attempts = (mo.content_fetch_attempts or 0) + 1
    try:
        body, content_type = await client.fetch_mo_content(mo.mo_key, max_bytes=MAX_CONTENT_BYTES)
    except MsghubAuthError:
        mo.content_fetch_attempts -= 1  # 인증 장애는 이 MO 의 실패가 아니다
        raise
    except (MsghubError, httpx.HTTPError) as exc:
        permanent = isinstance(exc, MsghubBadRequest) and exc.code == "TOO_LARGE"
        mo.content_error = str(exc)[:200]
        if permanent or mo.content_fetch_attempts >= MAX_ATTEMPTS:
            mo.content_fetch_status = EXPIRED
        else:
            mo.content_fetch_status = FAILED
            mo.content_next_fetch_at = (now + _backoff(mo.content_fetch_attempts)).isoformat()
        log.warning("MO 첨부 가져오기 실패: mo_id=%s, 시도=%d, %s", mo.id, mo.content_fetch_attempts, exc)
        return
    mo.content_blob = body
    mo.content_type = content_type
    mo.content_size = len(body)
    mo.content_fetch_status = FETCHED
    mo.content_next_fetch_at = None
    mo.content_error = None


async def fetch_pending(
    db: Session, client: MsghubClient, *, ids: Iterable[int] | None = None, now: datetime | None = None,
) -> int:
    """받을 차례가 된 MO 첨부를 받아 보관한다. 받은 건수를 돌려준다.

    인증 오류면 멈추고 다음 주기에 다시 한다 — MO 마다 재인증하지 않게.
    """
    now = now or datetime.now(UTC)
    stmt = select(MoMessage).where(
        MoMessage.content_fetch_status.in_((PENDING, FAILED)),
        or_(MoMessage.content_next_fetch_at.is_(None), MoMessage.content_next_fetch_at <= now.isoformat()),
    )
    if ids is not None:
        stmt = stmt.where(MoMessage.id.in_(list(ids)))
    rows = db.execute(stmt.order_by(MoMessage.id).limit(_BATCH)).scalars().all()
    fetched = 0
    for mo in rows:
        try:
            await _fetch_one(db, client, mo, now)
        except MsghubAuthError:
            log.warning("MO 첨부 가져오기 중단 — msghub 인증 오류")
            db.commit()
            break
        db.commit()
        fetched += mo.content_fetch_status == FETCHED
    return fetched


async def fetch_new(mo_ids: list[int]) -> None:
    """웹훅 응답 뒤 방금 저장한 MO 의 첨부를 받는다 (BackgroundTask). 실패는 재조정 루프가 다시 한다."""
    from app.db import SessionLocal
    from app.main import aget_msghub_client

    client = await aget_msghub_client()
    if client is None:
        return
    db = SessionLocal()
    try:
        if await fetch_pending(db, client, ids=mo_ids):
            # 열린 대화방이 '받아 오는 중' 을 사진으로 바꾸게 알린다 (services.events).
            from app.services import events

            events.publish_throttled("message.new")
    except Exception:  # noqa: BLE001 — 웹훅 응답은 이미 나갔다. 재조정 루프가 다시 받는다.
        log.exception("MO 첨부 백그라운드 가져오기 실패")
    finally:
        db.close()
