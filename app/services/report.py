"""발송 결과 리포트 처리 서비스.

웹훅 수신 → Message/Campaign 업데이트 → 비용 계산.
cliKey 기반 개별 조회 fallback도 지원.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models import Campaign, Message
from app.msghub.codes import SUCCESS_CODE, calculate_cost
from app.msghub.schemas import RecvInfo, ReportItem, SendResponse
from app.util.phone import mask_phone

if TYPE_CHECKING:
    from app.msghub.client import MsghubClient

log = logging.getLogger(__name__)


def process_report(db: Session, items: list[ReportItem]) -> tuple[int, list[Message]]:
    """리포트 항목들을 처리하여 Message/Campaign을 업데이트한다.

    Args:
        db: SQLAlchemy 세션 (커밋은 호출자가 담당).
        items: ReportItem 목록 (웹훅 또는 폴링에서 수신).

    Returns:
        (처리된 메시지 건수, SMS fallback이 필요한 메시지 목록).
        fallback 목록은 양방향 CHAT(RPCSAXX001) 캠페인 — 대화방 답장
        (compose.dispatch_chat_reply) — 의 RCS 실패 메시지다. 단방향 RCS 는
        msghub 가 fbInfoLst 로 자동 대체하므로 해당 없다.
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

        if _update_message(msg, item):
            campaign_ids.add(msg.campaign_id)
            processed += 1
            if item.result_code != SUCCESS_CODE:
                failed_msgs.append(msg)

    fallback_needed = _mark_chat_fallback(db, failed_msgs)

    # autoflush=False 이므로 _update_message의 ORM 변경을 집계 SELECT 전에
    # 명시적으로 flush 해야 한다. flush를 안 하면 SUM(...) 쿼리가 업데이트
    # 이전 상태(status=REG 등)를 읽어 rcs_count/ok_count가 모두 0으로 찍힘.
    if campaign_ids:
        db.flush()
        for cid in campaign_ids:
            _refresh_campaign_counters(db, cid)

    db.flush()
    return processed, fallback_needed


def process_sent_query(db: Session, raw_items: list[dict]) -> tuple[int, list[Message]]:
    """cliKey 기반 개별 조회 결과를 처리한다.

    Returns:
        (처리된 메시지 건수, SMS fallback이 필요한 메시지 목록) — process_report 와 같다.
        양방향 실패는 먼저 확정한 경로가 대체 발송해야 한다. 리포트 웹훅이 늦으면(msghub 는
        실패한 웹훅을 72시간 재시도) 재조정이 먼저 확정하고, 뒤늦게 온 실패 리포트는 이미
        확정된 행이라 _update_message 가 버린다 — 여기서 넘기지 않으면 답장이 끝내 안 간다.
    """
    from app.msghub.schemas import SentQueryItem

    processed = 0
    campaign_ids: set[int] = set()
    failed_msgs: list[Message] = []

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

        # 원래 cliKey 로 조회하는 사이 웹훅이 대체 발송해 cliKey 를 바꿨다 — 조회 결과는
        # 대체 전 시도의 것이다 (_update_message 와 같은 이유).
        if _is_superseded_report(msg, sq.cli_key):
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
            if not success:
                failed_msgs.append(msg)
        elif sq.status in ("REG", "ING") and msg.status != "FB_PENDING":
            # FB_PENDING 은 -fb 대체 SMS 접수·처리 중이라는 더 구체적인 상태라 덮지 않는다
            # (수신자 배지 fallback_sms).
            msg.status = sq.status

    fallback_needed = _mark_chat_fallback(db, failed_msgs)

    # autoflush=False — 집계 SELECT 전에 ORM 변경을 명시 flush (process_report 참조)
    if campaign_ids:
        db.flush()
        for cid in campaign_ids:
            _refresh_campaign_counters(db, cid)

    db.flush()
    return processed, fallback_needed


async def send_sms_fallback(
    db: Session, client: MsghubClient | None, messages: list[Message]
) -> int:
    """양방향 CHAT RCS 실패 메시지에 대해 SMS fallback을 발송한다.

    process_report(웹훅)·process_sent_query(재조정)가 FB_PENDING 으로 넘긴 목록을 받는다 — 실패를
    먼저 확정한 경로가 보내고, 다른 경로에 뒤늦게 온 같은 실패는 버려진다(_update_message,
    _is_superseded_report). 호출자는 실패 확정과 대체 발송을 한 트랜잭션으로 커밋한다.

    각 메시지의 cli_key를 {원본}-fb로 갱신하여 SMS 리포트 매칭에 사용하고, report_dt 에는 대체
    SMS 요청 시각을 남긴다 — 재조정이 -fb cliKey 를 조회할 발송일자(reconcile._query_req_dt)다.
    양방향 실패 리포트 시각과는 날짜가 다를 수 있다(재조정의 뒤늦은 확정, 웹훅 재시도).

    넘겨받은 행은 대체 SMS 가 접수됐을 때만 FB_PENDING 으로 남긴다. 접수되지 않은 건(클라이언트
    없음, 요청 예외, 수신자 단위 거부)엔 리포트가 오지 않으므로 FAILED 로 확정한다 — 그대로 두면
    영영 대기로 남는다.

    Returns:
        fallback 접수 건수.
    """
    if client is None:
        log.error("SMS fallback 실패: msghub 클라이언트 미초기화")

    # 캠페인별로 그룹화 (caller_number, content 조회용)
    campaign_cache: dict[int, Campaign] = {}
    for msg in messages:
        if msg.campaign_id not in campaign_cache:
            campaign_cache[msg.campaign_id] = db.get(Campaign, msg.campaign_id)

    sent = 0
    for msg in messages:
        campaign = campaign_cache.get(msg.campaign_id)
        if client is None or campaign is None:
            msg.status = "FAILED"
            msg.result_desc = (msg.result_desc or "") + " (SMS fallback 실패)"
            continue

        fb_cli_key = f"{msg.cli_key}-fb"
        msg.cli_key = fb_cli_key
        msg.status = "FB_PENDING"
        msg.report_dt = _now_iso()

        try:
            recv = RecvInfo(cli_key=fb_cli_key, phone=msg.to_number)
            resp = await client.send_sms(
                callback=campaign.caller_number,
                msg=campaign.content,
                recv_list=[recv],
            )
        except Exception:
            log.exception("SMS fallback 발송 실패: msg_id=%s, phone=%s", msg.id, mask_phone(msg.to_number))
            msg.status = "FAILED"
            msg.result_desc = (msg.result_desc or "") + " (SMS fallback 실패)"
            continue

        # 요청이 성공(최상위 10000)해도 수신자 단위로 거부될 수 있다(31101 수신번호 에러 등)
        # — send_sms 는 최상위 코드만 검사한다. 판정은 dispatch_chat_reply 와 같다.
        item = resp.items[0] if isinstance(resp, SendResponse) and resp.items else None
        if item is not None and item.code != SUCCESS_CODE:
            log.warning(
                "SMS fallback 수신자 거부: msg_id=%s, phone=%s, code=%s",
                msg.id, mask_phone(msg.to_number), item.code,
            )
            msg.status = "FAILED"
            msg.result_code = item.code
            msg.result_desc = f"{item.message} (SMS fallback 거부)"
            continue

        sent += 1

    # 실패 확정 경로는 이 행들을 FB_PENDING(대기)으로 집계했다 — 실패로 확정한 건을 다시
    # 집계해야 캠페인이 발송 중(pending_count)으로 남지 않는다. autoflush=False 라 먼저 flush.
    db.flush()
    for campaign_id in campaign_cache:
        _refresh_campaign_counters(db, campaign_id)
    return sent


def _mark_chat_fallback(db: Session, failed_msgs: list[Message]) -> list[Message]:
    """실패로 확정한 메시지 중 양방향 CHAT(RPCSAXX001) 답장을 FB_PENDING 으로 넘겨 반환한다.

    대화방 답장(compose.dispatch_chat_reply)은 msghub 가 자동 대체하지 않아 send_sms_fallback 이
    보낸다. -fb 행은 그 대체 SMS 의 결과라 제외한다 — 답장 하나에 대체 SMS 는 한 번이다.
    """
    if not failed_msgs:
        return []

    chat_cids = set(
        db.execute(
            select(Campaign.id).where(
                Campaign.id.in_({m.campaign_id for m in failed_msgs}),
                Campaign.rcs_messagebase_id == "RPCSAXX001",
            )
        ).scalars().all()
    )
    fallback_needed: list[Message] = []
    for msg in failed_msgs:
        if msg.campaign_id in chat_cids and not msg.cli_key.endswith("-fb"):
            msg.status = "FB_PENDING"
            fallback_needed.append(msg)
    return fallback_needed


def _find_message(
    db: Session,
    cli_key: str,
    msg_key: str | None,
    phone: str | None = None,
) -> Message | None:
    """cliKey → {cliKey}-fb → msgKey → (phone, status=REG/ING/PENDING) 순으로 Message를 찾는다.

    msghub v11 delivery report는 cliKey 외에도 phone 필드를 포함한다. cliKey
    없이 리포트가 도달하는 엣지 케이스(콘솔 설정 누락, 대량발송 일부 유실 등)
    에서 phone으로 최근 발송 중인 메시지를 찾아 보조 매칭한다.

    {cliKey}-fb 는 양방향 실패 후 대체 SMS 를 보내며 cliKey 를 바꾼 행이다
    (send_sms_fallback). 원래 키로 재전송된 실패 리포트를 그 행에
    붙여야 _update_message 가 버린다. 못 찾으면 msgKey(대체 SMS 리포트가 msg_key 를
    바꾼 뒤엔 불일치)도 빗나가 phone 매칭으로 같은 번호의 다른 미완료 메시지에 붙는다.
    """
    if cli_key:
        msg = db.execute(
            select(Message).where(Message.cli_key == cli_key)
        ).scalar_one_or_none()
        if msg:
            return msg
        if not cli_key.endswith("-fb"):
            msg = db.execute(
                select(Message).where(Message.cli_key == f"{cli_key}-fb")
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
    if phone:
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


def _is_superseded_report(msg: Message, report_cli_key: str) -> bool:
    """대체 발송(-fb)으로 cliKey 가 바뀐 행에 온, 대체 전 시도의 리포트인가.

    -fb 행의 결과는 그 cliKey 로 보낸 대체 발송의 리포트만 정한다. 다른 cliKey 로 온
    리포트(원래 RCS 키, 또는 cliKey 없이 msgKey·phone 으로 매칭된 것)를 적용하면 안 된다
    — msghub 가 양방향 실패 리포트를 재전송하면(웹훅 응답 유실·지연) FB_PENDING 행이
    DONE·실패 코드로 덮이고, 뒤이은 대체 SMS 성공 리포트는 DONE 이라 버려져 고객이 받은
    답장이 영구 실패로 남았다. cliKey 없이 온 대체 SMS 리포트도 여기서 버려지지만, FB_PENDING
    행은 재조정(services.reconcile)이 -fb cliKey 로 조회해 확정한다.
    """
    return (msg.cli_key or "").endswith("-fb") and report_cli_key != msg.cli_key


def _update_message(msg: Message, item: ReportItem) -> bool:
    """ReportItem으로 Message를 업데이트한다. 이미 DONE이거나 대체 전 시도의 리포트면 skip.

    Returns:
        True if updated, False if skipped (idempotency).
    """
    if msg.status == "DONE":
        log.debug("이미 완료된 메시지 skip: id=%s, cliKey=%s", msg.id, msg.cli_key)
        return False

    if _is_superseded_report(msg, item.cli_key):
        log.info(
            "대체 발송 전 시도의 리포트 skip: id=%s, cliKey=%s (현재 %s)",
            msg.id, item.cli_key, msg.cli_key,
        )
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
