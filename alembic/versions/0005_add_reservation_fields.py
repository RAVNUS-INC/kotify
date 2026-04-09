"""Add reservation fields to campaigns

NCP SENS v2 예약 발송 지원:
- reserve_time: 예약 실행 시각 (NCP 형식 'YYYY-MM-DD HH:mm', 로컬)
- reserve_timezone: 예약 타임존 (기본 'Asia/Seoul')

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-10
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.add_column(sa.Column("reserve_time", sa.Text, nullable=True))
        batch_op.add_column(sa.Column("reserve_timezone", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.drop_column("reserve_timezone")
        batch_op.drop_column("reserve_time")
