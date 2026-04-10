"""attachments 테이블 추가

MMS 첨부 이미지 저장. BLOB 기반 (SQLite 동일 DB, 백업 단순).

- original_filename: 사용자 업로드 파일명 (감사/UX용)
- stored_filename: 내부 UUID 기반 파일명 (충돌 방지)
- content_blob: 전처리 후 JPEG 바이너리 (NCP 제약: ≤300KB, ≤1500x1440)
- ncp_file_id: 업로드 성공 시 NCP가 돌려준 fileId
- ncp_expires_at: NCP 보관 만료 시각 (약 6일)

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-10
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "campaign_id",
            sa.Integer,
            sa.ForeignKey("campaigns.id"),
            nullable=True,  # 업로드 직후엔 campaign 미생성 상태
        ),
        sa.Column("ncp_file_id", sa.Text, nullable=True),
        sa.Column("original_filename", sa.Text, nullable=False),
        sa.Column("stored_filename", sa.Text, nullable=False),
        sa.Column("content_blob", sa.LargeBinary, nullable=False),
        sa.Column("file_size_bytes", sa.Integer, nullable=False),
        sa.Column("width", sa.Integer, nullable=False),
        sa.Column("height", sa.Integer, nullable=False),
        sa.Column("uploaded_by", sa.Text, sa.ForeignKey("users.sub"), nullable=False),
        sa.Column("uploaded_at", sa.Text, nullable=False),
        sa.Column("ncp_expires_at", sa.Text, nullable=True),
    )
    op.create_index("idx_attachments_campaign_id", "attachments", ["campaign_id"])
    op.create_index("idx_attachments_uploaded_by", "attachments", ["uploaded_by"])


def downgrade() -> None:
    op.drop_index("idx_attachments_uploaded_by", table_name="attachments")
    op.drop_index("idx_attachments_campaign_id", table_name="attachments")
    op.drop_table("attachments")
