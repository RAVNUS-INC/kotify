"""mo_messages 테이블 추가 — RCS 양방향 MO(수신) 저장

고객이 RCS 챗봇으로 보낸 답장 및 자동응답 과금 데이터를 저장한다.
멱등성을 위해 moKey에 UNIQUE 제약을 건다.

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-20
"""
import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"


def upgrade() -> None:
    op.create_table(
        "mo_messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("mo_key", sa.Text, nullable=False),
        sa.Column("mo_number", sa.Text, nullable=False),
        sa.Column("mo_callback", sa.Text, nullable=True),
        sa.Column("mo_type", sa.Text, nullable=True),
        sa.Column("product_code", sa.Text, nullable=True),
        sa.Column("mo_title", sa.Text, nullable=True),
        sa.Column("mo_msg", sa.Text, nullable=True),
        sa.Column("telco", sa.Text, nullable=True),
        sa.Column("content_cnt", sa.Integer, nullable=False, server_default="0"),
        sa.Column("content_info_lst", sa.Text, nullable=True),
        sa.Column("mo_recv_dt", sa.Text, nullable=True),
        sa.Column("raw_payload", sa.Text, nullable=False),
        sa.Column("received_at", sa.Text, nullable=False),
        sa.UniqueConstraint("mo_key", name="uq_mo_messages_mo_key"),
    )
    op.create_index("idx_mo_messages_mo_number", "mo_messages", ["mo_number"])
    op.create_index("idx_mo_messages_received_at", "mo_messages", ["received_at"])


def downgrade() -> None:
    op.drop_index("idx_mo_messages_received_at", table_name="mo_messages")
    op.drop_index("idx_mo_messages_mo_number", table_name="mo_messages")
    op.drop_table("mo_messages")
