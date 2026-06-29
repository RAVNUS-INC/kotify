"""messages.to_number 인덱스 추가 — 회신 담당자(lastSender) 조회 가속.

회신(MO) 수신 시 lookup_last_sender 가 `WHERE messages.to_number = ?` 로 그
고객에게 마지막으로 발송한 건을 찾는다. 이 조회는 msghub 웹훅 응답 전(blocking
구간)에 실행되므로, 인덱스가 없으면 messages 풀스캔 → 응답 지연 → 통신사
재전송 위험. messages 는 수신자 1명당 1행이라 빠르게 커진다.

Revision ID: 0014
Revises: 0013
"""
from __future__ import annotations

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("idx_messages_to_number", "messages", ["to_number"])


def downgrade() -> None:
    op.drop_index("idx_messages_to_number", table_name="messages")
