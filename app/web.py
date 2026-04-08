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
