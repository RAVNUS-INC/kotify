"""mo_callback / thread_reads.caller 를 숫자만으로 정규화.

0013 이 전화번호 컬럼을 숫자만으로 통일했으나 mo_messages.mo_callback 과
thread_reads.caller 두 컬럼이 누락됐다. 그 결과 대화방 그룹핑 키
(caller, phone)=(mo_callback, mo_number) 에서 caller 형식이 발송측
(campaigns.caller_number, 숫자만)과 달라, 같은 고객이 "발송방"과 "회신방"
두 개로 쪼개졌다. 이 마이그레이션으로 기존 데이터를 정리한다(신규는
webhook 저장 단계에서 이미 숫자만으로 저장).

thread_reads 는 (caller, phone) UNIQUE 제약이 있어, 정규화 후 충돌하면
(예: 같은 phone 에 caller 만 형식이 다른 중복 읽음행) 더 최근 read_at 을
남기고 나머지는 삭제한다. 읽음 상태는 유실돼도 "미읽음"으로 안전 fallback.

멱등: 이미 숫자만인 값은 변화 없음.

Revision ID: 0015
Revises: 0014
"""
from __future__ import annotations

import re

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels = None
depends_on = None

_NON_DIGIT = re.compile(r"\D")


def upgrade() -> None:
    conn = op.get_bind()

    # 1) mo_messages.mo_callback — UNIQUE 제약 없음, 단순 정규화.
    rows = conn.execute(
        sa.text("SELECT id, mo_callback FROM mo_messages WHERE mo_callback IS NOT NULL")
    ).fetchall()
    for row_id, value in rows:
        digits = _NON_DIGIT.sub("", value)
        if digits != value:
            conn.execute(
                sa.text("UPDATE mo_messages SET mo_callback = :v WHERE id = :i"),
                {"v": digits, "i": row_id},
            )

    # 2) thread_reads.caller — (caller, phone) UNIQUE. 정규화 후 충돌 처리.
    tr_rows = conn.execute(
        sa.text("SELECT id, caller, phone, read_at FROM thread_reads")
    ).fetchall()
    # (norm_caller, phone) → 살아남을 행의 (id, read_at). 나머지는 삭제 대상.
    keep: dict[tuple[str, str], tuple[int, str]] = {}
    to_delete: list[int] = []
    to_update: list[tuple[int, str]] = []  # (id, norm_caller)
    for row_id, caller, phone, read_at in tr_rows:
        norm = _NON_DIGIT.sub("", caller or "")
        key = (norm, phone)
        prev = keep.get(key)
        if prev is None:
            keep[key] = (row_id, read_at or "")
            if norm != (caller or ""):
                to_update.append((row_id, norm))
        else:
            # 충돌 — 더 최근 read_at 을 남기고 오래된 행 삭제.
            prev_id, prev_read = prev
            if (read_at or "") > prev_read:
                to_delete.append(prev_id)
                keep[key] = (row_id, read_at or "")
                if norm != (caller or ""):
                    to_update.append((row_id, norm))
            else:
                to_delete.append(row_id)

    # 삭제 먼저(제약 충돌 방지) → 그다음 update.
    for del_id in to_delete:
        conn.execute(
            sa.text("DELETE FROM thread_reads WHERE id = :i"), {"i": del_id}
        )
    for row_id, norm in to_update:
        conn.execute(
            sa.text("UPDATE thread_reads SET caller = :v WHERE id = :i"),
            {"v": norm, "i": row_id},
        )


def downgrade() -> None:
    # 구분자 제거 + 중복 삭제는 비가역. no-op.
    pass
