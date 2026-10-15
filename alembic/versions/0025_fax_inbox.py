"""PBX 가상 팩스로 받은 팩스 테이블을 추가한다.

Revision ID: 0025
Revises: 0024
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fax_inbox",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pbx_log_id", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.Text(), nullable=False),
        sa.Column("sender_number", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("pbx_file", sa.Text(), nullable=True),
        sa.Column("pdf_blob", sa.LargeBinary(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("fetch_status", sa.Text(), nullable=False),
        sa.Column("fetch_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("first_viewed_at", sa.Text(), nullable=True),
        sa.Column("first_viewed_by", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pbx_log_id", name="uq_fax_inbox_pbx_log_id"),
    )
    op.create_index("idx_fax_inbox_received_at", "fax_inbox", ["received_at"], unique=False)
    op.create_index("idx_fax_inbox_fetch", "fax_inbox", ["fetch_status"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_fax_inbox_fetch", table_name="fax_inbox")
    op.drop_index("idx_fax_inbox_received_at", table_name="fax_inbox")
    op.drop_table("fax_inbox")
