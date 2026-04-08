"""contacts + groups + members 테이블

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("phone", sa.Text, nullable=True),
        sa.Column("email", sa.Text, nullable=True),
        sa.Column("department", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("active", sa.Integer, nullable=False, server_default="1"),
        sa.Column("last_sent_at", sa.Text, nullable=True),
        sa.Column("last_sent_channel", sa.Text, nullable=True),
        sa.Column("created_by", sa.Text, sa.ForeignKey("users.sub"), nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )
    op.create_index("idx_contacts_phone", "contacts", ["phone"])
    op.create_index("idx_contacts_email", "contacts", ["email"])
    op.create_index("idx_contacts_department", "contacts", ["department"])
    op.create_index("idx_contacts_name", "contacts", ["name"])
    op.create_index("idx_contacts_active", "contacts", ["active"])

    op.create_table(
        "contact_groups",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_by", sa.Text, sa.ForeignKey("users.sub"), nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
    )

    op.create_table(
        "contact_group_members",
        sa.Column(
            "group_id",
            sa.Integer,
            sa.ForeignKey("contact_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "contact_id",
            sa.Integer,
            sa.ForeignKey("contacts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("added_by", sa.Text, nullable=True),
        sa.Column("added_at", sa.Text, nullable=False),
    )
    op.create_index("idx_cgm_contact_id", "contact_group_members", ["contact_id"])


def downgrade() -> None:
    op.drop_index("idx_cgm_contact_id", table_name="contact_group_members")
    op.drop_table("contact_group_members")
    op.drop_table("contact_groups")
    op.drop_index("idx_contacts_active", table_name="contacts")
    op.drop_index("idx_contacts_name", table_name="contacts")
    op.drop_index("idx_contacts_department", table_name="contacts")
    op.drop_index("idx_contacts_email", table_name="contacts")
    op.drop_index("idx_contacts_phone", table_name="contacts")
    op.drop_table("contacts")
