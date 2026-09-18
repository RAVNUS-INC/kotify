"""기존 RCS CHAT 성공 비용에 24시간·10건 세션 상한을 적용한다.

동일 (caller_number, to_number) 쌍의 첫 성공 발송부터 24시간을 한 세션으로 보고,
시간순 첫 10건은 8원, 이후 성공 건은 0원으로 보정한다. 리포트가 순서와 다르게
도착할 수 있으므로 각 쌍의 전체 성공 CHAT을 다시 배분하고 영향을 받은 캠페인 합계를
갱신한다. 실패·대체 SMS·다른 RCS 상품은 변경하지 않는다.

downgrade는 보정된 비용을 보존한다. 어떤 0원 CHAT이 상한으로 무료가 됐는지 별도
이력을 추가하지 않으므로 이전의 과다 집계로 안전하게 복원할 수 없다.

Revision ID: 0022
Revises: 0021
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import sqlalchemy as sa

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

_KST = ZoneInfo("Asia/Seoul")
_WINDOW = timedelta(hours=24)


def _parse(raw: str) -> datetime | None:
    try:
        value = raw.replace("Z", "+00:00") if raw.endswith("Z") else raw
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=_KST)
    except (AttributeError, TypeError, ValueError):
        return None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text("""
        SELECT m.id, m.campaign_id, m.to_number, m.cost,
               c.caller_number, c.created_at
        FROM messages m
        JOIN campaigns c ON c.id = m.campaign_id
        WHERE m.status = 'DONE' AND m.result_code = '10000'
          AND m.channel = 'RCS' AND m.product_code = 'CHAT'
    """)).mappings().all()

    grouped: dict[tuple[str, str], list[tuple[datetime, int, int, int]]] = defaultdict(list)
    updates: list[dict[str, int]] = []
    affected_campaigns: set[int] = set()
    for row in rows:
        # 메시지 비용이 이미 맞아도 캠페인 합계가 과거 값일 수 있어 모두 다시 집계한다.
        affected_campaigns.add(row["campaign_id"])
        event_time = _parse(row["created_at"])
        if event_time is None:
            if row["cost"] != 8:
                updates.append({"message_id": row["id"], "cost": 8})
            continue
        grouped[(row["caller_number"], row["to_number"])].append((
            event_time, row["id"], row["campaign_id"], row["cost"],
        ))

    for entries in grouped.values():
        entries.sort(key=lambda item: (item[0], item[1]))
        session_start: datetime | None = None
        session_units = 0
        for event_time, message_id, _campaign_id, old_cost in entries:
            if session_start is None or event_time >= session_start + _WINDOW:
                session_start = event_time
                session_units = 0
            session_units += 1
            new_cost = 8 if session_units <= 10 else 0
            if old_cost != new_cost:
                updates.append({"message_id": message_id, "cost": new_cost})

    if not affected_campaigns:
        return
    if updates:
        connection.execute(
            sa.text("UPDATE messages SET cost = :cost WHERE id = :message_id"), updates
        )
    connection.execute(sa.text("""
        UPDATE campaigns
        SET total_cost = (
            SELECT COALESCE(SUM(m.cost), 0) FROM messages m
            WHERE m.campaign_id = campaigns.id
        )
        WHERE id = :campaign_id
    """), [{"campaign_id": campaign_id} for campaign_id in affected_campaigns])


def downgrade() -> None:
    # 무료 처리된 건을 다른 0원 원인과 구분할 수 없어 데이터 보정은 유지한다.
    pass
