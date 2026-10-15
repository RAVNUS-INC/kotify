"""PBX 통화 기록(CDR) 조회와 녹음 재생 토큰.

- 통화 기록은 kotify DB 에 복제하지 않고 조회할 때마다 PBX 에서 읽는다.
- 응답에서 ``recording_url``·``recfile``·``channel``·``lastdata`` 같은 원본 필드는 버린다.
  녹음은 경로를 마스터 키(Fernet)로 암호화한 토큰으로만 브라우저에 넘긴다 —
  VitalPBX 녹음 파일 이름에 고객 번호가 들어 있어 서명만으로는 경로가 드러난다.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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


def cdr_number_variants(phone: str) -> list[str]:
    """고객 번호를 CDR ``extensions`` 필터 값들로 바꾼다.

    통신사 트렁크에 따라 CDR 의 외부 번호가 ``0`` 을 뺀 국내 번호나 ``82`` 국가
    번호로 남을 수 있어 같은 번호의 표기를 함께 넘긴다(필터는 OR).
    """
    digits = _digits(phone)
    if not digits:
        return []
    variants = [digits]
    if digits.startswith("0") and len(digits) > 1:
        variants += [digits[1:], "82" + digits[1:]]
    return list(dict.fromkeys(variants))


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
        # PBX 시간대는 Asia/Seoul — 오프셋 없는 값은 KST 로 본다.
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST).isoformat()
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
    date_from: str | None,
    date_to: str | None,
    call_type: str | None,
    limit: int,
    offset: int,
) -> dict:
    """CDR 을 조회해 ``{data, meta}`` 형태로 돌려준다.

    ``limit+1`` 건을 요청해 다음 페이지 여부를 판단한다(PBX 응답의 전체 건수에
    의존하지 않는다).
    """
    today = _kst_today().date()
    end = date_to or today.isoformat()
    start = date_from or (today - timedelta(days=30)).isoformat()
    params: dict[str, str] = {
        "start_date": start,
        "end_date": end,
        "limit": f"{offset},{limit + 1}",
        "order_by": "calldate",
        "order_type": "desc",
    }
    if phone:
        params["extensions"] = ",".join(cdr_number_variants(phone))
    if call_type:
        params["calltype"] = CALL_TYPES[call_type]

    rows = await PbxClient(config).list_cdr(params)
    has_more = len(rows) > limit
    data = [summarize_cdr(row, user_sub) for row in rows[:limit]]
    return {
        "data": data,
        "meta": {
            "limit": limit,
            "offset": offset,
            "hasMore": has_more,
            "from": start,
            "to": end,
        },
    }
