"""PBX 가상 팩스 발송 작업 테이블을 추가한다.

Revision ID: 0024
Revises: 0023
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fax_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_by", sa.Text(), nullable=False),
        sa.Column("recipient", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("pdf_blob", sa.LargeBinary(), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=False),
        sa.Column("retries", sa.Integer(), nullable=False),
        sa.Column("retry_time", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("pbx_file", sa.Text(), nullable=True),
        sa.Column("pbx_log_id", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("fetch_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("submitted_at", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.sub"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_fax_jobs_status", "fax_jobs", ["status"], unique=False)
    op.create_index(
        "idx_fax_jobs_created_by", "fax_jobs", ["created_by", "id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("idx_fax_jobs_created_by", table_name="fax_jobs")
    op.drop_index("idx_fax_jobs_status", table_name="fax_jobs")
    op.drop_table("fax_jobs")
