"""초기 스키마 생성.

Revision ID: 0001
Revises:
Create Date: 2026-04-08
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users ────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("sub", sa.Text, primary_key=True),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("roles", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("last_login_at", sa.Text, nullable=False),
    )

    # ── callers ──────────────────────────────────────────────────────────────
    op.create_table(
        "callers",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("number", sa.Text, nullable=False, unique=True),
        sa.Column("label", sa.Text, nullable=False),
        sa.Column("active", sa.Integer, nullable=False, server_default="1"),
        sa.Column("is_default", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.Text, nullable=False),
    )

    # ── settings ─────────────────────────────────────────────────────────────
    op.create_table(
        "settings",
        sa.Column("key", sa.Text, primary_key=True),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("is_secret", sa.Integer, nullable=False, server_default="0"),
        # updated_by는 'setup', 'system' 같은 비-user 출처도 허용 — FK 제거
        sa.Column("updated_by", sa.Text, nullable=True),
        sa.Column("updated_at", sa.Text, nullable=False),
    )

    # ── campaigns ────────────────────────────────────────────────────────────
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("created_by", sa.Text, sa.ForeignKey("users.sub"), nullable=False),
        sa.Column("caller_number", sa.Text, nullable=False),
        sa.Column("message_type", sa.Text, nullable=False),
        sa.Column("subject", sa.Text, nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("total_count", sa.Integer, nullable=False),
        sa.Column("ok_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("fail_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("pending_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("completed_at", sa.Text, nullable=True),
    )
    op.create_index("idx_campaigns_created_by", "campaigns", ["created_by"])
    op.create_index("idx_campaigns_created_at", "campaigns", ["created_at"])

    # ── ncp_requests ─────────────────────────────────────────────────────────
    op.create_table(
        "ncp_requests",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.Integer, sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("request_id", sa.Text, nullable=True),
        sa.Column("request_time", sa.Text, nullable=True),
        sa.Column("http_status", sa.Integer, nullable=True),
        sa.Column("status_code", sa.Text, nullable=True),
        sa.Column("status_name", sa.Text, nullable=True),
        sa.Column("error_body", sa.Text, nullable=True),
        sa.Column("sent_at", sa.Text, nullable=False),
        sa.UniqueConstraint("campaign_id", "chunk_index", name="uq_ncp_requests_chunk"),
    )
    op.create_index("idx_ncp_requests_request_id", "ncp_requests", ["request_id"])

    # ── messages ─────────────────────────────────────────────────────────────
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.Integer, sa.ForeignKey("campaigns.id"), nullable=False),
        sa.Column(
            "ncp_request_id", sa.Integer, sa.ForeignKey("ncp_requests.id"), nullable=False
        ),
        sa.Column("to_number", sa.Text, nullable=False),
        sa.Column("to_number_raw", sa.Text, nullable=False),
        sa.Column("message_id", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="PENDING"),
        sa.Column("result_status", sa.Text, nullable=True),
        sa.Column("result_code", sa.Text, nullable=True),
        sa.Column("result_message", sa.Text, nullable=True),
        sa.Column("telco_code", sa.Text, nullable=True),
        sa.Column("complete_time", sa.Text, nullable=True),
        sa.Column("last_polled_at", sa.Text, nullable=True),
        sa.Column("poll_count", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_index("idx_messages_campaign_id", "messages", ["campaign_id"])
    op.create_index("idx_messages_status", "messages", ["status"])
    op.create_index("idx_messages_message_id", "messages", ["message_id"])

    # ── audit_logs ───────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("actor_sub", sa.Text, nullable=True),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("target", sa.Text, nullable=True),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("ip", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_index("idx_messages_message_id", "messages")
    op.drop_index("idx_messages_status", "messages")
    op.drop_index("idx_messages_campaign_id", "messages")
    op.drop_table("messages")
    op.drop_index("idx_ncp_requests_request_id", "ncp_requests")
    op.drop_table("ncp_requests")
    op.drop_index("idx_campaigns_created_at", "campaigns")
    op.drop_index("idx_campaigns_created_by", "campaigns")
    op.drop_table("campaigns")
    op.drop_table("settings")
    op.drop_table("callers")
    op.drop_table("users")
