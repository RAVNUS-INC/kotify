"""공통 Jinja2Templates 인스턴스 + 글로벌 헬퍼.

모든 route는 여기서 templates를 import한다.
각 route가 자체 인스턴스를 만들면 csrf_token 같은 글로벌이
한 인스턴스에만 등록되어 다른 route에서 500 에러가 발생한다.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from fastapi.templating import Jinja2Templates

from app.i18n import t_error
from app.ncp.codes import describe
from app.security.csrf import get_csrf_token

templates = Jinja2Templates(directory="app/templates")

# 모든 템플릿에서 {{ csrf_token(request) }} 사용 가능
templates.env.globals["csrf_token"] = get_csrf_token

# 오류 슬러그 → 한국어 메시지
templates.env.globals["t_error"] = t_error

# NCP 결과 코드 → 한국어 설명
templates.env.globals["describe_ncp"] = describe

# KST 날짜 필터
_KST = timezone(timedelta(hours=9))


def kst_dt(value: str | None) -> str:
    """ISO UTC 문자열 → KST 'YYYY-MM-DD HH:mm' 형식으로 변환한다.

    Args:
        value: ISO 형식의 날짜/시간 문자열 또는 None.

    Returns:
        KST 기준 'YYYY-MM-DD HH:mm' 문자열. value가 없으면 빈 문자열 반환.
    """
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(_KST).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return value[:16].replace("T", " ")


templates.env.filters["kst_dt"] = kst_dt


def phone_fmt(value: str | None) -> str:
    """전화번호를 표시용으로 포맷팅한다.

    입력은 정규화된 숫자만 (예: '01012345678', '0212345678').
    출력은 하이픈 포맷:
    - 휴대폰 11자리: 010-1234-5678
    - 휴대폰 10자리: 011-123-4567
    - 서울 02 9-10자리: 02-1234-5678 / 02-123-4567
    - 그 외 지역번호 10-11자리: 031-1234-5678
    - 매치 안 되면 원본 반환

    Args:
        value: 정규화된 전화번호 문자열 또는 None.

    Returns:
        하이픈이 포함된 표시용 문자열.
    """
    if not value:
        return ""
    digits = "".join(c for c in value if c.isdigit())
    if not digits:
        return value
    # 휴대폰 (010, 011, 016, 017, 018, 019)
    if digits.startswith("01") and len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    if digits.startswith("01") and len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    # 서울 02
    if digits.startswith("02") and len(digits) == 10:
        return f"{digits[:2]}-{digits[2:6]}-{digits[6:]}"
    if digits.startswith("02") and len(digits) == 9:
        return f"{digits[:2]}-{digits[2:5]}-{digits[5:]}"
    # 지역번호 03x ~ 06x (10~11자리)
    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    # 인터넷 070, 050x 등
    if digits.startswith("070") and len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"
    return value


templates.env.filters["phone_fmt"] = phone_fmt
