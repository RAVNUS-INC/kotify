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
from app.util.phone import mask_phone

log = logging.getLogger(__name__)


def process_report(db: Session, items: list[ReportItem]) -> tuple[int, list[Message]]:
    """리포트 항목들을 처리하여 Message/Campaign을 업데이트한다.

    Args:
        db: SQLAlchemy 세션 (커밋은 호출자가 담당).
        items: ReportItem 목록 (웹훅 또는 폴링에서 수신).

    Returns:
        (처리된 메시지 건수, 대체 발송이 필요한 메시지 목록).
        대체 발송 목록은 대화방 양방향 답장(CHAT, RPCSAXX001 캠페인)이 리포트에서 실패한
        메시지다. 양방향 요청엔 fbInfoLst 가 없어 msghub 가 대체 발송하지 않으므로 FB_PENDING
        으로 두고 호출자(webhook)가 단방향 RCS 로 보낸다(compose.dispatch_chat_fallback).
        cliKey 가 "-fb"(직접 발송)·"-rcs-fb"(단방향 RCS)로 끝나는 건은 이미 대체 발송이라
        실패해도 다시 넣지 않는다.
    """
    processed = 0
    campaign_ids: set[int] = set()
    failed_msgs: list[Message] = []

    for item in items:
        msg = _find_message(db, item.cli_key, item.msg_key, item.phone)
        if msg is None:
            log.warning(
                "리포트 매칭 실패: cliKey=%s, msgKey=%s, phone=%s",
                item.cli_key, item.msg_key, mask_phone(item.phone),
            )
            continue
        if _superseded_by_fallback(item.cli_key, msg.cli_key):
            log.info("대체 발송 전 원본 리포트 재수신 — 건너뜀: cliKey=%s", item.cli_key)
            continue
        if item.cli_key and _fallback_base_key(item.cli_key) == msg.cli_key:
            # 대체 발송 키로 바꾼 커밋이 롤백돼 원본 키 행에 매칭됨 — 실제 발송 키로 맞춰야 실패
            # 리포트여도 아래에서 다시 대체 발송하지 않고, 원본 리포트 재수신도 걸러진다.
            msg.cli_key = item.cli_key

        if _update_message(msg, item):
            campaign_ids.add(msg.campaign_id)
            processed += 1
            if item.result_code != SUCCESS_CODE:
                failed_msgs.append(msg)

    # 양방향 CHAT 캠페인의 실패 메시지 → 대체 발송 필요 (이미 대체 발송한 "-fb" 건 제외)
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

    # autoflush=False 이므로 _update_message의 ORM 변경을 집계 SELECT 전에
    # 명시적으로 flush 해야 한다. flush를 안 하면 SUM(...) 쿼리가 업데이트
    # 이전 상태(status=REG 등)를 읽어 rcs_count/ok_count가 모두 0으로 찍힘.
    if campaign_ids:
        db.flush()
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

    # autoflush=False — 집계 SELECT 전에 ORM 변경을 명시 flush (process_report 참조)
    if campaign_ids:
        db.flush()
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
    에서 phone으로 최근 발송 중인 메시지를 찾아 보조 매칭한다. cliKey 가 있는데
    맞는 행이 없는 리포트는 우리 발송이 아니거나 이미 처리한 원본(대체 발송으로 키가
    바뀜)이라 phone 매칭하지 않는다 — 같은 번호의 다른 발송에 결과가 붙는다.
    """
    if cli_key:
        msg = db.execute(
            select(Message).where(Message.cli_key == cli_key)
        ).scalar_one_or_none()
        if msg:
            return msg
        # 대체 발송 키(-rcs-fb/-fb) 리포트인데 행은 아직 원본 키 — 대체 발송이 접수된 뒤 그 키로
        # 바꾼 커밋이 롤백된 경우(webhook 400 → msghub 재전송 대기). 발송은 이미 나갔으므로 원본
        # 키 행이 이 리포트의 메시지다. phone 보조매칭이 모호해 버려지면 FB_PENDING 영구 대기.
        base_key = _fallback_base_key(cli_key)
        if base_key:
            msg = db.execute(
                select(Message).where(Message.cli_key == base_key)
            ).scalar_one_or_none()
            if msg:
                return msg

    if msg_key:
        msg = db.execute(
            select(Message).where(Message.msg_key == msg_key)
        ).scalar_one_or_none()
        if msg:
            return msg

    # phone 보조 매칭 — 미완료 메시지가 정확히 1건일 때만 매칭한다 (H4).
    # 동일 번호가 2개+ 캠페인에 동시에 미완료로 남아 있으면 cliKey 없는 리포트가
    # 어느 캠페인의 결과인지 확신할 수 없다. limit(1)+order_by 로 "가장 최근 1건"을
    # 집으면 엉뚱한 캠페인에 결과가 귀속돼 과금·집계가 오염되므로, 모호하면 보류한다.
    # limit(2) 는 "정확히 1건 vs 2건+" 판별에 필요한 최소 조회량이다.
    if phone and not cli_key:
        candidates = db.execute(
            select(Message)
            .where(
                Message.to_number == phone,
                Message.status.in_(("PENDING", "REG", "ING", "FB_PENDING")),
            )
            .order_by(Message.id.desc())
            .limit(2)
        ).scalars().all()
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) >= 2:
            log.warning(
                "phone 보조매칭 보류: phone=%s 에 미완료 메시지 %d건 — 모호하여 매칭하지 않음",
                mask_phone(phone), len(candidates),
            )

    return None


_FALLBACK_SUFFIXES = ("-rcs-fb", "-fb")  # -rcs-fb 가 -fb 로도 끝나므로 긴 것부터


def _fallback_base_key(cli_key: str) -> str | None:
    """대체 발송 cliKey 의 원본 키. 대체 발송 키가 아니면 None."""
    for suffix in _FALLBACK_SUFFIXES:
        if cli_key.endswith(suffix):
            return cli_key[: -len(suffix)]
    return None


def _superseded_by_fallback(report_cli_key: str, msg_cli_key: str | None) -> bool:
    """리포트가 대체 발송으로 cliKey 를 바꾸기 전 원본 요청의 것인가.

    원본 결과는 대체 발송을 시작할 때 이미 반영했다. 그 리포트를 msghub 가 다시 보내면(웹훅
    응답 지연 등) cliKey 는 안 맞아도 원본 msgKey 가 남은 행(중복 코드로 접수만 확인했거나
    대체 발송이 FAILED)에 매칭돼, 대체 발송 결과를 원본 실패로 덮어쓴다 — 그래서 건너뛴다.
    """
    return bool(report_cli_key) and msg_cli_key in {
        f"{report_cli_key}{suffix}" for suffix in _FALLBACK_SUFFIXES
    }


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
    total_msgs = row.total or 0
    if campaign.pending_count == 0 and campaign.state in ("DISPATCHING", "DISPATCHED", "RESERVED"):
        if total_msgs >= campaign.total_count:
            campaign.state = "COMPLETED" if campaign.fail_count == 0 else "PARTIAL_FAILED"
            campaign.completed_at = _now_iso()
    elif (
        campaign.state in ("PARTIAL_FAILED", "FAILED")
        and campaign.pending_count == 0
        and campaign.fail_count == 0
        and total_msgs >= campaign.total_count
    ):
        # 실패로 마감한 메시지가 늦게 온 리포트로 전부 성공 보정됨 — 예: 타임아웃이라 FAILED 로
        # 둔 대체 발송이 실제론 접수돼 도달. 대시보드·알림이 실패로 남지 않게 완료로 고친다.
        campaign.state = "COMPLETED"
        campaign.completed_at = campaign.completed_at or _now_iso()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
