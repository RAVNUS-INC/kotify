"""NCP SENS 수신결과 코드 표시 헬퍼.

우리는 코드 의미를 자체 번역하지 않는다.
NCP가 돌려주는 `statusMessage`만이 신뢰할 수 있는 원천이며,
DB의 `result_message` 컬럼(poller에서 `item.status_message`로 저장)이 그 값이다.

statusMessage가 비어 있는 엣지케이스(구 이력, API 누락)에서는
추측하지 않고 raw 코드만 노출한다. 운영자가 직접 공식 문서를 참조한다:
https://api.ncloud-docs.com/docs/ko/sens-sms-get
"""
from __future__ import annotations


def describe(code: str | None, raw_message: str | None = None) -> str:
    """NCP 수신결과를 사람이 읽을 수 있는 문자열로 변환한다.

    우선순위:
    1. NCP가 보내준 ``statusMessage`` (``raw_message``) — 유일한 신뢰 원천
    2. 없으면 ``"결과 코드 {code}"`` 형태로 raw 코드만 노출 (추측 금지)
    3. 코드도 없으면 ``"—"``

    Args:
        code: NCP ``messages[].statusCode`` 값 (예: ``"0"``, ``"3023"``).
        raw_message: NCP ``messages[].statusMessage`` 원문.

    Returns:
        표시용 문자열. 우리가 자체 번역한 설명은 절대 반환하지 않는다.
    """
    if raw_message:
        return raw_message
    if code:
        return f"결과 코드 {code}"
    return "—"
