"""첨부파일의 RCS/MMS 공급자 ID와 만료 시각을 분리한다."""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("attachments", sa.Column("msghub_rcs_file_id", sa.Text(), nullable=True))
    op.add_column("attachments", sa.Column("rcs_file_expires_at", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("attachments", "rcs_file_expires_at")
    op.drop_column("attachments", "msghub_rcs_file_id")
