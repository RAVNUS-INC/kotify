"""팀 읽음 경계를 수신 MO ID 로 저장한다.

기존 caller별 행은 보존하고 phone 전체 MAX cursor를 공유한다. read_at 이전에 서버가
수신한(received_at) 메시지의 연속 ID prefix만 backfill한다. 공급자 mo_recv_dt는 지연 도착
시에도 과거 시각이므로 사용하지 않는다. 수신 시각이 ID 순서와 어긋나도 앞의 미관측 ID를
넘어가 읽음 처리하지 않는다. 불명확한 과거 시각은 읽음으로 추정하지 않는다.

MO 삭제 경로는 현재 없다. 수신 ID는 저장 순서대로 증가하며, 향후 수신 데이터 삭제/보관을
추가할 때에는 SQLite ID 재사용을 막는 별도 수신 sequence 또는 AUTOINCREMENT가 필요하다.

Revision ID: 0019
Revises: 0018
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def _received_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    except (ValueError, TypeError):
        return None


def upgrade() -> None:
    op.add_column("thread_reads", sa.Column("last_read_mo_id", sa.Integer, nullable=False, server_default="0"))
    op.create_index("idx_thread_reads_phone", "thread_reads", ["phone"])
    connection = op.get_bind()
    reads = connection.execute(sa.text("SELECT id, phone, read_at FROM thread_reads")).all()
    if not reads:
        return

    prefixes: dict[str, tuple[list[datetime], list[int]]] = {}
    for row in connection.execute(sa.text(
        "SELECT id, mo_number, received_at FROM mo_messages "
        "WHERE mo_number IN (SELECT phone FROM thread_reads) ORDER BY id"
    )):
        times, ids = prefixes.setdefault(row.mo_number, ([], []))
        timestamp = _received_time(row.received_at) or datetime.max.replace(tzinfo=UTC)
        times.append(max(times[-1], timestamp) if times else timestamp)
        ids.append(row.id)

    for row in reads:
        cutoff = _received_time(row.read_at)
        if cutoff is None or row.phone not in prefixes:
            continue
        times, ids = prefixes[row.phone]
        position = bisect_right(times, cutoff) - 1
        if position >= 0:
            connection.execute(sa.text(
                "UPDATE thread_reads SET last_read_mo_id = :cursor WHERE id = :row_id"
            ), {"cursor": ids[position], "row_id": row.id})


def downgrade() -> None:
    # caller/read_at와 기존 행을 보존했으므로 이전 코드의 읽음 표현으로 되돌릴 수 있다.
    op.drop_index("idx_thread_reads_phone", table_name="thread_reads")
    with op.batch_alter_table("thread_reads") as batch:
        batch.drop_column("last_read_mo_id")
