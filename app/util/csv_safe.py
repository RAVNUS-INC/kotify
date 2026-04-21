"""CSV formula injection 방어 공통 헬퍼 (CWE-1236).

Excel/Numbers에서 `=`, `+`, `-`, `@`, `\\t`, `\\r`로 시작하는 셀 값은
공식으로 해석되어 외부 링크·명령 실행 위험이 있다. single-quote prefix로
무력화한다.

사용처: app/routes/audit_api.py, app/routes/reports.py
"""
from __future__ import annotations


# CWE-1236: Excel/LibreOffice/Numbers가 공식 시작 문자로 해석하는 접두사.
# `\n` 과 `;` 는 일부 로케일(특히 LibreOffice) 에서도 셀 구분/공식 트리거로 쓰이므로 포함.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n", ";")


def safe_csv_cell(value: str) -> str:
    """공식 해석 가능한 값이면 single-quote로 prefix, 아니면 그대로 반환."""
    if value and value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value
