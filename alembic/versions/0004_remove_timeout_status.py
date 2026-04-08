"""Remove TIMEOUT status — convert existing records to UNKNOWN

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-08
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE messages SET status = 'UNKNOWN' WHERE status = 'TIMEOUT'")


def downgrade() -> None:
    pass  # irreversible
