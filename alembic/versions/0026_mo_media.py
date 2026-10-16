"""고객 회신(MO) 첨부 보관 테이블을 추가한다 — RCS 양방향 사진과 MMS 첨부.

source 로 받는 곳을 나눈다(services.mo_media): RCS_URL(contentInfo.fileMessage.fileUrl, 통신사 주소)과
MMS_API(msghub GET /mo/v1/file/{moKey}). 이미 저장된 회신도 소급해 넣는다.
- RCS: fileMessage 가 있는 행 — 이미지는 PENDING, 그 밖의 형식은 UNSUPPORTED.
- MMS: RCS 가 아닌(fileMessage 없음) 실제 moKey 회신 중 content_cnt > 0 인 행 — PENDING.
같은 회신에 이미 행이 있으면 넣지 않는다(NOT EXISTS). 내려받기는 앱의 주기 작업이 맡고 이미 만료된
것은 그때 FAILED 로 남는다 — 마이그레이션은 네트워크를 쓰지 않는다. mo_messages 는 바꾸지 않는다.

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
        sa.Column("source", sa.Text(), nullable=False, server_default="RCS_URL"),
        sa.Column("fetch_status", sa.Text(), nullable=False),
        sa.Column("fetch_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_fetch_at", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["mo_id"], ["mo_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("mo_id", name="uq_mo_media_mo_id"),
    )
    op.create_index("idx_mo_media_fetch", "mo_media", ["fetch_status"], unique=False)

    bind = op.get_bind()
    now = {"now": datetime.now(UTC).isoformat()}
    not_exists = "NOT EXISTS (SELECT 1 FROM mo_media mm WHERE mm.mo_id = mo_messages.id)"
    # RCS 소급 — SQLite json1 로 fileMessage 가 있는 행만 고른다.
    url = "json_extract(content_info_lst, '$.fileMessage.fileUrl')"
    mime = "json_extract(content_info_lst, '$.fileMessage.fileMIMEType')"
    # CASE 로 감싸 깨진 JSON 행에서 json_type 이 오류를 내지 않게 한다(SQLite 는 AND 단락을 보장하지 않음).
    has_file_message = (
        "(CASE WHEN content_info_lst IS NOT NULL AND json_valid(content_info_lst)"
        " THEN coalesce(json_type(content_info_lst, '$.fileMessage.fileUrl') = 'text'"
        f" AND {url} <> '', 0) ELSE 0 END) = 1"
    )
    bind.execute(
        sa.text(
            f"""
            INSERT INTO mo_media (mo_id, declared_mime, source, fetch_status, fetch_attempts, created_at)
            SELECT id, {mime}, 'RCS_URL',
                   CASE WHEN lower(coalesce({mime}, '')) LIKE 'image/%' THEN 'PENDING'
                        ELSE 'UNSUPPORTED' END,
                   0, :now
            FROM mo_messages
            WHERE {has_file_message} AND {not_exists}
            """
        ),
        now,
    )
    # MMS 소급 — moKey 없이 만든 대체 키(syn-)로는 조회할 수 없다.
    bind.execute(
        sa.text(
            f"""
            INSERT INTO mo_media (mo_id, source, fetch_status, fetch_attempts, created_at)
            SELECT id, 'MMS_API', 'PENDING', 0, :now
            FROM mo_messages
            WHERE content_cnt > 0 AND mo_key NOT LIKE 'syn-%'
              AND NOT ({has_file_message})
              AND {not_exists}
            """
        ),
        now,
    )


def downgrade() -> None:
    op.drop_index("idx_mo_media_fetch", table_name="mo_media")
    op.drop_table("mo_media")
