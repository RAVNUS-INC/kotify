"""사내 PBX 연동 API — 팩스 발송, 통화 기록, 녹음 재생.

- GET  /fax                       : 팩스 이력 (sender 는 본인 것, admin 은 전체)
- POST /fax                       : 팩스 발송 (sender 이상, multipart)
- POST /fax/{id}/resend           : 같은 PDF·번호로 새 작업 (본인 또는 admin)
- GET  /fax/{id}/pdf              : 보낸 PDF 보기 (본인 또는 admin)
- GET  /fax/inbox                 : 받은 팩스 목록 (sender 이상, 실패 수신 포함)
- GET  /fax/inbox/{id}/pdf        : 받은 팩스 PDF 보기 (sender 이상, 감사 로그·첫 열람 기록)
- POST /fax/inbox/{id}/refetch    : PBX 에서 PDF 다시 가져오기 (admin)
- GET  /pbx/calls                 : 통화 기록 (sender 이상, 번호 없는 전체 조회는 admin, cursor 페이지)
- GET  /pbx/recordings/{token}    : 녹음 스트리밍 (sender 이상, 토큰 발급 사용자만)
- POST /pbx/test                  : 연결 테스트 (admin)
- GET  /pbx/fax-files/{token}.pdf : **PBX 전용** PDF 내려받기 — 로그인 없음, 서명 토큰으로만

녹음 경로·전화번호는 로그에 남기지 않는다. 브라우저는 녹음 원본 주소를 받지 않는다.
"""
from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import (
    SEND_ROLES,
    require_role,
    require_sender,
    require_setup_complete,
    require_user,
    user_has_role,
)
from app.db import get_db
from app.models import FaxInbox, FaxJob, User
from app.pbx.client import (
    PbxClient,
    PbxConfig,
    PbxError,
    PbxNotConfigured,
    require_pbx_config,
)
from app.pbx.sftp import load_sftp_config
from app.security.csrf import verify_csrf
from app.services import audit
from app.services import calls as calls_service
from app.services import fax as fax_service
from app.services import fax_inbox as inbox_service

log = logging.getLogger(__name__)

router = APIRouter(
    dependencies=[Depends(require_user), Depends(require_setup_complete)],
)
# PBX 가 팩스 PDF 를 받아 가는 경로 — 세션이 없으므로 서명 토큰만으로 보호한다.
public_router = APIRouter()

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _error(code: str, message: str, status: int) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def _not_configured() -> JSONResponse:
    return _error("pbx_not_configured", "전화 교환기(PBX) 연동이 설정되지 않았습니다", 409)


def _pbx_failed(exc: PbxError) -> JSONResponse:
    return _error("pbx_error", f"전화 교환기 응답 오류 ({exc.code})", 502)


def _can_see_job(user: User, job: FaxJob) -> bool:
    return job.created_by == user.sub or user_has_role(user, "admin")


def _creator_names(db: Session, jobs: list[FaxJob]) -> dict[str, str]:
    subs = {job.created_by for job in jobs}
    if not subs:
        return {}
    users = db.execute(select(User).where(User.sub.in_(subs))).scalars()
    return {u.sub: (u.display_name or u.name or "") for u in users}


# ── 팩스 ───────────────────────────────────────────────────────────────────


@router.get("/fax", dependencies=[Depends(require_sender)])
def list_fax_jobs(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    stmt = select(FaxJob).order_by(FaxJob.id.desc())
    if not user_has_role(user, "admin"):
        stmt = stmt.where(FaxJob.created_by == user.sub)
    jobs = list(db.execute(stmt.offset(offset).limit(limit + 1)).scalars())
    has_more = len(jobs) > limit
    jobs = jobs[:limit]
    names = _creator_names(db, jobs)
    return {
        "data": [fax_service.serialize_job(j, creator_name=names.get(j.created_by)) for j in jobs],
        "meta": {"limit": limit, "offset": offset, "hasMore": has_more},
    }


async def _send(
    db: Session, user: User, job: FaxJob, config: PbxConfig, request: Request
) -> dict:
    job = await fax_service.submit_job(db, job, config)
    audit.log(
        db,
        actor_sub=user.sub,
        action=audit.FAX_SEND,
        target=f"fax:{job.id}",
        detail={"status": job.status},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return {"data": fax_service.serialize_job(job, creator_name=user.display_name or user.name)}


@router.post(
    "/fax",
    dependencies=[Depends(require_sender), Depends(verify_csrf)],
    response_model=None,
)
async def send_fax(
    request: Request,
    recipient: str = Form(...),
    resolution: str = Form(fax_service.DEFAULT_RESOLUTION),
    file: UploadFile = File(...),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    try:
        config = require_pbx_config(db)
    except PbxNotConfigured:
        return _not_configured()
    raw = await file.read(fax_service.MAX_PDF_BYTES + 1)
    try:
        job = fax_service.create_job(
            db,
            user_sub=user.sub,
            recipient=recipient,
            filename=file.filename or "fax.pdf",
            pdf=raw,
            resolution=resolution,
        )
    except fax_service.FaxInputError as exc:
        status = {"fax_busy": 409, "file_too_large": 413}.get(exc.code, 400)
        return _error(exc.code, str(exc), status)
    return await _send(db, user, job, config, request)


@router.post(
    "/fax/{job_id}/resend",
    dependencies=[Depends(require_sender), Depends(verify_csrf)],
    response_model=None,
)
async def resend_fax(
    job_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    original = db.get(FaxJob, job_id)
    if original is None or not _can_see_job(user, original):
        return _error("not_found", "팩스를 찾을 수 없습니다", 404)
    try:
        config = require_pbx_config(db)
    except PbxNotConfigured:
        return _not_configured()
    try:
        job = fax_service.create_job(
            db,
            user_sub=user.sub,
            recipient=original.recipient,
            filename=original.original_filename,
            pdf=original.pdf_blob,
            resolution=original.resolution,
        )
    except fax_service.FaxInputError as exc:
        return _error(exc.code, str(exc), 409 if exc.code == "fax_busy" else 400)
    return await _send(db, user, job, config, request)


# ── 받은 팩스 ───────────────────────────────────────────────────────────────
# /fax/{job_id} 경로보다 먼저 등록해야 "inbox" 가 job_id 로 해석되지 않는다.


@router.get("/fax/inbox", dependencies=[Depends(require_sender)], response_model=None)
async def list_fax_inbox(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    rows = list(
        db.execute(
            select(FaxInbox)
            .order_by(FaxInbox.received_at.desc(), FaxInbox.id.desc())
            .offset(offset)
            .limit(limit + 1)
        ).scalars()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    # 하이웍스 조회는 동기 MySQL — 이벤트 루프를 막지 않게 스레드에서.
    names = await run_in_threadpool(
        calls_service.lookup_display_names, db, [r.sender_number for r in rows]
    )
    viewers = {r.first_viewed_by for r in rows if r.first_viewed_by}
    viewer_names: dict[str, str] = {}
    if viewers:
        viewer_names = {
            u.sub: (u.display_name or u.name or "")
            for u in db.execute(select(User).where(User.sub.in_(viewers))).scalars()
        }
    unread = db.execute(
        select(func.count()).select_from(FaxInbox).where(
            FaxInbox.status == "RECEIVED", FaxInbox.first_viewed_at.is_(None)
        )
    ).scalar_one()
    return {
        "data": [
            inbox_service.serialize(
                r,
                name=names.get(r.sender_number),
                viewer_name=viewer_names.get(r.first_viewed_by or ""),
            )
            for r in rows
        ],
        "meta": {"limit": limit, "offset": offset, "hasMore": has_more, "unread": int(unread)},
    }


@router.get("/fax/inbox/{inbox_id}/pdf", dependencies=[Depends(require_sender)], response_model=None)
def view_fax_inbox_pdf(
    inbox_id: int,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    row = db.get(FaxInbox, inbox_id)
    if row is None:
        return _error("not_found", "받은 팩스를 찾을 수 없습니다", 404)
    if row.pdf_blob is None:
        return _error("not_fetched", "아직 PBX 에서 PDF 를 가져오지 못했습니다", 409)
    if row.first_viewed_at is None:
        row.first_viewed_at = datetime.now(UTC).isoformat()
        row.first_viewed_by = user.sub
    audit.log(
        db,
        actor_sub=user.sub,
        action=audit.FAX_INBOX_VIEW,
        target=f"fax_inbox:{row.id}",
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return Response(
        content=row.pdf_blob,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="fax-in-{row.id}.pdf"',
            "Cache-Control": "private, no-store",
        },
    )


@router.post(
    "/fax/inbox/{inbox_id}/refetch",
    dependencies=[Depends(require_role("admin")), Depends(verify_csrf)],
    response_model=None,
)
async def refetch_fax_inbox(
    inbox_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    row = db.get(FaxInbox, inbox_id)
    if row is None:
        return _error("not_found", "받은 팩스를 찾을 수 없습니다", 404)
    if row.status != "RECEIVED" or not row.pbx_file:
        return _error("no_file", "가져올 PDF 가 없는 수신 기록입니다", 409)
    config = load_sftp_config(db)
    if config is None:
        return _error("sftp_not_configured", "PBX 팩스 파일 가져오기(SFTP)가 설정되지 않았습니다", 409)
    row.fetch_status = "PENDING"
    row.fetch_attempts = 0
    audit.log(db, actor_sub=user.sub, action=audit.FAX_INBOX_REFETCH, target=f"fax_inbox:{row.id}")
    db.commit()
    await inbox_service.fetch_pending(db, config)
    db.refresh(row)
    return {"data": inbox_service.serialize(row)}


@router.get("/fax/{job_id}/pdf", dependencies=[Depends(require_sender)], response_model=None)
def view_fax_pdf(
    job_id: int,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    job = db.get(FaxJob, job_id)
    if job is None or not _can_see_job(user, job):
        return _error("not_found", "팩스를 찾을 수 없습니다", 404)
    return Response(
        content=job.pdf_blob,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="fax-{job.id}.pdf"',
            "Cache-Control": "private, no-store",
        },
    )


@public_router.get("/pbx/fax-files/{token}.pdf", response_model=None)
def pbx_fetch_fax_pdf(token: str, db: Session = Depends(get_db)) -> Response:
    """PBX 가 팩스 발송 요청 처리 중에 호출한다. 실패 사유와 무관하게 404."""
    pdf = fax_service.fetch_pdf(db, token)
    if pdf is None:
        return Response(status_code=404)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Cache-Control": "no-store"},
    )


# ── 통화 기록 ───────────────────────────────────────────────────────────────


@router.get("/pbx/calls", dependencies=[Depends(require_sender)], response_model=None)
async def list_calls(
    phone: str | None = Query(None, max_length=32),
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
    call_type: Literal["in", "out", "internal", "transit"] | None = Query(None, alias="type"),
    limit: int = Query(50, ge=1, le=calls_service.MAX_LIMIT),
    cursor: str | None = Query(None, max_length=1200),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    digits = "".join(c for c in (phone or "") if c.isdigit())
    if phone is not None and not digits:
        return _error("invalid_phone", "번호를 확인하세요", 400)
    if not digits and not user_has_role(user, "admin"):
        return _error("forbidden", "번호 없이 전체 통화 기록은 관리자만 볼 수 있습니다", 403)
    dates: list[date | None] = []
    for value in (date_from, date_to):
        if value is None or value == "":
            dates.append(None)
            continue
        try:
            if not _DATE.fullmatch(value):
                raise ValueError(value)
            dates.append(date.fromisoformat(value))
        except ValueError:
            return _error("invalid_date", "날짜는 YYYY-MM-DD 형식입니다", 400)
    if dates[0] and dates[1] and dates[0] > dates[1]:
        return _error("invalid_date", "시작일이 종료일보다 늦습니다", 400)
    try:
        config = require_pbx_config(db)
    except PbxNotConfigured:
        return _not_configured()
    try:
        result = await calls_service.list_calls(
            config,
            user_sub=user.sub,
            phone=digits or None,
            date_from=dates[0],
            date_to=dates[1],
            call_type=call_type,
            limit=limit,
            cursor=cursor or None,
        )
    except ValueError:
        return _error("invalid_cursor", "페이지 정보가 올바르지 않습니다. 처음부터 다시 조회하세요", 400)
    except PbxError as exc:
        return _pbx_failed(exc)
    # 하이웍스 조회는 동기 MySQL(최대 수 초) — 이벤트 루프를 막지 않게 스레드에서.
    await run_in_threadpool(calls_service.attach_names, db, result["data"])
    return result


def _is_first_range(range_header: str | None) -> bool:
    """재생 시작 요청인지 — 탐색(Range bytes=N-)마다 감사 로그가 쌓이지 않게."""
    if not range_header:
        return True
    return range_header.replace(" ", "").lower().startswith("bytes=0-")


@router.get(
    "/pbx/recordings/{token}",
    dependencies=[Depends(require_role(*SEND_ROLES))],
    response_model=None,
)
async def play_recording(
    token: str,
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Response:
    ref = calls_service.read_recording_token(token, user.sub)
    if ref is None:
        return _error("not_found", "녹음을 찾을 수 없거나 링크가 만료되었습니다. 목록을 새로 불러오세요", 404)
    try:
        config = require_pbx_config(db)
    except PbxNotConfigured:
        return _not_configured()

    range_header = request.headers.get("range")
    try:
        upstream, body = await PbxClient(config).open_recording(ref.path, range_header)
    except PbxError as exc:
        if exc.status_code == 404:
            return _error("not_found", "녹음 파일이 PBX 에 없습니다", 404)
        return _pbx_failed(exc)

    if _is_first_range(range_header):
        audit.log(
            db,
            actor_sub=user.sub,
            action=audit.RECORDING_PLAY,
            target=f"cdr:{ref.cdr_id}",
            ip=request.client.host if request.client else None,
        )
        db.commit()

    content_type = upstream.headers.get("content-type", "")
    if not content_type.startswith("audio/"):
        content_type = "audio/wav" if ref.path.lower().endswith(".wav") else "application/octet-stream"
    headers = {
        "Cache-Control": "private, no-store",
        "Content-Disposition": "inline",
        "Accept-Ranges": "bytes",
    }
    for name in ("content-length", "content-range"):
        if name in upstream.headers:
            headers[name.title()] = upstream.headers[name]
    return StreamingResponse(
        body, status_code=upstream.status_code, media_type=content_type, headers=headers,
    )


# ── 설정 ───────────────────────────────────────────────────────────────────


@router.post(
    "/pbx/test",
    dependencies=[Depends(require_role("admin")), Depends(verify_csrf)],
    response_model=None,
)
async def test_pbx(db: Session = Depends(get_db)) -> dict | JSONResponse:
    """CDR 조회와 팩스 장치 조회가 되는지 확인한다. 장치 secret·번호는 버린다."""
    try:
        config = require_pbx_config(db)
    except PbxNotConfigured:
        return _not_configured()
    client = PbxClient(config)
    try:
        await client.list_cdr({"limit": "1"})
    except PbxError as exc:
        return _error("connect_failed", f"통화 기록 조회 실패 ({exc.code})", 422)
    if not config.fax_device_id:
        return {"data": {"ok": True, "message": "연결 성공 · 팩스 장치 미설정"}}
    try:
        device = await client.get_fax_device(config.fax_device_id)
    except PbxError as exc:
        return _error("connect_failed", f"통화 기록은 조회됨 · 팩스 장치 조회 실패 ({exc.code})", 422)
    name = str(device.get("description") or "").strip()[:60] or f"#{config.fax_device_id}"
    return {"data": {"ok": True, "message": f"연결 성공 · 팩스 장치 {name}"}}
