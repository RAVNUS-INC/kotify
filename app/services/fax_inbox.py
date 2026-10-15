"""받은 팩스 — PBX 수신 로그 기록, 기존 수신 한 번 가져오기, PDF SFTP 가져오기.

- 수신 감지는 발송 추적과 같은 로그 커서 스캔(``fax.track_fax_jobs``)이 ``Incoming``
  로그를 넘겨 주면 ``record_incoming`` 이 행을 만든다(로그 ID 유일 — 중복 없음).
- 첫 배포 때 커서 이전에 이미 받은 팩스는 ``backfill`` 이 1번부터 커서까지 한 번 훑는다.
- PDF 는 ``fetch_pending`` 이 SFTP 로 가져온다. 실패는 다음 주기에 다시, 3번 실패하면
  ``FETCH_FAILED`` (관리자가 다시 가져오기 가능). PBX 에서 지워진 파일("File Removed")은
  ``NONE``.
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import FaxInbox
from app.pbx.client import PbxClient
from app.pbx.sftp import INBOX_FILE, SftpConfig, SftpError, fetch_inbox_pdf
from app.security.settings_store import SettingsStore

log = logging.getLogger(__name__)

MAX_FETCH_ATTEMPTS = 3
FETCH_BATCH = 5
BACKFILL_BATCH = 500
_BACKFILL_KEY = "pbx.fax_inbox_backfill_upto"

_SENDER_NUMBER = re.compile(r"<\s*\+?(\d+)\s*>")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def is_incoming(entry: dict) -> bool:
    return str(entry.get("type") or "").strip().lower() in ("incoming", "in", "receive", "received")


def sender_number(raw: object) -> str:
    """``"\\"0212345678\\" <0212345678>"`` → ``0212345678``. 괄호 안 번호 우선, 없으면 숫자 전체."""
    text = str(raw or "")
    found = _SENDER_NUMBER.findall(text)
    digits = found[-1] if found else "".join(c for c in text if c.isdigit())
    if digits.startswith("82") and len(digits) >= 11:
        digits = "0" + digits[2:]
    return digits


def _received_at(entry: dict) -> str:
    try:
        return datetime.fromtimestamp(int(entry.get("unix_date") or 0), UTC).isoformat()
    except (TypeError, ValueError, OverflowError):
        return _now()


def record_incoming(db: Session, log_id: int, entry: dict) -> FaxInbox | None:
    """수신 로그 1건을 기록한다. 이미 있으면 그대로 둔다. 커밋은 호출자가 한다."""
    existing = db.execute(select(FaxInbox).where(FaxInbox.pbx_log_id == log_id)).scalar_one_or_none()
    if existing is not None:
        return None
    status_text = str(entry.get("status") or "").strip().lower()
    file_name = str(entry.get("file") or "").strip()
    received = status_text == "received"
    has_file = bool(INBOX_FILE.fullmatch(file_name))
    row = FaxInbox(
        pbx_log_id=log_id,
        received_at=_received_at(entry),
        sender_number=sender_number(entry.get("sender")),
        status="RECEIVED" if received else "FAILED",
        error=None if received else (str(entry.get("error") or entry.get("status") or "").strip()[:200] or None),
        pbx_file=file_name[:200] or None,
        fetch_status="PENDING" if received and has_file else "NONE",
        fetch_attempts=0,
        created_at=_now(),
    )
    db.add(row)
    db.flush()
    return row


async def backfill(db: Session, client: PbxClient, *, upto: int) -> int:
    """커서 이전 수신 로그를 1번부터 한 번 훑는다. 진행 위치를 저장해 나눠서 끝낸다."""
    store = SettingsStore(db)
    done = int(store.get(_BACKFILL_KEY, "0") or "0")
    if upto <= done:
        return 0
    added = 0
    last = done
    for log_id in range(done + 1, min(upto, done + BACKFILL_BATCH) + 1):
        entry = await client.get_fax_log(log_id)
        last = log_id
        if entry is not None and is_incoming(entry) and record_incoming(db, log_id, entry):
            added += 1
    store.set(_BACKFILL_KEY, str(last), is_secret=False, updated_by=None)
    db.commit()
    return added


async def fetch_pending(db: Session, config: SftpConfig | None) -> int:
    """PDF 를 아직 못 가져온 받은 팩스를 SFTP 로 가져온다. 가져온 수를 반환."""
    if config is None:
        return 0
    rows = list(
        db.execute(
            select(FaxInbox)
            .where(FaxInbox.fetch_status == "PENDING", FaxInbox.fetch_attempts < MAX_FETCH_ATTEMPTS)
            .order_by(FaxInbox.id)
            .limit(FETCH_BATCH)
        ).scalars()
    )
    fetched = 0
    for row in rows:
        try:
            data = await fetch_inbox_pdf(config, row.pbx_file or "")
        except SftpError as exc:
            row.fetch_attempts += 1
            if exc.code == "bad_name" or row.fetch_attempts >= MAX_FETCH_ATTEMPTS:
                row.fetch_status = "FETCH_FAILED"
            db.commit()
            continue
        row.pdf_blob = data
        row.file_size_bytes = len(data)
        row.fetch_status = "FETCHED"
        row.fetch_attempts += 1
        db.commit()
        fetched += 1
    return fetched


def serialize(row: FaxInbox, *, name: str | None = None, viewer_name: str | None = None) -> dict:
    return {
        "id": row.id,
        "receivedAt": row.received_at,
        "senderNumber": row.sender_number,
        "senderName": name,
        "status": row.status,
        "error": row.error,
        "fetchStatus": row.fetch_status,
        "sizeBytes": row.file_size_bytes,
        "firstViewedAt": row.first_viewed_at,
        "firstViewedBy": viewer_name,
    }
