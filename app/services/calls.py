"""PBX 통화 기록(CDR) 조회와 녹음 재생 토큰.

- 통화 기록은 kotify DB 에 복제하지 않고 조회할 때마다 PBX 에서 읽는다.
- 2026-10-15 운영 PBX(4.5.1-4) 실측: ``limit`` 의 ``offset,length`` 형식은 500·빈 결과,
  ``page`` 는 무시된다 → ``end_date``(UNIX, 경계 포함)로 키셋 페이지를 만든다.
  ``YYYY-MM-DD`` 날짜는 0건이라 항상 UNIX 시각을 보낸다. ``extensions`` 는 번호 1개의
  정확 일치이며(쉼표 목록은 0건) CDR 의 외부 번호는 0 을 포함한 국내 형식이다.
  ``calldate`` 문자열은 UTC 다(``calldate_ts`` 와 같은 시각).
- 응답에서 ``recording_url``·``recfile``·``channel``·``lastdata`` 같은 원본 필드는 버린다.
  녹음은 경로를 마스터 키(Fernet)로 암호화한 토큰으로만 브라우저에 넘긴다 —
  VitalPBX 녹음 파일 이름에 고객 번호가 들어 있어 서명만으로는 경로가 드러난다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from urllib.parse import urlsplit

from cryptography.fernet import InvalidToken

from app.pbx.client import PbxClient, PbxConfig
from app.security.crypto import get_fernet
from app.util.time import KST

# 녹음 토큰 유효 시간 — 목록을 띄워 둔 채 재생하는 시간을 고려.
RECORDING_TOKEN_TTL_SECONDS = 30 * 60

# /vrecordings/<테넌트>/<YYYY>/<MM>/<DD>/<파일> 만 허용 (경로 조작 차단).
_RECORDING_PATH = re.compile(
    r"^/vrecordings/[A-Za-z0-9_-]+/\d{4}/\d{2}/\d{2}/[A-Za-z0-9_.+-]+\.(?:wav|WAV|mp3|gsm)$"
)

_DIRECTIONS = {"1": "internal", "2": "in", "3": "out", "4": "transit"}
CALL_TYPES = {"internal": "1", "in": "2", "out": "3", "transit": "4"}

MAX_LIMIT = 100


def _digits(value: object) -> str:
    return "".join(c for c in str(value or "") if c.isdigit())


def cdr_number(phone: str) -> str:
    """고객 번호 → CDR ``extensions`` 값. 국제 표기(+82)는 0 으로 시작하는 국내 형식으로."""
    digits = _digits(phone)
    if digits.startswith("82") and len(digits) >= 11:
        digits = "0" + digits[2:]
    return digits


def _kst_day_bounds(start: date, end: date) -> tuple[int, int]:
    """KST 날짜 범위 → (시작 00:00:00, 끝 23:59:59) UNIX 초."""
    lo = datetime.combine(start, dt_time.min, tzinfo=KST)
    hi = datetime.combine(end, dt_time.max, tzinfo=KST)
    return int(lo.timestamp()), int(hi.timestamp())


def encode_cursor(ts: int, ids: list[int]) -> str:
    """다음 페이지 커서 — 마지막 행의 시각과, 그 시각에 이미 보여 준 행 id."""
    return f"{ts}:" + ".".join(str(i) for i in sorted(set(ids)))


def decode_cursor(raw: str) -> tuple[int, set[int]] | None:
    head, _, tail = raw.partition(":")
    if not head.isdigit():
        return None
    ids = tail.split(".") if tail else []
    if not all(i.isdigit() for i in ids) or len(ids) > MAX_LIMIT:
        return None
    return int(head), {int(i) for i in ids}


def recording_path(recording_url: object) -> str | None:
    """``recording_url`` 에서 경로만 꺼낸다. 허용 형식이 아니면 None."""
    if not isinstance(recording_url, str) or not recording_url:
        return None
    path = urlsplit(recording_url).path
    if ".." in path or not _RECORDING_PATH.fullmatch(path):
        return None
    return path


def make_recording_token(path: str, user_sub: str, cdr_id: int | str) -> str:
    """녹음 경로·사용자·CDR id 를 Fernet 으로 암호화한 토큰."""
    payload = json.dumps({"p": path, "u": user_sub, "c": str(cdr_id)}, separators=(",", ":"))
    return get_fernet().encrypt(payload.encode("utf-8")).decode("ascii")


@dataclass(frozen=True)
class RecordingRef:
    path: str
    cdr_id: str


def read_recording_token(token: str, user_sub: str) -> RecordingRef | None:
    """토큰을 검증한다. 위조·만료·다른 사용자·형식 오류는 모두 None."""
    try:
        raw = get_fernet().decrypt(token.encode("ascii"), ttl=RECORDING_TOKEN_TTL_SECONDS)
        payload = json.loads(raw)
    except (InvalidToken, UnicodeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("u") != user_sub:
        return None
    path = payload.get("p")
    if not isinstance(path, str) or recording_path(path) != path:
        return None
    return RecordingRef(path=path, cdr_id=str(payload.get("c") or ""))


def _int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _call_time(row: dict) -> str:
    """통화 시각을 KST ISO 문자열로. ``calldate_ts``(UNIX) 우선."""
    ts = _int(row.get("calldate_ts"))
    if ts > 0:
        return datetime.fromtimestamp(ts, UTC).astimezone(KST).isoformat()
    raw = str(row.get("calldate") or "").strip()
    try:
        # 운영 PBX 의 calldate 는 UTC (calldate_ts 와 같은 시각, 2026-10-15 실측).
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        return dt.astimezone(KST).isoformat()
    except ValueError:
        return ""


def summarize_cdr(row: dict, user_sub: str) -> dict:
    """PBX CDR 1행 → 화면용 축약 형태. 원본 경로·채널 정보는 넣지 않는다."""
    cdr_id = row.get("cdr_id")
    path = recording_path(row.get("recording_url"))
    disposition = str(row.get("disposition") or "")
    return {
        "id": _int(cdr_id),
        "at": _call_time(row),
        "direction": _DIRECTIONS.get(str(row.get("calltype") or ""), "unknown"),
        "from": _digits(row.get("source") or row.get("src")),
        "to": _digits(row.get("destination") or row.get("dst")),
        "durationSec": _int(row.get("duration")),
        "billSec": _int(row.get("billsec")),
        "disposition": disposition,
        "recordingToken": (
            make_recording_token(path, user_sub, cdr_id if cdr_id is not None else "")
            if path
            else None
        ),
    }


def _kst_today() -> datetime:
    return datetime.now(UTC).astimezone(KST)


async def list_calls(
    config: PbxConfig,
    *,
    user_sub: str,
    phone: str | None,
    date_from: date | None,
    date_to: date | None,
    call_type: str | None,
    limit: int,
    cursor: str | None,
) -> dict:
    """CDR 을 최신순으로 조회해 ``{data, meta}`` 형태로 돌려준다.

    다음 페이지는 ``meta.nextCursor`` 를 ``cursor`` 로 넘긴다. 같은 초에 여러 통화가
    있을 수 있어 경계 시각은 포함해 다시 받고, 이미 보여 준 id 만 버린다.

    Raises:
        ValueError: 커서 형식 오류.
    """
    today = _kst_today().date()
    end = date_to or today
    start = date_from or (end - timedelta(days=30))
    start_ts, end_ts = _kst_day_bounds(start, end)
    seen: set[int] = set()
    if cursor:
        decoded = decode_cursor(cursor)
        if decoded is None:
            raise ValueError("invalid cursor")
        end_ts, seen = min(end_ts, decoded[0]), decoded[1]

    params: dict[str, str] = {
        "start_date": str(start_ts),
        "end_date": str(end_ts),
        # 경계에서 버릴 행만큼 더 받는다. +1 은 다음 페이지 여부 판단용.
        "limit": str(limit + len(seen) + 1),
        "order_by": "calldate",
        "order_type": "desc",
    }
    if phone:
        params["extensions"] = cdr_number(phone)
    if call_type:
        params["calltype"] = CALL_TYPES[call_type]

    rows = await PbxClient(config).list_cdr(params)
    rows = [row for row in rows if _int(row.get("cdr_id")) not in seen]
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = None
    if has_more and page:
        last_ts = _int(page[-1].get("calldate_ts"))
        same_second = [_int(r.get("cdr_id")) for r in page if _int(r.get("calldate_ts")) == last_ts]
        if last_ts == end_ts:
            same_second += list(seen)
        next_cursor = encode_cursor(last_ts, same_second)
    return {
        "data": [summarize_cdr(row, user_sub) for row in page],
        "meta": {
            "limit": limit,
            "hasMore": has_more,
            "nextCursor": next_cursor,
            "from": start.isoformat(),
            "to": end.isoformat(),
        },
    }
