"""시간 변환 유틸 — ISO 8601 (UTC 정규화) 과 msghub 네이티브(KST yyyyMMddHHmmss)
를 모두 지원하는 공통 파서/포매터.

왜 필요한가:
    우리 DB 에는 두 포맷이 섞여 저장된다.
      - `Campaign.created_at`, `AuditLog.created_at`, `User.created_at` 등:
        `datetime.now(UTC).isoformat()` 결과 (+00:00 접미사).
      - `Message.complete_time`, `Message.report_dt`:
        msghub webhook 원본 `yyyyMMddHHmmss` 를 **그대로 저장** (KST).

    이전엔 각 route 파일마다 로컬 `_fmt_kst_*` 를 두고 `datetime.fromisoformat`
    만 호출했는데, msghub 원본을 만나면 ValueError → except 로 빈 문자열 반환.
    사용자 화면에서 시간 필드가 비거나 일부만 변환되어 "UTC 로 보이는" 혼란
    이 발생.

    이 모듈의 `parse_mixed_ts()` 가 두 포맷을 모두 수용하고, 이후 변환 헬퍼
    (`fmt_kst_*`) 는 전부 이 파서 위에서 동작. 각 route 는 로컬 헬퍼를 지우고
    여기서 import.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def parse_mixed_ts(raw: str | None) -> datetime | None:
    """문자열 → tz-aware datetime. 실패 시 None.

    지원 포맷 (우선순위):
      1. ISO 8601 (`fromisoformat` 호환). 'Z'·오프셋 있으면 그대로, **naive(오프셋
         없음)면 KST 간주**. 우리가 만드는 값은 항상 +00:00(aware)이고, 오프셋 없는
         값은 msghub moRecvDt("2026-02-23 11:36:38" 등)처럼 KST 이기 때문.
      2. msghub 네이티브 yyyyMMddHHmmss — 14자리 이상의 숫자. **KST 로 간주**
         (msghub 가 한국 서비스라 문자열에 tz 표기가 없어도 KST 로 해석해야
         실제 이벤트 시각과 일치).

    두 포맷 모두 실패하면 None — 호출자가 빈 문자열 fallback 결정.
    """
    if not raw:
        return None

    # 1차: ISO 8601.
    try:
        s = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            # 오프셋 없는 값은 msghub KST(예: moRecvDt "2026-02-23 11:36:38").
            # 우리가 생성하는 시각은 항상 +00:00 이라 naive=KST 가정이 안전하다.
            dt = dt.replace(tzinfo=KST)
        return dt
    except (ValueError, TypeError):
        pass

    # 2차: msghub 네이티브 yyyyMMddHHmmss (또는 14자리 숫자 포함 문자열).
    # digits 만 추출해서 맨 앞 14자리 — "2026-04-23 00:12:00" 같은 표기도
    # 자릿수 맞으면 허용.
    digits = "".join(c for c in raw if c.isdigit())
    if len(digits) >= 14:
        try:
            naive = datetime.strptime(digits[:14], "%Y%m%d%H%M%S")
            return naive.replace(tzinfo=KST)
        except (ValueError, TypeError):
            pass

    return None


def parse_mixed_ts_epoch(raw: str | None) -> float:
    """정렬 키용 epoch float. 실패 시 0.0 (가장 앞)."""
    dt = parse_mixed_ts(raw)
    return dt.timestamp() if dt is not None else 0.0


def _fmt(raw: str | None, pattern: str) -> str:
    """내부: parse → KST 변환 → strftime. 실패 시 빈 문자열."""
    dt = parse_mixed_ts(raw)
    if dt is None:
        return ""
    return dt.astimezone(KST).strftime(pattern)


def fmt_kst_hhmm(raw: str | None) -> str:
    """'HH:MM' KST. 오늘 날짜 메시지 시간 표시용."""
    return _fmt(raw, "%H:%M")


def fmt_kst_date(raw: str | None) -> str:
    """'YYYY-MM-DD' KST. 가입일 등 날짜만 표시."""
    return _fmt(raw, "%Y-%m-%d")


def fmt_kst_dt(raw: str | None) -> str:
    """'YYYY-MM-DD HH:MM' KST. 기본 리스트/테이블 표시용."""
    return _fmt(raw, "%Y-%m-%d %H:%M")


def fmt_kst_full(raw: str | None) -> str:
    """'YYYY-MM-DD HH:MM:SS' KST. 감사 로그 등 정밀 필요 시."""
    return _fmt(raw, "%Y-%m-%d %H:%M:%S")
