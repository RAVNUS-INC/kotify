"""고객 회신(MO) 첨부 이미지 — 수신 직후 통신사 서버에서 내려받아 DB 에 보관한다.

RCS 양방향 MO 의 contentInfo.fileMessage 는 ``{"fileMIMEType", "fileUrl"}`` 이고, fileUrl 은
SKT·KT·LG U+ 의 MaaP 서버 주소다(운영 확인 2026-10-16). msghub 문서는 MMS MO 컨텐츠 URL 을
"일회성, 24시간 유효"로 적고 RCS fileUrl 은 규정이 없어 같은 성격으로 본다. 그래서

- 웹훅 응답 직후 한 번 내려받고(BackgroundTask), 주기 작업이 남은 PENDING 을 줍는다.
- 같은 주소를 동시에 두 번 열지 않도록 PENDING→FETCHING 을 조건부 UPDATE 로 선점한다.
- 응답을 받은 4xx 는 만료·소진으로 보고 다시 시도하지 않는다(FAILED). 연결 실패·5xx 처럼
  주소를 쓰지 못했을 수 있는 경우만 MAX_FETCH_ATTEMPTS 까지 다시 시도한다.

주소는 외부(msghub 웹훅)에서 오므로 https·공인 IP 만 허용하고 크기를 제한한다(SSRF 방어).
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
from datetime import UTC, datetime, timedelta
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import MoMedia, MoMessage
from app.services import events

log = logging.getLogger(__name__)

MAX_FETCH_ATTEMPTS = 3
FETCH_BATCH = 5
MAX_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 3
_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_LOCK_TIMEOUT = timedelta(minutes=5)

# 대화방 목록·알림에서 본문 대신 쓰는 문구.
IMAGE_LABEL = "[사진]"
FILE_LABEL = "[첨부 파일]"


class _Retry(Exception):
    """주소를 쓰지 못했을 수 있는 실패 — 다시 시도한다."""


class _Fail(Exception):
    """다시 시도해도 안 되는 실패 — FAILED 로 남긴다."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def file_message(content_info_lst: str | None) -> dict | None:
    """저장된 contentInfo JSON → fileMessage({fileMIMEType, fileUrl}) 또는 None."""
    if not content_info_lst:
        return None
    try:
        info = json.loads(content_info_lst)
    except ValueError:
        return None
    fm = info.get("fileMessage") if isinstance(info, dict) else None
    if not isinstance(fm, dict):
        return None
    url = fm.get("fileUrl")
    return fm if isinstance(url, str) and url else None


def is_image_mime(mime: object) -> bool:
    return isinstance(mime, str) and mime.lower().startswith("image/")


def display_text(mo_msg: str | None, content_info_lst: str | None) -> str:
    """회신 본문 — 글 없이 파일만 온 회신은 [사진]/[첨부 파일] 로 대신한다."""
    if mo_msg:
        return mo_msg
    fm = file_message(content_info_lst)
    if fm is None:
        return ""
    return IMAGE_LABEL if is_image_mime(fm.get("fileMIMEType")) else FILE_LABEL


def record_for(db: Session, mo: MoMessage) -> MoMedia | None:
    """새로 저장한 회신에 파일이 있으면 mo_media 행을 만든다(flush 는 호출자 몫)."""
    fm = file_message(mo.content_info_lst)
    if fm is None:
        return None
    mime = fm.get("fileMIMEType") if isinstance(fm.get("fileMIMEType"), str) else None
    row = MoMedia(
        mo_id=mo.id,
        declared_mime=mime,
        fetch_status="PENDING" if is_image_mime(mime) else "UNSUPPORTED",
        fetch_attempts=0,
        created_at=_now(),
    )
    db.add(row)
    return row


def sniff_image(data: bytes) -> str | None:
    """파일 앞부분으로 브라우저가 그릴 수 있는 이미지 형식을 고른다. 통신사 헤더는 믿지 않는다."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:2] == b"BM":
        return "image/bmp"
    return None


async def _check_public_https(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise _Fail("https 주소가 아님")
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            parts.hostname, parts.port or 443, type=socket.SOCK_STREAM
        )
    except OSError as exc:
        raise _Retry(f"이름 해석 실패: {type(exc).__name__}") from exc
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise _Fail("공인 주소가 아님")


async def download(url: str, client: httpx.AsyncClient) -> bytes:
    """주소를 한 번 내려받는다. 리다이렉트는 매 단계 주소를 다시 검사한다."""
    for _ in range(MAX_REDIRECTS + 1):
        await _check_public_https(url)
        try:
            async with client.stream("GET", url) as resp:
                if resp.is_redirect and resp.headers.get("location"):
                    url = urljoin(url, resp.headers["location"])
                    continue
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise _Retry(f"HTTP {resp.status_code}")
                if resp.status_code != 200:
                    raise _Fail(f"HTTP {resp.status_code}")
                declared = resp.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > MAX_BYTES:
                    raise _Fail("크기 초과")
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > MAX_BYTES:
                        raise _Fail("크기 초과")
                return bytes(body)
        except httpx.HTTPError as exc:
            raise _Retry(type(exc).__name__) from exc
    raise _Fail("리다이렉트 초과")


def _claim(db: Session, row_id: int) -> bool:
    """PENDING 행을 FETCHING 으로 선점한다. 이미 누가 가져갔으면 False."""
    result = db.execute(
        update(MoMedia)
        .where(MoMedia.id == row_id, MoMedia.fetch_status == "PENDING")
        .values(
            fetch_status="FETCHING",
            locked_at=_now(),
            fetch_attempts=MoMedia.fetch_attempts + 1,
        )
    )
    db.commit()
    return result.rowcount == 1


async def _fetch_one(db: Session, row_id: int, client: httpx.AsyncClient) -> None:
    if not _claim(db, row_id):
        return
    row = db.get(MoMedia, row_id)
    mo = db.get(MoMessage, row.mo_id) if row else None
    if row is None or mo is None:
        return
    fm = file_message(mo.content_info_lst)
    try:
        if fm is None:
            raise _Fail("fileUrl 없음")
        data = await download(fm["fileUrl"], client)
        content_type = sniff_image(data)
        if content_type is None:
            raise _Fail("지원하지 않는 형식")
    except _Retry as exc:
        row.fetch_status = "PENDING" if row.fetch_attempts < MAX_FETCH_ATTEMPTS else "FAILED"
        row.error = str(exc)
    except _Fail as exc:
        row.fetch_status = "FAILED"
        row.error = str(exc)
    else:
        row.fetch_status = "FETCHED"
        row.content_type = content_type
        row.content_blob = data
        row.file_size_bytes = len(data)
        row.fetched_at = _now()
        row.error = None
    row.locked_at = None
    db.commit()
    if row.fetch_status != "FETCHED":
        # 주소에는 통신사 파일 키가 있어 남기지 않는다.
        log.warning("회신 이미지 가져오기 %s: mo_media=%d (%s)", row.fetch_status, row.id, row.error)


async def fetch_pending(
    db: Session, *, ids: list[int] | None = None, client: httpx.AsyncClient | None = None
) -> int:
    """PENDING 이미지를 가져온다. ids 를 주면 그 행만. 가져온(FETCHED) 건수를 돌려준다."""
    stale = (datetime.now(UTC) - _LOCK_TIMEOUT).isoformat()
    # 프로세스가 죽어 FETCHING 에 남은 행은 다시 차례를 준다(시도 횟수는 이미 늘어 있다).
    db.execute(
        update(MoMedia)
        .where(MoMedia.fetch_status == "FETCHING", MoMedia.locked_at < stale)
        .values(
            fetch_status=case(
                (MoMedia.fetch_attempts < MAX_FETCH_ATTEMPTS, "PENDING"), else_="FAILED"
            ),
            locked_at=None,
            error="가져오는 중 중단됨",
        )
    )
    db.commit()

    query = select(MoMedia.id).where(MoMedia.fetch_status == "PENDING").order_by(MoMedia.id)
    if ids is not None:
        query = query.where(MoMedia.id.in_(ids))
    else:
        query = query.limit(FETCH_BATCH)
    row_ids = list(db.scalars(query))
    if not row_ids:
        return 0

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False)
    try:
        for row_id in row_ids:
            await _fetch_one(db, row_id, client)
    finally:
        if owns_client:
            await client.aclose()
    finished = dict(
        db.execute(
            select(MoMedia.fetch_status, func.count())
            .where(MoMedia.id.in_(row_ids), MoMedia.fetch_status.in_(("FETCHED", "FAILED")))
            .group_by(MoMedia.fetch_status)
        ).all()
    )
    if finished:
        # 열린 대화방이 '불러오는 중' 말풍선을 사진이나 실패 문구로 바꾸도록 다시 불러오게 한다.
        try:
            events.publish_throttled("message.new")
        except Exception:  # noqa: BLE001
            log.debug("SSE 이벤트 발행 실패(무시)", exc_info=True)
    return finished.get("FETCHED", 0)


async def fetch_new(ids: list[int]) -> None:
    """웹훅 응답 직후 BackgroundTask — 요청 세션이 닫힌 뒤라 새 세션을 연다."""
    db = SessionLocal()
    try:
        await fetch_pending(db, ids=ids)
    except Exception:  # noqa: BLE001 — 남은 행은 주기 작업이 다시 줍는다.
        log.exception("회신 이미지 가져오기 실패")
    finally:
        db.close()


def statuses(db: Session, mo_ids: list[int]) -> dict[int, str]:
    """mo_id → fetch_status. 본문(BLOB)은 읽지 않는다."""
    if not mo_ids:
        return {}
    out: dict[int, str] = {}
    for i in range(0, len(mo_ids), 500):
        chunk = mo_ids[i : i + 500]
        rows = db.execute(
            select(MoMedia.mo_id, MoMedia.fetch_status).where(MoMedia.mo_id.in_(chunk))
        ).all()
        out.update((mo_id, status) for mo_id, status in rows)
    return out
