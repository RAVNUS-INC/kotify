"""campaigns 에 idempotency_key 컬럼 + UNIQUE 인덱스 추가

POST /campaigns 멱등성(C1) — 클라이언트가 보낸 Idempotency-Key 를 저장하고
UNIQUE 제약으로 중복 발송(더블클릭/네트워크 재시도/동시 요청)을 차단한다.

기존 레코드와 키 미전송 요청은 NULL 로 남으며, NULL 은 UNIQUE 제약에서 서로
충돌하지 않으므로(표준 SQL) 키가 있는 신규 캠페인만 유일성이 강제된다.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-30
"""
import sqlalchemy as sa

from alembic import op

revision = "0011"
down_revision = "0010"


def upgrade() -> None:
    with op.batch_alter_table("campaigns") as batch:
        batch.add_column(sa.Column("idempotency_key", sa.Text, nullable=True))
        batch.create_index(
            "uq_campaigns_idempotency_key", ["idempotency_key"], unique=True
        )


def downgrade() -> None:
    with op.batch_alter_table("campaigns") as batch:
        batch.drop_index("uq_campaigns_idempotency_key")
        batch.drop_column("idempotency_key")
