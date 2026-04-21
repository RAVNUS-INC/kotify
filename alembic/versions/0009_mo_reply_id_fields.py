"""mo_messages 에 reply_id / postback_id / postback_data 컬럼 추가

msghub 실제 RCS 양방향 MO 페이로드(rcsBiLst)에 따라 replyId / postbackId /
postbackData 를 함께 저장한다. replyId 는 양방향 답장 발송(/rcs/bi/v1.1)
시 msghub에 넘겨야 하는 핵심 값.

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-22
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"


def upgrade() -> None:
    with op.batch_alter_table("mo_messages") as batch:
        batch.add_column(sa.Column("reply_id", sa.Text, nullable=True))
        batch.add_column(sa.Column("postback_id", sa.Text, nullable=True))
        batch.add_column(sa.Column("postback_data", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("mo_messages") as batch:
        batch.drop_column("postback_data")
        batch.drop_column("postback_id")
        batch.drop_column("reply_id")
