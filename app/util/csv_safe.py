"""CSV formula injection 방어 공통 헬퍼 (CWE-1236).

Excel/Numbers에서 `=`, `+`, `-`, `@`, `\\t`, `\\r`로 시작하는 셀 값은
공식으로 해석되어 외부 링크·명령 실행 위험이 있다. single-quote prefix로
무력화한다.

사용처: app/routes/audit_api.py, app/routes/reports.py
"""
from __future__ import annotations


_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_csv_cell(value: str) -> str:
    """공식 해석 가능한 값이면 single-quote로 prefix, 아니면 그대로 반환."""
    if value and value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value
