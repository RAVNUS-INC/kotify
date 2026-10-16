"""고객 회신(MO) 첨부 이미지 보관 테이블을 추가한다.

이미 저장된 회신 중 contentInfo.fileMessage 가 있는 행은 PENDING(이미지) 또는
UNSUPPORTED(그 밖의 형식)로 넣어 둔다. 내려받기는 앱의 주기 작업이 맡고, 이미 만료된
주소는 그때 FAILED 로 남는다 — 마이그레이션은 네트워크를 쓰지 않는다.

Revision ID: 0026
Revises: 0025
"""
from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mo_media",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("mo_id", sa.Integer(), nullable=False),
        sa.Column("declared_mime", sa.Text(), nullable=True),
        sa.Column("content_type", sa.Text(), nullable=True),
        sa.Column("content_blob", sa.LargeBinary(), nullable=True),
        sa.Column("file_size_bytes", sa.Integer(), nullable=True),
        sa.Column("fetch_status", sa.Text(), nullable=False),
        sa.Column("fetch_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_at", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["mo_id"], ["mo_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mo_id", name="uq_mo_media_mo_id"),
    )
    op.create_index("idx_mo_media_fetch", "mo_media", ["fetch_status"], unique=False)

    # 기존 회신 소급 — SQLite json1 로 fileMessage 가 있는 행만 고른다.
    url = "json_extract(content_info_lst, '$.fileMessage.fileUrl')"
    mime = "json_extract(content_info_lst, '$.fileMessage.fileMIMEType')"
    op.get_bind().execute(
        sa.text(
            f"""
            INSERT INTO mo_media (mo_id, declared_mime, fetch_status, fetch_attempts, created_at)
            SELECT id, {mime},
                   CASE WHEN lower(coalesce({mime}, '')) LIKE 'image/%' THEN 'PENDING'
                        ELSE 'UNSUPPORTED' END,
                   0, :now
            FROM mo_messages
            WHERE content_info_lst IS NOT NULL AND json_valid(content_info_lst)
              AND json_type(content_info_lst, '$.fileMessage.fileUrl') = 'text'
              AND {url} <> ''
            """
        ),
        {"now": datetime.now(UTC).isoformat()},
    )


def downgrade() -> None:
    op.drop_index("idx_mo_media_fetch", table_name="mo_media")
    op.drop_table("mo_media")
