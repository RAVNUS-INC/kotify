"""발송 결과 리포트 처리 서비스.

웹훅 수신 → Message/Campaign 업데이트 → 비용 계산.
cliKey 기반 개별 조회 fallback도 지원.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Campaign, Message
from app.msghub.codes import SUCCESS_CODE, calculate_cost
from app.msghub.schemas import ReportItem

log = logging.getLogger(__name__)


def process_report(db: Session, items: list[ReportItem]) -> tuple[int, list[Message]]:
    """리포트 항목들을 처리하여 Message/Campaign을 업데이트한다.

    Args:
        db: SQLAlchemy 세션 (커밋은 호출자가 담당).
        items: ReportItem 목록 (웹훅 또는 폴링에서 수신).

    Returns:
        (처리된 메시지 건수, SMS fallback이 필요한 메시지 목록).
        fallback 목록은 양방향 CHAT(RPCSAXX001) 캠페인의 RCS 실패 메시지.
    """
    processed = 0
    campaign_ids: set[int] = set()
    failed_msgs: list[Message] = []

    for item in items:
        msg = _find_message(db, item.cli_key, item.msg_key, item.phone)
        if msg is None:
            log.warning(
                "리포트 매칭 실패: cliKey=%s, msgKey=%s, phone=%s",
                item.cli_key, item.msg_key, item.phone,
            )
            continue

        if _update_message(msg, item):
            campaign_ids.add(msg.campaign_id)
            processed += 1
            if item.result_code != SUCCESS_CODE:
                failed_msgs.append(msg)

    # 양방향 CHAT 캠페인의 실패 메시지 → SMS fallback 필요
    fallback_needed: list[Message] = []
    if failed_msgs:
        chat_cids = set(
            db.execute(
                select(Campaign.id).where(
                    Campaign.id.in_({m.campaign_id for m in failed_msgs}),
                    Campaign.rcs_messagebase_id == "RPCSAXX001",
                )
            ).scalars().all()
        )
        for msg in failed_msgs:
            if msg.campaign_id in chat_cids and not msg.cli_key.endswith("-fb"):
                msg.status = "FB_PENDING"
                fallback_needed.append(msg)

    for cid in campaign_ids:
        _refresh_campaign_counters(db, cid)

    db.flush()
    return processed, fallback_needed


def process_sent_query(db: Session, raw_items: list[dict]) -> int:
    """cliKey 기반 개별 조회 결과를 처리한다."""
    from app.msghub.schemas import SentQueryItem

    processed = 0
    campaign_ids: set[int] = set()

    for raw in raw_items:
        sq = SentQueryItem.from_dict(raw)
        if sq.status in ("OVER_DATE", "INVALID_KEY"):
            continue

        msg = _find_message(db, sq.cli_key, sq.msg_key)
        if msg is None:
            continue

        # 이미 완료된 메시지는 skip (idempotency)
        if msg.status == "DONE":
            continue

        if sq.status == "DONE" and sq.result_code:
            success = sq.result_code == SUCCESS_CODE
            msg.status = "DONE"
            msg.result_code = sq.result_code
            msg.result_desc = sq.result_code_desc
            msg.channel = sq.ch or msg.channel
            msg.product_code = sq.product_code or msg.product_code
            msg.cost = calculate_cost(sq.ch, sq.product_code, success)
            msg.telco = sq.telco or msg.telco
            msg.report_dt = sq.rpt_dt or _now_iso()

            if sq.fb_reason_lst:
                msg.fb_reason = json.dumps(
                    [{"ch": fb.ch, "code": fb.fb_result_code, "desc": fb.fb_result_desc}
                     for fb in sq.fb_reason_lst],
                    ensure_ascii=False,
                )

            campaign_ids.add(msg.campaign_id)
            processed += 1
        elif sq.status in ("REG", "ING"):
            msg.status = sq.status

    for cid in campaign_ids:
        _refresh_campaign_counters(db, cid)

    db.flush()
    return processed


def _find_message(
    db: Session,
    cli_key: str,
    msg_key: str | None,
    phone: str | None = None,
) -> Message | None:
    """cliKey → msgKey → (phone, status=REG/ING/PENDING) 순으로 Message를 찾는다.

    msghub v11 delivery report는 cliKey 외에도 phone 필드를 포함한다. cliKey
    없이 리포트가 도달하는 엣지 케이스(콘솔 설정 누락, 대량발송 일부 유실 등)
    에서 phone으로 최근 발송 중인 메시지를 찾아 보조 매칭한다.
    """
    if cli_key:
        msg = db.execute(
            select(Message).where(Message.cli_key == cli_key)
        ).scalar_one_or_none()
        if msg:
            return msg

    if msg_key:
        msg = db.execute(
            select(Message).where(Message.msg_key == msg_key)
        ).scalar_one_or_none()
        if msg:
            return msg

    # phone 보조 매칭 — 아직 완료되지 않은 최근 메시지만 대상 (ambiguity 최소화)
    if phone:
        msg = db.execute(
            select(Message)
            .where(
                Message.to_number == phone,
                Message.status.in_(("PENDING", "REG", "ING", "FB_PENDING")),
            )
            .order_by(Message.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if msg:
            return msg

    return None


def _update_message(msg: Message, item: ReportItem) -> bool:
    """ReportItem으로 Message를 업데이트한다. 이미 DONE이면 skip.

    Returns:
        True if updated, False if skipped (idempotency).
    """
    if msg.status == "DONE":
        log.debug("이미 완료된 메시지 skip: id=%s, cliKey=%s", msg.id, msg.cli_key)
        return False

    success = item.result_code == SUCCESS_CODE

    msg.status = "DONE"
    msg.msg_key = item.msg_key or msg.msg_key
    msg.result_code = item.result_code
    msg.result_desc = item.result_code_desc
    msg.channel = item.ch
    msg.product_code = item.product_code
    msg.cost = calculate_cost(item.ch, item.product_code, success)
    msg.telco = item.telco
    msg.report_dt = item.rpt_dt or _now_iso()
    msg.complete_time = item.rpt_dt or _now_iso()

    if item.fb_reason_lst:
        msg.fb_reason = json.dumps(
            [{"ch": fb.ch, "code": fb.fb_result_code, "desc": fb.fb_result_desc}
             for fb in item.fb_reason_lst],
            ensure_ascii=False,
        )

    return True


def _refresh_campaign_counters(db: Session, campaign_id: int) -> None:
    """캠페인의 ok/fail/pending/cost 카운터를 SQL 집계로 재계산한다."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        return

    # SQL aggregate — O(1) 메모리, DB에서 직접 집계
    is_success = (Message.status == "DONE") & (Message.result_code == SUCCESS_CODE)
    is_fail = (Message.status.in_(("FAILED", "DONE"))) & (
        (Message.result_code != SUCCESS_CODE) | (Message.result_code.is_(None))
    )
    is_rcs = (Message.channel == "RCS") & is_success
    is_fallback = (Message.channel.in_(("SMS", "LMS", "MMS"))) & is_success

    row = db.execute(
        select(
            func.count().label("total"),
            func.sum(case((is_success, 1), else_=0)).label("ok"),
            func.sum(case((is_fail, 1), else_=0)).label("fail"),
            func.coalesce(func.sum(Message.cost), 0).label("total_cost"),
            func.sum(case((is_rcs, 1), else_=0)).label("rcs_count"),
            func.sum(case((is_fallback, 1), else_=0)).label("fallback_count"),
        ).where(Message.campaign_id == campaign_id)
    ).one()

    campaign.ok_count = row.ok or 0
    campaign.fail_count = row.fail or 0
    campaign.pending_count = max(0, (row.total or 0) - (row.ok or 0) - (row.fail or 0))
    campaign.total_cost = row.total_cost or 0
    campaign.rcs_count = row.rcs_count or 0
    campaign.fallback_count = row.fallback_count or 0

    # 모든 메시지 처리 완료 시 상태 전환
    if campaign.pending_count == 0 and campaign.state in ("DISPATCHING", "DISPATCHED", "RESERVED"):
        total_msgs = row.total or 0
        if total_msgs >= campaign.total_count:
            campaign.state = "COMPLETED" if campaign.fail_count == 0 else "PARTIAL_FAILED"
            campaign.completed_at = _now_iso()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
