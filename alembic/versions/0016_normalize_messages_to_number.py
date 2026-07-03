"""messages.to_number 잔여 하이픈 정리 (0013 이후 유입분).

0013 이 배포 시점의 to_number 를 숫자만으로 통일했으나, 그 이후 발송 경로
(compose)가 to_number 를 정규화 없이 저장해 하이픈 번호가 다시 유입됐다
(예: '010-7171-2463'). 그 결과 발송(MT) to_number 와 회신(MO) mo_number 의
형식이 달라, 같은 고객이 대화방 2개로 분리됐다.

이 마이그레이션으로 잔여분을 정리하고, compose 저장 경로도 함께 수정해
재유입을 막는다(_norm_to_number). to_number_raw(원본)는 보존한다.

멱등: 이미 숫자만인 값은 변화 없음.

Revision ID: 0016
Revises: 0015
"""
from __future__ import annotations

import re

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels = None
depends_on = None

_NON_DIGIT = re.compile(r"\D")


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, to_number FROM messages WHERE to_number IS NOT NULL")
    ).fetchall()
    for row_id, value in rows:
        digits = _NON_DIGIT.sub("", value)
        if digits != value:
            conn.execute(
                sa.text("UPDATE messages SET to_number = :v WHERE id = :i"),
                {"v": digits, "i": row_id},
            )


def downgrade() -> None:
    # 구분자 제거는 비가역(원본 하이픈 위치 복원 불가). to_number_raw 에 원본 보존.
    pass
