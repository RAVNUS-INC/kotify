"""전화번호 컬럼을 숫자만 저장하도록 일괄 정규화 (기존 하이픈/구분자 제거).

정책: DB 에는 전화번호를 숫자만 저장하고, 표시용 하이픈은 프론트(formatPhone)에서
넣는다. 신규 입력은 normalize_phone 으로 이미 숫자만 저장되지만, 정규화 통일 이전
데이터나 인바운드(MO) 경로로 들어온 값에 하이픈/공백/점이 남아 있을 수 있어 일괄 정리한다.

멱등(idempotent): 이미 숫자만 있는 값은 변화 없음.

Revision ID: 0013
Revises: 0012
"""
from __future__ import annotations

import re

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels = None
depends_on = None

# 전화번호/식별번호를 보관하는 모든 (table, column).
_TARGETS = [
    ("callers", "number"),
    ("campaigns", "caller_number"),
    ("messages", "to_number"),
    ("contacts", "phone"),
    ("mo_messages", "mo_number"),
    ("thread_reads", "phone"),
]

_NON_DIGIT = re.compile(r"\D")


def upgrade() -> None:
    conn = op.get_bind()
    for table, col in _TARGETS:
        rows = conn.execute(
            sa.text(f"SELECT id, {col} FROM {table} WHERE {col} IS NOT NULL")
        ).fetchall()
        for row_id, value in rows:
            if value is None:
                continue
            digits = _NON_DIGIT.sub("", value)
            if digits != value:
                conn.execute(
                    sa.text(f"UPDATE {table} SET {col} = :v WHERE id = :i"),
                    {"v": digits, "i": row_id},
                )


def downgrade() -> None:
    # 구분자 제거는 비가역(원본 하이픈 위치 복원 불가). no-op.
    pass
