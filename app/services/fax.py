"""PBX 가상 팩스 발송과 결과 추적.

흐름:
1. ``create_job`` — 번호·PDF 검증 후 ``QUEUED`` 행을 만들고 **커밋**한다. PBX 가 발송
   요청 처리 중에 PDF 를 내려받으러 오므로, 그 전에 SQLite 쓰기 잠금을 놓아야 한다.
2. ``submit_job`` — 서명된 짧은 수명 URL 을 PBX 에 넘긴다. 접수되면 ``SUBMITTED``,
   명시적 거부는 ``FAILED``, 시간 초과·5xx 처럼 접수 여부를 모르면 ``UNKNOWN``.
   ``UNKNOWN`` 은 다시 보내지 않는다(이중 발송 방지).
3. ``track_fax_jobs`` — 주기 루프에서 PBX 팩스 로그(``/virtual_faxes/log/{id}``)를
   증가하는 ID 순으로 읽어 작업과 맞추고 최종 상태를 반영한다. 목록 API 가 없어
   마지막으로 확인한 로그 ID(``pbx.fax_log_cursor``)부터 앞으로 훑는다.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
import time
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import FaxJob
from app.pbx.client import PbxClient, PbxConfig, PbxError
from app.security.settings_store import SettingsStore

log = logging.getLogger(__name__)

MAX_PDF_BYTES = 10 * 1024 * 1024
RESOLUTIONS = ("standard", "medium", "high")
DEFAULT_RESOLUTION = "standard"
DEFAULT_RETRIES = 2
DEFAULT_RETRY_TIME = 300

# 회선 1개를 쓰는 G.711 팩스라 PBX 큐에 너무 많이 쌓지 않는다.
MAX_IN_FLIGHT = 3
# PBX 가 PDF 를 받아 갈 수 있는 시간과 횟수.
FETCH_URL_TTL_SECONDS = 10 * 60
MAX_FETCHES = 5
# 이 시간이 지나도 로그를 못 찾으면 UNKNOWN, 이보다 오래되면 추적을 그만둔다.
MATCH_DEADLINE = timedelta(hours=2)
TRACK_WINDOW = timedelta(hours=24)
# 한 주기에 새로 읽을 로그 수와, 빈 ID 를 몇 개까지 건너뛸지.
LOG_SCAN_BATCH = 20
LOG_SCAN_MISSES = 3
# 커서가 없을 때(첫 추적) 앞쪽의 빈 ID 를 얼마나 건너뛸지. 운영 PBX 는 실제 로그가
# 74번부터 시작했다(2026-10-15 실측, 1~73 은 빈 자리표시).
LOG_DISCOVERY_MISSES = 300

_RECIPIENT = re.compile(r"^0\d{8,10}$")
_SECRET_KEY = "pbx.fax_url_secret"
_CURSOR_KEY = "pbx.fax_log_cursor"

OPEN_STATUSES = ("QUEUED", "SUBMITTED", "UNKNOWN")


class FaxInputError(ValueError):
    """사용자 입력 오류. ``code`` 는 API 오류 코드."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.now(UTC)


def normalize_fax_number(raw: str) -> str | None:
    """국내 유선·휴대 번호(0 으로 시작 9~11자리)만 허용. 숫자만 남겨 반환."""
    digits = "".join(c for c in (raw or "") if c.isdigit())
    if digits.startswith("82") and len(digits) >= 11:
        digits = "0" + digits[2:]
    return digits if _RECIPIENT.fullmatch(digits) else None


def validate_pdf(raw: bytes) -> None:
    if not raw:
        raise FaxInputError("empty_file", "빈 파일입니다")
    if len(raw) > MAX_PDF_BYTES:
        raise FaxInputError("file_too_large", "PDF 는 최대 10MB 까지 보낼 수 있습니다")
    if not raw.lstrip()[:5] == b"%PDF-":
        raise FaxInputError("not_pdf", "PDF 파일만 보낼 수 있습니다")


def in_flight_count(db: Session) -> int:
    return int(
        db.execute(
            select(func.count()).select_from(FaxJob).where(
                FaxJob.status.in_(("QUEUED", "SUBMITTED"))
            )
        ).scalar_one()
    )


def create_job(
    db: Session,
    *,
    user_sub: str,
    recipient: str,
    filename: str,
    pdf: bytes,
    resolution: str,
) -> FaxJob:
    """입력을 검증하고 QUEUED 작업을 만든 뒤 커밋한다."""
    number = normalize_fax_number(recipient)
    if number is None:
        raise FaxInputError("invalid_recipient", "받는 팩스 번호를 확인하세요 (국내 번호, 숫자 9~11자리)")
    if resolution not in RESOLUTIONS:
        raise FaxInputError("invalid_resolution", "해상도는 standard·medium·high 중 하나입니다")
    validate_pdf(pdf)
    if in_flight_count(db) >= MAX_IN_FLIGHT:
        raise FaxInputError(
            "fax_busy", "보내는 중인 팩스가 많습니다. 앞선 팩스가 끝난 뒤 다시 보내세요"
        )
    job = FaxJob(
        created_by=user_sub,
        recipient=number,
        original_filename=(PurePosixPath(filename or "fax.pdf").name or "fax.pdf")[:200],
        pdf_blob=pdf,
        file_size_bytes=len(pdf),
        resolution=resolution,
        retries=DEFAULT_RETRIES,
        retry_time=DEFAULT_RETRY_TIME,
        status="QUEUED",
        fetch_count=0,
        created_at=_now().isoformat(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


# ── 서명 URL ────────────────────────────────────────────────────────────────


def _url_secret(db: Session) -> bytes:
    """PDF 내려받기 URL 서명 키. 없으면 만들어 암호화 저장한다."""
    store = SettingsStore(db)
    value = store.get(_SECRET_KEY)
    if not value:
        value = secrets.token_hex(32)
        store.set(_SECRET_KEY, value, is_secret=True, updated_by=None)
        db.commit()
    return value.encode("utf-8")


def _sign(secret: bytes, job_id: int, exp: int) -> str:
    return hmac.new(secret, f"fax:{job_id}:{exp}".encode(), hashlib.sha256).hexdigest()


def make_fetch_token(db: Session, job_id: int, *, now: float | None = None) -> str:
    exp = int((now if now is not None else time.time()) + FETCH_URL_TTL_SECONDS)
    return f"{job_id}.{exp}.{_sign(_url_secret(db), job_id, exp)}"


def read_fetch_token(db: Session, token: str, *, now: float | None = None) -> int | None:
    """서명·만료를 확인해 작업 id 를 돌려준다. 실패는 None."""
    parts = token.split(".")
    if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    job_id, exp = int(parts[0]), int(parts[1])
    if exp < (now if now is not None else time.time()):
        return None
    if not hmac.compare_digest(_sign(_url_secret(db), job_id, exp), parts[2]):
        return None
    return job_id


def fetch_pdf(db: Session, token: str) -> bytes | None:
    """PBX 의 PDF 내려받기. 열린 작업이고 횟수 상한 안일 때만 원본을 준다."""
    job_id = read_fetch_token(db, token)
    if job_id is None:
        return None
    job = db.get(FaxJob, job_id)
    if job is None or job.status not in ("QUEUED", "SUBMITTED") or job.fetch_count >= MAX_FETCHES:
        return None
    job.fetch_count += 1
    db.commit()
    return job.pdf_blob


# ── 발송 ───────────────────────────────────────────────────────────────────


async def submit_job(db: Session, job: FaxJob, config: PbxConfig) -> FaxJob:
    """PBX 에 발송을 요청하고 결과 상태를 저장한다."""
    if not config.fax_device_id or not config.fax_fetch_base_url:
        job.status = "FAILED"
        job.error = "PBX 팩스 장치 또는 kotify 내려받기 주소가 설정되지 않았습니다"
        job.completed_at = _now().isoformat()
        db.commit()
        return job

    token = make_fetch_token(db, job.id)
    url = f"{config.fax_fetch_base_url}/api/pbx/fax-files/{token}.pdf"
    try:
        data = await PbxClient(config).send_fax(
            config.fax_device_id,
            url=url,
            recipient=job.recipient,
            resolution=job.resolution,
            retries=job.retries,
            retry_time=job.retry_time,
        )
    except PbxError as exc:
        db.refresh(job)  # 요청 중 PDF 내려받기가 fetch_count 를 바꿨을 수 있다.
        if exc.uncertain:
            job.status = "UNKNOWN"
            job.error = "PBX 응답을 받지 못했습니다. 팩스 뷰어에서 결과를 확인하세요"
        else:
            job.status = "FAILED"
            job.error = f"PBX 가 발송을 거부했습니다 ({exc.code})"
            job.completed_at = _now().isoformat()
        db.commit()
        return job

    db.refresh(job)
    job.status = "SUBMITTED"
    job.submitted_at = _now().isoformat()
    pbx_file = data.get("file")
    job.pbx_file = PurePosixPath(pbx_file).name if isinstance(pbx_file, str) and pbx_file else None
    db.commit()
    return job


# ── 결과 추적 ───────────────────────────────────────────────────────────────


def map_log_status(status: object) -> str | None:
    """PBX 팩스 로그 상태 문구 → 최종 상태. 아직 진행 중이면 None."""
    text = str(status or "").strip().lower()
    if not text:
        return None
    if text in ("sent", "success", "successful", "done", "completed", "ok"):
        return "SENT"
    if any(word in text for word in ("fail", "error", "busy", "no answer", "cancel", "abort", "reject")):
        return "FAILED"
    return None


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _apply_log(job: FaxJob, log_id: int, entry: dict) -> None:
    job.pbx_log_id = log_id
    final = map_log_status(entry.get("status"))
    if final is None:
        if job.status == "UNKNOWN":
            job.status = "SUBMITTED"
        return
    job.status = final
    job.completed_at = _now().isoformat()
    if final == "FAILED":
        error = str(entry.get("error") or entry.get("status") or "").strip()
        job.error = error[:200] or "PBX 가 실패로 기록했습니다"
    else:
        job.error = None


def _match_job(entry: dict, jobs: list[FaxJob]) -> FaxJob | None:
    """로그 1건에 맞는 작업. 파일 이름이 우선, 없으면 번호+시각이 유일할 때만."""
    if str(entry.get("type") or "").lower() not in ("outgoing", "out", "send", "sent"):
        return None
    file_name = PurePosixPath(str(entry.get("file") or "")).name
    if file_name:
        for job in jobs:
            if job.pbx_file and job.pbx_file == file_name:
                return job
    recipient = "".join(c for c in str(entry.get("recipient") or "") if c.isdigit())
    try:
        logged_at = datetime.fromtimestamp(int(entry.get("unix_date") or 0), UTC)
    except (TypeError, ValueError, OverflowError):
        return None
    candidates = []
    for job in jobs:
        created = _parse_iso(job.created_at)
        if (
            job.pbx_log_id is None
            and recipient
            and job.recipient.endswith(recipient[-8:])
            and created is not None
            and created - timedelta(minutes=5) <= logged_at <= created + MATCH_DEADLINE
        ):
            candidates.append(job)
    return candidates[0] if len(candidates) == 1 else None


async def track_fax_jobs(db: Session, config: PbxConfig) -> int:
    """열린 작업의 PBX 로그를 찾아 상태를 갱신한다. 갱신한 작업 수를 반환."""
    now = _now()
    # 0) 발송 요청 도중 프로세스가 멈춰 QUEUED 로 남은 작업 — 접수 여부를 모른다.
    stale = list(
        db.execute(
            select(FaxJob).where(
                FaxJob.status == "QUEUED",
                FaxJob.created_at < (now - timedelta(seconds=FETCH_URL_TTL_SECONDS)).isoformat(),
            )
        ).scalars()
    )
    for job in stale:
        job.status = "UNKNOWN"
        job.error = "발송 요청 결과를 기록하지 못했습니다. 팩스 뷰어에서 확인하세요"
    if stale:
        db.commit()

    jobs = list(
        db.execute(
            select(FaxJob).where(
                FaxJob.status.in_(("SUBMITTED", "UNKNOWN")),
                FaxJob.created_at >= (now - TRACK_WINDOW).isoformat(),
            )
        ).scalars()
    )
    if not jobs:
        return len(stale)
    client = PbxClient(config)
    changed = len(stale)

    # 1) 이미 로그를 찾은 작업은 그 로그만 다시 읽는다(진행 중 → 최종 상태).
    for job in jobs:
        if job.pbx_log_id is None:
            continue
        entry = await client.get_fax_log(job.pbx_log_id)
        if entry:
            before = job.status
            _apply_log(job, job.pbx_log_id, entry)
            changed += int(job.status != before)

    # 2) 새 로그를 커서부터 앞으로 읽는다. 빈 ID 가 몇 개 이어지면 멈춘다.
    store = SettingsStore(db)
    cursor = int(store.get(_CURSOR_KEY, "0") or "0")
    unmatched = [job for job in jobs if job.pbx_log_id is None]
    misses = 0
    next_id = cursor + 1
    max_misses = LOG_SCAN_MISSES if cursor > 0 else LOG_DISCOVERY_MISSES
    # 읽기 상한은 시작할 때 한 번 정한다(첫 추적은 앞쪽 빈 ID 만큼 더 읽는다).
    budget = LOG_SCAN_BATCH + (LOG_DISCOVERY_MISSES if cursor == 0 else 0)
    reads = 0
    while unmatched and reads < budget:
        reads += 1
        entry = await client.get_fax_log(next_id)
        if entry is None:
            misses += 1
            if misses >= max_misses:
                break
            next_id += 1
            continue
        misses = 0
        cursor = next_id
        max_misses = LOG_SCAN_MISSES  # 실제 로그를 찾은 뒤에는 짧은 빈칸만 건너뛴다.
        job = _match_job(entry, unmatched)
        if job is not None:
            _apply_log(job, next_id, entry)
            unmatched.remove(job)
            changed += 1
        next_id += 1
    store.set(_CURSOR_KEY, str(cursor), is_secret=False, updated_by=None)

    # 3) 기한 안에 로그를 못 찾은 접수 작업은 UNKNOWN 으로 둔다.
    for job in unmatched:
        submitted = _parse_iso(job.submitted_at or job.created_at)
        if job.status == "SUBMITTED" and submitted and now - submitted > MATCH_DEADLINE:
            job.status = "UNKNOWN"
            job.error = "PBX 팩스 로그에서 결과를 찾지 못했습니다. 팩스 뷰어에서 확인하세요"
            changed += 1

    db.commit()
    return changed


def serialize_job(job: FaxJob, *, creator_name: str | None = None) -> dict:
    return {
        "id": job.id,
        "recipient": job.recipient,
        "filename": job.original_filename,
        "sizeBytes": job.file_size_bytes,
        "resolution": job.resolution,
        "status": job.status,
        "error": job.error,
        "createdAt": job.created_at,
        "submittedAt": job.submitted_at,
        "completedAt": job.completed_at,
        "createdBy": creator_name,
    }
