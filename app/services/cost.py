"""저장된 메시지 비용의 세션 단위 보정."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.models import Campaign, Message
from app.msghub.codes import SUCCESS_CODE, allocate_chat_session_costs
from app.util.time import parse_mixed_ts


def apply_chat_session_cap(db: Session, changed_messages: Iterable[Message]) -> set[int]:
    """변경된 CHAT과 같은 대화의 성공 비용을 재배분한다.

    리포트는 발송 순서와 다르게 도착할 수 있다. 새 성공 건만 0/8원으로 결정하면 늦게
    도착한 과거 리포트가 상한 순서를 뒤집으므로, 영향을 받은 (caller, phone) 쌍의
    성공 CHAT 전체를 발송 시각순으로 다시 계산한다. 반환값은 비용이 바뀐 캠페인 ID다.
    """
    pairs: set[tuple[str, str]] = set()
    for message in changed_messages:
        if not (
            message.status == "DONE"
            and message.result_code == SUCCESS_CODE
            and message.channel == "RCS"
            and message.product_code == "CHAT"
        ):
            continue
        campaign = db.get(Campaign, message.campaign_id)
        if campaign is not None:
            pairs.add((campaign.caller_number, message.to_number))
    if not pairs:
        return set()

    rows = db.execute(
        select(Message, Campaign.caller_number, Campaign.created_at)
        .join(Campaign, Campaign.id == Message.campaign_id)
        .where(
            tuple_(Campaign.caller_number, Message.to_number).in_(pairs),
            Message.status == "DONE",
            Message.result_code == SUCCESS_CODE,
            Message.channel == "RCS",
            Message.product_code == "CHAT",
        )
    ).all()

    grouped: dict[tuple[str, str], list[tuple[datetime, Message]]] = defaultdict(list)
    changed_campaign_ids: set[int] = set()
    for message, caller, created_at in rows:
        event_time = parse_mixed_ts(created_at)
        if event_time is None:
            # 시각을 모르면 다른 건을 무료 처리할 근거가 없다. 보수적으로 건당 과금한다.
            if message.cost != 8:
                message.cost = 8
                changed_campaign_ids.add(message.campaign_id)
            continue
        grouped[(caller, message.to_number)].append((event_time, message))

    for entries in grouped.values():
        entries.sort(key=lambda item: (item[0], item[1].id or 0))
        costs = allocate_chat_session_costs(event_time for event_time, _ in entries)
        for (_, message), cost in zip(entries, costs, strict=True):
            if message.cost != cost:
                message.cost = cost
                changed_campaign_ids.add(message.campaign_id)

    return changed_campaign_ids
