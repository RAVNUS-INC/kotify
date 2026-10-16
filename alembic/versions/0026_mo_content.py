"""MMS MO 첨부(컨텐츠)를 받아 보관하는 컬럼을 추가한다.

msghub 는 MO 컨텐츠를 7일만 보관한다(GET /mo/v1/file/{moKey}). 받은 파일은 팩스처럼 DB 에 보관한다.
이미 받은 MO 중 컨텐츠가 있는 것은 대기(PENDING)로 표시해 7일 안이면 재조정 루프가 받아 온다.

Revision ID: 0026
Revises: 0025
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("mo_messages") as batch_op:
        batch_op.add_column(sa.Column("content_blob", sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column("content_type", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("content_size", sa.Integer(), nullable=True))
        # NULL(컨텐츠 없음) | PENDING | FETCHED | FAILED(재시도 대기) | EXPIRED(보관 기간·재시도 한도 초과)
        batch_op.add_column(sa.Column("content_fetch_status", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("content_fetch_attempts", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(sa.Column("content_next_fetch_at", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("content_error", sa.Text(), nullable=True))
        batch_op.create_index("idx_mo_messages_content_fetch", ["content_fetch_status"])
    op.execute(
        "UPDATE mo_messages SET content_fetch_status = 'PENDING' "
        "WHERE content_cnt > 0 AND mo_key NOT LIKE 'syn-%'"
    )


def downgrade() -> None:
    with op.batch_alter_table("mo_messages") as batch_op:
        batch_op.drop_index("idx_mo_messages_content_fetch")
        batch_op.drop_column("content_error")
        batch_op.drop_column("content_next_fetch_at")
        batch_op.drop_column("content_fetch_attempts")
        batch_op.drop_column("content_fetch_status")
        batch_op.drop_column("content_size")
        batch_op.drop_column("content_type")
        batch_op.drop_column("content_blob")
