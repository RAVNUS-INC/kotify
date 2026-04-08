"""오류 슬러그 → 한국어 메시지 매핑."""
from __future__ import annotations

ERROR_MESSAGES: dict[str, str] = {
    "invalid_caller": "선택한 발신번호가 활성 목록에 없습니다.",
    "invalid_numbers": "잘못된 전화번호가 포함되어 있습니다. 모두 수정한 뒤 다시 시도하세요.",
    "too_many_recipients": "1회 최대 1,000명까지만 발송할 수 있습니다.",
    "ncp_not_configured": "NCP 발송 서비스가 구성되지 않았습니다. 관리자에게 문의하세요.",
    "stub_phone": "전화번호 검증 모듈이 구현되지 않았습니다 (개발자 영역).",
    "stub_signature": "NCP HMAC 서명 모듈이 구현되지 않았습니다 (개발자 영역).",
    "invalid_token": "올바르지 않은 setup token입니다.",
    "invalid_message": "메시지 내용이 유효하지 않습니다.",
    "no_recipients": "유효한 수신번호가 없습니다.",
}


def t_error(slug: str | None) -> str:
    """오류 슬러그를 한국어 메시지로 변환한다.

    Args:
        slug: 오류 슬러그 문자열 또는 None.

    Returns:
        한국어 오류 메시지. slug가 None이거나 빈 문자열이면 빈 문자열 반환.
    """
    if not slug:
        return ""
    return ERROR_MESSAGES.get(slug, f"알 수 없는 오류 ({slug})")
