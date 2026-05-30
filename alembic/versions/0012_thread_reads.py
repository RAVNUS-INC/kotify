"""thread_reads 테이블 추가 — 대화방 팀 공유 읽음 상태

대화방(caller:phone)별 마지막 읽음 시각을 팀 전체 기준으로 저장한다.
unread 판정은 "마지막 고객(MO) 메시지 시각 > read_at" (app/services/chat.py).

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-30
"""
import sqlalchemy as sa

from alembic import op

revision = "0012"
down_revision = "0011"


def upgrade() -> None:
    op.create_table(
        "thread_reads",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("caller", sa.Text, nullable=False),
        sa.Column("phone", sa.Text, nullable=False),
        sa.Column("read_at", sa.Text, nullable=False),
        sa.UniqueConstraint("caller", "phone", name="uq_thread_reads_caller_phone"),
    )


def downgrade() -> None:
    op.drop_table("thread_reads")
