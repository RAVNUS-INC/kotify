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
    """cliKey 기반 개별 조회 결과를 처리한다. 확정(DONE)한 건수를 반환한다.

    요청 예외로 실패 기록한 행(compose._record_failed_chunk — FAILED 인데 result_code 없음)도 받는다
    (services.reconcile). msghub 가 접수했으면 결과대로 확정하거나 대기(REG/ING)로 되돌리고, 결과를 줄
    수 없다고 답하면(INVALID_KEY 키 오류·OVER_DATE 조회기간 초과) 실패를 유지하며 그 답을 result_code 에
    남긴다 — 재조정이 같은 행을 매 주기 다시 조회하지 않게 하는 표시다.
    """
    from app.msghub.schemas import SentQueryItem

    processed = 0
    campaign_ids: set[int] = set()

    for raw in raw_items:
        sq = SentQueryItem.from_dict(raw)
        if sq.status in ("OVER_DATE", "INVALID_KEY"):
            _record_no_result(db, sq.cli_key, sq.status)
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
        elif sq.status in ("REG", "ING") and msg.status != "FB_PENDING":
            # FB_PENDING 은 -fb 대체 SMS 접수·처리 중이라는 더 구체적인 상태라 덮지 않는다
            # (수신자 배지 fallback_sms).
            if msg.status == "FAILED":
                # 요청 예외로 실패 기록했지만 msghub 는 접수해 처리 중이다 — 집계를 실패에서 대기로
                # 옮긴다. 이후엔 미완료 행이라 리포트나 재조정이 확정한다.
                campaign_ids.add(msg.campaign_id)
            msg.status = sq.status

    # autoflush=False — 집계 SELECT 전에 ORM 변경을 명시 flush (process_report 참조)
    if campaign_ids:
        db.flush()
        for cid in campaign_ids:
            _refresh_campaign_counters(db, cid)

    db.flush()
    return processed


def _record_no_result(db: Session, cli_key: str, query_status: str) -> None:
    """조회가 결과를 주지 않은(INVALID_KEY·OVER_DATE) 요청 예외 실패 행에 그 상태를 result_code 로 남긴다.

    발송 후 조회 기간(reconcile._FAILED_QUERY_WINDOW) 안의 INVALID_KEY 는 msghub 가 그 요청을 접수하지
    않았다는 뜻으로 본다 — 접수하지 않은 키의 응답은 문서에 없고 실측 전이다. 그 키로 조회한 행에만
    남긴다 — _find_message 의 -fb·msgKey 대체 매칭은 다른 요청의 행을 고를 수 있다. 미완료 행은 접수
    응답을 받은 행이라 건드리지 않는다(조회 발송일 reqDt 가 어긋난 경우일 수 있다). 집계는 그대로다 —
    result_code 가 성공 코드가 아닌 FAILED 는 계속 실패로 센다.
    """
    if not cli_key:
        return
    msg = db.execute(select(Message).where(Message.cli_key == cli_key)).scalar_one_or_none()
    if msg is not None and msg.status == "FAILED" and msg.result_code is None:
        msg.result_code = query_status


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
    (routes.webhook._send_sms_fallback). 원래 키로 재전송된 실패 리포트를 그 행에
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


# 리포트 집계로 state 를 정하는 캠페인 state — 발송 중인 state 와 결과 state.
# 결과 state 도 다시 정한다. _update_message 는 DONE 만 건너뛰어 FAILED 행도 리포트를 받는데,
# 요청 예외(응답 타임아웃)로 실패 처리한 건을 msghub 는 실제로 접수했을 수 있다 —
# routes.webhook._send_sms_fallback, compose._record_failed_chunk(발송 때 FAILED·PARTIAL_FAILED·
# RESERVE_FAILED). RESERVE_CANCELED 는 msghub 가 취소를 받아들인 state 라 바꾸지 않는다 — 취소된
# 메시지가 재조정 조회에서 실패 코드로 확정되면 "발송 실패" 로 오표기된다.
_REPORT_DRIVEN_STATES = frozenset({
    "DISPATCHING", "DISPATCHED", "RESERVED",
    "COMPLETED", "PARTIAL_FAILED", "FAILED", "RESERVE_FAILED",
})


def _settled_state(ok_count: int, fail_count: int) -> str:
    """결과가 다 정해진 캠페인의 state (SPEC §4.1) — 실패 0 이면 COMPLETED, 성공 0 이면 FAILED.

    PARTIAL_FAILED 는 성공과 실패가 섞였을 때만이다. 소비자가 그렇게 읽는다 — 목록은 "sent"(일부
    성공), 알림은 "일부 실패 · {ok}/{total} 성공". 전건 실패는 발송 때(compose)처럼 FAILED 다.
    """
    if fail_count == 0:
        return "COMPLETED"
    if ok_count == 0:
        return "FAILED"
    return "PARTIAL_FAILED"


def _refresh_campaign_counters(db: Session, campaign_id: int) -> None:
    """캠페인의 ok/fail/pending/cost 카운터를 SQL 집계로 재계산하고, 결과가 다 정해졌으면 state 를 맞춘다.

    이미 결과 state 인 캠페인도 집계를 따른다 — 늦게 온 리포트가 실패로 기록한 행을 전달 성공으로
    바꾸면 집계만 성공이 되고 대시보드·알림센터·목록은 state 대로 실패를 보여 줬다.
    completed_at 은 결과가 처음 정해질 때만 기록한다(발송 때 전건 실패면 compose.dispatch_campaign).
    알림센터는 알림을 저장하지 않고 캠페인에서 파생하며 이 시각으로 정렬·읽음을 판정하므로, state 를
    다시 정할 때 새로 찍으면 읽은 알림이 새 알림으로 다시 뜬다.
    """
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

    # 모든 메시지 처리 완료 시 상태 전환. 청크 전송 중엔 아직 만들지 않은 메시지가 있어 pending 이
    # 0 으로 보일 수 있으므로 메시지 수가 total_count 에 이르렀는지도 본다.
    total_msgs = row.total or 0
    if (
        campaign.pending_count == 0
        and total_msgs >= campaign.total_count
        and campaign.state in _REPORT_DRIVEN_STATES
    ):
        campaign.state = _settled_state(campaign.ok_count, campaign.fail_count)
        if campaign.completed_at is None:
            campaign.completed_at = _now_iso()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()
