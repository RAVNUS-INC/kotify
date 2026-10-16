"""고객 회신(MO) 첨부 — 받아서 DB 에 보관한다 (mo_media).

받는 곳은 두 가지다(mo_media.source).
- RCS_URL: RCS 양방향 MO 의 contentInfo.fileMessage ``{"fileMIMEType", "fileUrl"}``. fileUrl 은 SKT·KT·
  LG U+ 의 MaaP 서버 주소다(운영 확인 2026-10-16). 규정이 없어 msghub MMS MO 컨텐츠 URL("일회성, 24시간
  유효")과 같은 성격으로 본다. 이미지만 받고 그 밖은 UNSUPPORTED. 주소가 외부(msghub 웹훅)에서 오므로
  https·공인 IP 만 허용하고 크기를 제한한다(SSRF 방어).
- MMS_API: MMS MO(contentCnt>0) — msghub GET /mo/v1/file/{moKey}(19-mo). msghub 가 7일 보관한다.
  이미지가 아니어도 받아 두고 화면은 내려받기로만 준다.

공통:
- 웹훅 응답 직후 한 번 받고(BackgroundTask), 60초 주기 작업이 남은 PENDING 을 줍는다.
- 같은 행을 동시에 두 번 받지 않도록 PENDING→FETCHING 을 조건부 UPDATE 로 선점한다.
- 다시 받아도 안 되는 실패는 FAILED, 일시 실패는 1·2·4…분(최대 6시간) 뒤 다시 시도하고 source 별 횟수
  (RCS 3회, MMS 12회)를 넘으면 FAILED. MMS 는 받은 지 7일이 지나면 FAILED.
- 한 건은 ROW_TIMEOUT 안에 끝낸다 — 같은 주기의 재조정·팩스 추적을 오래 막지 않게.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import socket
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit

import httpx
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import MoMedia, MoMessage
from app.msghub.schemas import MsghubAuthError, MsghubBadRequest, MsghubError
from app.services import events
from app.util.time import parse_mixed_ts

if TYPE_CHECKING:
    from app.msghub.client import MsghubClient

log = logging.getLogger(__name__)

RCS_URL = "RCS_URL"
MMS_API = "MMS_API"

MAX_FETCH_ATTEMPTS = {RCS_URL: 3, MMS_API: 12}
MMS_RETENTION = timedelta(days=7)
FETCH_BATCH = 5
MAX_BYTES = 10 * 1024 * 1024
MAX_REDIRECTS = 3
ROW_TIMEOUT = 60.0
_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_LOCK_TIMEOUT = timedelta(minutes=5)
_MAX_BACKOFF = timedelta(hours=6)

# 대화방 목록·알림에서 본문 대신 쓰는 문구.
IMAGE_LABEL = "[사진]"
FILE_LABEL = "[첨부 파일]"

# MMS contentInfoLst[].contentExt → 형식. 받기 전 화면이 사진인지 파일인지 미리 보이는 데만 쓴다.
_IMAGE_EXT = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
              "bmp": "image/bmp", "webp": "image/webp"}


class _Retry(Exception):
    """일시 실패 — 간격을 두고 다시 시도한다."""


class _Fail(Exception):
    """다시 시도해도 안 되는 실패 — FAILED 로 남긴다."""


class _Stop(Exception):
    """이 행 탓이 아닌 실패(msghub 인증 장애) — 선점을 풀고 이번 주기를 멈춘다."""


def _now() -> datetime:
    return datetime.now(UTC)


def file_message(content_info_lst: str | None) -> dict | None:
    """저장된 contentInfo JSON → RCS fileMessage({fileMIMEType, fileUrl}) 또는 None."""
    info = _load(content_info_lst)
    fm = info.get("fileMessage") if isinstance(info, dict) else None
    if not isinstance(fm, dict):
        return None
    url = fm.get("fileUrl")
    return fm if isinstance(url, str) and url else None


def _load(content_info_lst: str | None) -> object:
    if not content_info_lst:
        return None
    try:
        return json.loads(content_info_lst)
    except ValueError:
        return None


def mms_declared_mime(content_info_lst: str | None) -> str | None:
    """MMS contentInfoLst 첫 항목의 확장자로 짐작한 이미지 형식. 모르면 None."""
    info = _load(content_info_lst)
    first = info[0] if isinstance(info, list) and info else None
    ext = first.get("contentExt") if isinstance(first, dict) else None
    return _IMAGE_EXT.get(ext.lower().lstrip(".")) if isinstance(ext, str) else None


def is_image_mime(mime: object) -> bool:
    return isinstance(mime, str) and mime.lower().startswith("image/")


def _is_mms_with_content(mo: MoMessage) -> bool:
    return (mo.content_cnt or 0) > 0 and bool(mo.mo_key) and not mo.mo_key.startswith("syn-")


def display_text(mo_msg: str | None, content_info_lst: str | None, content_cnt: int = 0) -> str:
    """회신 본문 — 글 없이 파일만 온 회신은 [사진]/[첨부 파일] 로 대신한다(RCS·MMS)."""
    if mo_msg:
        return mo_msg
    fm = file_message(content_info_lst)
    if fm is not None:
        return IMAGE_LABEL if is_image_mime(fm.get("fileMIMEType")) else FILE_LABEL
    if content_cnt > 0:
        return IMAGE_LABEL if mms_declared_mime(content_info_lst) else FILE_LABEL
    return ""


def record_for(db: Session, mo: MoMessage) -> MoMedia | None:
    """새로 저장한 회신에 파일이 있으면 mo_media 행을 만든다(flush 는 호출자 몫)."""
    fm = file_message(mo.content_info_lst)
    if fm is not None:
        mime = fm.get("fileMIMEType") if isinstance(fm.get("fileMIMEType"), str) else None
        row = MoMedia(
            mo_id=mo.id, source=RCS_URL, declared_mime=mime,
            fetch_status="PENDING" if is_image_mime(mime) else "UNSUPPORTED",
            fetch_attempts=0, created_at=_now().isoformat(),
        )
    elif _is_mms_with_content(mo):
        row = MoMedia(
            mo_id=mo.id, source=MMS_API, declared_mime=mms_declared_mime(mo.content_info_lst),
            fetch_status="PENDING", fetch_attempts=0, created_at=_now().isoformat(),
        )
    else:
        return None
    db.add(row)
    return row


def sniff_image(data: bytes) -> str | None:
    """파일 앞부분으로 브라우저가 그릴 수 있는 이미지 형식을 고른다. 받은 헤더는 믿지 않는다."""
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
    """RCS 주소를 한 번 내려받는다. 리다이렉트는 매 단계 주소를 다시 검사한다.

    401·403 은 인증 없이 받는 방식이 막힌 것일 수 있어(문서에 규정 없음, 실주소로 받아 본 적 없음)
    바로 FAILED 로 닫지 않고 '인증 거부' 로 구분해 다시 시도한다 — 배포 뒤 집계로 확인하고 방법을 바꾼 뒤
    다시 PENDING 으로 돌릴 수 있게(deploy/README "회신 첨부 보관 0026").
    """
    for _ in range(MAX_REDIRECTS + 1):
        await _check_public_https(url)
        try:
            async with client.stream("GET", url) as resp:
                if resp.is_redirect and resp.headers.get("location"):
                    url = urljoin(url, resp.headers["location"])
                    continue
                if resp.status_code in (401, 403):
                    raise _Retry(f"인증 거부 HTTP {resp.status_code}")
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


async def _fetch_rcs(mo: MoMessage, client: httpx.AsyncClient) -> tuple[bytes, str]:
    fm = file_message(mo.content_info_lst)
    if fm is None:
        raise _Fail("fileUrl 없음")
    data = await download(fm["fileUrl"], client)
    content_type = sniff_image(data)
    if content_type is None:
        raise _Fail("지원하지 않는 형식")
    return data, content_type


async def _fetch_mms(mo: MoMessage, msghub: MsghubClient, now: datetime) -> tuple[bytes, str]:
    received = parse_mixed_ts(mo.received_at)
    if received is not None and now - received > MMS_RETENTION:
        raise _Fail("보관 기간(7일)이 지나 받을 수 없음")
    try:
        data, _declared = await msghub.fetch_mo_content(mo.mo_key, max_bytes=MAX_BYTES)
    except MsghubAuthError as exc:
        if exc.code == "29011":
            # 이 API 권한이 없다 — 다시 받아도 같고, 재발급을 부르면 발급 횟수 제한(50010)에 걸린다.
            raise _Fail("권한 없음 [29011]") from exc
        raise _Stop(str(exc)) from exc
    except MsghubBadRequest as exc:
        if exc.code == "TOO_LARGE":
            raise _Fail("크기 초과") from exc
        raise _Retry(str(exc)[:200]) from exc
    except (MsghubError, httpx.HTTPError) as exc:
        raise _Retry(str(exc)[:200] or type(exc).__name__) from exc
    # 이미지면 화면에 바로, 아니면 내려받기 전용(application/octet-stream).
    return data, sniff_image(data) or "application/octet-stream"


def _claim(db: Session, row_id: int, now: datetime) -> bool:
    """받을 차례가 된 PENDING 행을 FETCHING 으로 선점한다. 이미 누가 가져갔으면 False."""
    result = db.execute(
        update(MoMedia)
        .where(
            MoMedia.id == row_id,
            MoMedia.fetch_status == "PENDING",
            or_(MoMedia.next_fetch_at.is_(None), MoMedia.next_fetch_at <= now.isoformat()),
        )
        .values(fetch_status="FETCHING", locked_at=now.isoformat(), fetch_attempts=MoMedia.fetch_attempts + 1)
    )
    db.commit()
    return result.rowcount == 1


def _backoff(attempts: int) -> timedelta:
    return min(timedelta(minutes=2 ** max(attempts - 1, 0)), _MAX_BACKOFF)


async def _fetch_one(
    db: Session, row_id: int, client: httpx.AsyncClient, msghub: MsghubClient | None, now: datetime,
) -> None:
    if not _claim(db, row_id, now):
        return
    row = db.get(MoMedia, row_id)
    mo = db.get(MoMessage, row.mo_id) if row else None
    if row is None or mo is None:
        return
    try:
        if row.source == MMS_API:
            if msghub is None:
                raise _Stop("msghub 클라이언트 없음")
            coro = _fetch_mms(mo, msghub, now)
        else:
            coro = _fetch_rcs(mo, client)
        try:
            data, content_type = await asyncio.wait_for(coro, ROW_TIMEOUT)
        except TimeoutError as exc:
            raise _Retry("시간 초과") from exc
    except _Stop:
        row.fetch_status = "PENDING"
        row.fetch_attempts -= 1
        row.locked_at = None
        db.commit()
        raise
    except _Retry as exc:
        if row.fetch_attempts >= MAX_FETCH_ATTEMPTS.get(row.source, 3):
            row.fetch_status = "FAILED"
        else:
            row.fetch_status = "PENDING"
            row.next_fetch_at = (now + _backoff(row.fetch_attempts)).isoformat()
        row.error = str(exc)
    except _Fail as exc:
        row.fetch_status = "FAILED"
        row.error = str(exc)
    else:
        row.fetch_status = "FETCHED"
        row.content_type = content_type
        row.content_blob = data
        row.file_size_bytes = len(data)
        row.fetched_at = _now().isoformat()
        row.next_fetch_at = None
        row.error = None
    row.locked_at = None
    db.commit()
    if row.fetch_status != "FETCHED":
        # 주소·moKey 에는 통신사·msghub 파일 키가 있어 남기지 않는다.
        log.warning("회신 첨부 가져오기 %s: mo_media=%d (%s)", row.fetch_status, row.id, row.error)


async def fetch_pending(
    db: Session,
    *,
    ids: list[int] | None = None,
    msghub: MsghubClient | None = None,
    client: httpx.AsyncClient | None = None,
    now: datetime | None = None,
) -> int:
    """받을 차례가 된 첨부를 받는다. ids 를 주면 그 행만. 받은(FETCHED) 건수를 돌려준다.

    msghub 가 없으면 MMS 첨부는 건너뛴다. msghub 인증 장애면 이번 주기를 멈춘다.
    """
    now = now or _now()
    stale = (now - _LOCK_TIMEOUT).isoformat()
    # 프로세스가 죽어 FETCHING 에 남은 행은 다시 차례를 준다(시도 횟수는 이미 늘어 있다).
    max_attempts = case(
        (MoMedia.source == MMS_API, MAX_FETCH_ATTEMPTS[MMS_API]), else_=MAX_FETCH_ATTEMPTS[RCS_URL]
    )
    db.execute(
        update(MoMedia)
        .where(MoMedia.fetch_status == "FETCHING", MoMedia.locked_at < stale)
        .values(
            fetch_status=case((MoMedia.fetch_attempts < max_attempts, "PENDING"), else_="FAILED"),
            locked_at=None,
            next_fetch_at=None,
            error="가져오는 중 중단됨",
        )
    )
    db.commit()

    query = select(MoMedia.id).where(
        MoMedia.fetch_status == "PENDING",
        or_(MoMedia.next_fetch_at.is_(None), MoMedia.next_fetch_at <= now.isoformat()),
    )
    if msghub is None:
        query = query.where(MoMedia.source != MMS_API)
    if ids is not None:
        query = query.where(MoMedia.id.in_(ids))
    else:
        query = query.limit(FETCH_BATCH)
    row_ids = list(db.scalars(query.order_by(MoMedia.id)))
    if not row_ids:
        return 0

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False)
    try:
        for row_id in row_ids:
            try:
                await _fetch_one(db, row_id, client, msghub, now)
            except _Stop as exc:
                log.warning("회신 첨부 가져오기 중단 — %s", exc)
                break
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
        # 열린 대화방이 '받아 오는 중' 말풍선을 사진·파일이나 실패 문구로 바꾸도록 다시 불러오게 한다.
        # 웹훅 직후든 주기 작업이든 같은 경로라 나중에 받은 첨부도 알린다.
        try:
            events.publish_throttled("message.new")
        except Exception:  # noqa: BLE001
            log.debug("SSE 이벤트 발행 실패(무시)", exc_info=True)
    return finished.get("FETCHED", 0)


async def fetch_new(ids: list[int]) -> None:
    """웹훅 응답 직후 BackgroundTask — 요청 세션이 닫힌 뒤라 새 세션을 연다."""
    from app.main import aget_msghub_client

    db = SessionLocal()
    try:
        await fetch_pending(db, ids=ids, msghub=await aget_msghub_client())
    except Exception:  # noqa: BLE001 — 남은 행은 주기 작업이 다시 줍는다.
        log.exception("회신 첨부 가져오기 실패")
    finally:
        db.close()


def statuses(db: Session, mo_ids: list[int]) -> dict[int, tuple[str, str]]:
    """mo_id → (fetch_status, "image"|"file"). 본문(BLOB)은 읽지 않는다.

    받기 전에는 알려 준 형식(declared_mime), 받은 뒤에는 실제 형식(content_type)으로 사진인지 가른다.
    """
    if not mo_ids:
        return {}
    out: dict[int, tuple[str, str]] = {}
    for i in range(0, len(mo_ids), 500):
        chunk = mo_ids[i : i + 500]
        rows = db.execute(
            select(MoMedia.mo_id, MoMedia.fetch_status, MoMedia.content_type, MoMedia.declared_mime)
            .where(MoMedia.mo_id.in_(chunk))
        ).all()
        for mo_id, status, content_type, declared in rows:
            mime = content_type if status == "FETCHED" else declared
            out[mo_id] = (status, "image" if is_image_mime(mime) else "file")
    return out


def preview_label_sql():
    """목록 미리보기용 첨부 문구(SQL) — display_text 와 같은 규칙. 첨부가 없으면 ''."""
    info = MoMessage.content_info_lst
    valid = and_(info.is_not(None), func.json_valid(info) == 1)
    rcs_url = func.json_extract(info, "$.fileMessage.fileUrl")
    rcs_mime = func.json_extract(info, "$.fileMessage.fileMIMEType")
    mms_ext = func.lower(func.coalesce(func.json_extract(info, "$[0].contentExt"), ""))
    return case(
        (~valid, case((MoMessage.content_cnt > 0, FILE_LABEL), else_="")),
        (func.json_type(info) == "object",
         case(
             (func.coalesce(rcs_url, "") == "", ""),
             (func.lower(func.coalesce(rcs_mime, "")).like("image/%"), IMAGE_LABEL),
             else_=FILE_LABEL,
         )),
        (MoMessage.content_cnt > 0,
         case((func.ltrim(mms_ext, ".").in_(list(_IMAGE_EXT)), IMAGE_LABEL), else_=FILE_LABEL)),
        else_="",
    )
