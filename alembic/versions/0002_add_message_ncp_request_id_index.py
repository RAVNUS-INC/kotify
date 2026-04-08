"""add idx_messages_ncp_request_id

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-08
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("idx_messages_ncp_request_id", "messages", ["ncp_request_id"])


def downgrade() -> None:
    op.drop_index("idx_messages_ncp_request_id", table_name="messages")
