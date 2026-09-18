"""발송 결과 리포트 처리 서비스.

웹훅 수신 → Message/Campaign 업데이트 → 비용 계산.
cliKey 기반 개별 조회 fallback도 지원.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
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

# 메시지 행이 아직 안 보일 수 있는 캠페인 id → 겹친 표시 수 (awaiting_record).
_awaiting_record: Counter[int] = Counter()

# compose._make_cli_key 의 c{캠페인}-{청크}-{순번}, 양방향 답장은 시도 토큰(compose._make_chat_reply_cli_key), 대체 발송은 -fb.
_CLI_KEY = re.compile(r"c(\d+)-\d+-\d+(?:-[0-9a-f]{6})?(?:-fb)?")


class ReportBeforeRecord(Exception):
    """행을 아직 커밋하지 않은 발송의 리포트 — 반영하지 않고 msghub 재전송을 받아야 한다 (awaiting_record)."""

    def __init__(self, cli_key: str) -> None:
        super().__init__(f"행 기록 전 리포트: cliKey={cli_key}")
        self.cli_key = cli_key


@contextmanager
def awaiting_record(campaign_ids: Iterable[int]) -> Iterator[None]:
    """블록 동안 캠페인의 리포트가 메시지 행 기록(커밋)보다 먼저 올 수 있다고 표시한다.

    msghub 는 요청 응답보다 리포트를 먼저 보내기도 한다. 청크 발송(compose.dispatch_campaign)은 응답을 받아야
    행을 기록하고, 양방향 답장(compose.dispatch_chat_reply)과 대체 SMS(send_sms_fallback — 웹훅·재조정, -fb)는 발송을 기다린
    트랜잭션이 커밋돼야 행이 보인다 — 응답은 httpx 타임아웃(30초)까지 걸린다. 그사이 온 리포트는 매칭할 행이 없어
    200 으로 버려졌다. 웹훅은 표시된 캠페인의 리포트인데 그 cliKey 행이 없으면 반영하지 않고(split_unrecorded)
    400 으로 답해 msghub 재전송을 받는다(공식 문서 2.8 §3 — 400 은 "실패로 전달시 재처리 가능", 재시도 기본
    10초, 리포트 보관 72시간).

    재전송 요청은 그 cliKey 행이 커밋되거나 블록이 끝나면(발송 포기·롤백 포함) 멈춘다 — 캠페인의 청크 발송 전체,
    답장 발송, 대체 SMS 트랜잭션보다 길어지지 않는다. 롤백한 답장의 리포트는 그 id 를 다시 받은 단방향 fallback
    (chat.send_reply)을 보내는 동안까지 이어진다. 그 뒤에도 행이 없는 리포트는 기록하지 않은 메시지의 것이라
    버린다(_find_message).

    단일 uvicorn 워커 전제(deploy/kotify.service --workers 1, services.events 와 같음)라 프로세스 메모리로
    충분하다 — 재시작하면 진행 중이던 발송도 끝났다.
    """
    ids = list(campaign_ids)
    _awaiting_record.update(ids)
    try:
        yield
    finally:
        for campaign_id in ids:
            _awaiting_record[campaign_id] -= 1
            if _awaiting_record[campaign_id] <= 0:
                del _awaiting_record[campaign_id]


def _is_unrecorded(db: Session, item: ReportItem) -> bool:
    """표시된 캠페인(awaiting_record)의 리포트인데 그 cliKey 행이 아직 없는가.

    그 키의 행이 있으면 기록이 끝난 것이라 평소대로 처리한다 — 청크를 보내는 동안에도 앞 청크 리포트는 바로
    반영된다. 짝 키 행(_find_message)은 기록으로 치지 않는다. 대체 SMS 트랜잭션이 커밋되기 전 -fb 리포트는 원래
    키 행에 짝 키로 매칭되는데, 그 행에 쓰려면 같은 이벤트 루프에서 SMS 응답을 기다리는 그 트랜잭션의 쓰기
    잠금을 busy timeout(5초) 동안 막혀 기다리다 실패한다 — 그동안 앱 전체가 멈춘다.
    """
    if not _awaiting_record:
        return False
    match = _CLI_KEY.fullmatch(item.cli_key or "")
    if match is None or int(match.group(1)) not in _awaiting_record:
        return False
    recorded = db.execute(
        select(Message.id).where(Message.cli_key == item.cli_key).limit(1)
    ).first()
    return recorded is None


def split_unrecorded(
    db: Session, items: list[ReportItem],
) -> tuple[list[ReportItem], list[ReportItem]]:
    """리포트를 (지금 반영할 것, msghub 재전송으로 다시 받을 것) 으로 나눈다.

    행 기록 전 리포트(_is_unrecorded)가 있으면 웹훅은 나머지를 반영·커밋하고 400 으로 배치째 재전송을 받는다.
    cliKey 리포트는 재전송돼도 같은 행을 찾아 DONE·대체 전 시도로 건너뛰므로 먼저 반영해도 된다 — 배치째
    미루면 같은 배치의 다른 리포트(양방향 실패 답장의 대체 SMS 등)가 행 기록 때까지 늦는다. cliKey 없는
    리포트는 같이 미룬다 — phone 보조매칭은 한 번 반영된 뒤 재전송되면 그새 생긴 같은 번호의 다른 미완료
    메시지에 붙을 수 있다.
    """
    unrecorded = [_is_unrecorded(db, item) for item in items]
    if not any(unrecorded):
        return list(items), []
    pairs = list(zip(items, unrecorded, strict=True))
    ready = [item for item, late in pairs if item.cli_key and not late]
    deferred = [item for item, late in pairs if late or not item.cli_key]
    return ready, deferred


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

    Raises:
        ReportBeforeRecord: 행을 커밋하기 전일 수 있는 발송(awaiting_record)의 리포트가 섞였다. 아무것도
            반영하지 않는다 — 웹훅은 split_unrecorded 로 나눠 행이 있을 리포트만 넘긴다.
    """
    unrecorded = next((item for item in items if _is_unrecorded(db, item)), None)
    if unrecorded is not None:
        raise ReportBeforeRecord(unrecorded.cli_key)

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


def process_sent_query(
    db: Session, raw_items: list[dict], *, recovered_campaign_ids: set[int] | None = None,
) -> tuple[int, list[Message]]:
    """cliKey 기반 개별 조회 결과를 처리한다.

    요청 예외로 실패 기록한 행(compose._record_failed_chunk — FAILED 인데 result_code 없음)도 받는다
    (services.reconcile). msghub 가 접수했으면 결과대로 확정하거나 대기(REG/ING)로 되돌리고, 결과를 줄
    수 없다고 답하면(INVALID_KEY 키 오류·OVER_DATE 조회기간 초과) 실패를 유지하며 그 답을 result_code 에
    남긴다 — 재조정이 같은 행을 매 주기 다시 조회하지 않게 하는 표시다.

    recovered_campaign_ids 를 넘기면 FAILED → REG/ING 로 복구한 캠페인 id 를 넣는다.
    확정(DONE) 건수에는 포함하지 않지만, 호출자는 커밋 뒤 실패 → 대기 화면 변경을 알려야 한다.

    Returns:
        (확정(DONE)한 메시지 건수, SMS fallback이 필요한 메시지 목록) — process_report 와 같다.
        양방향 실패는 먼저 확정한 경로가 대체 발송해야 한다. 리포트 웹훅이 늦으면(msghub 는
        실패한 웹훅을 72시간 재시도) 재조정이 먼저 확정하고, 뒤늦게 온 실패 리포트는 이미
        확정된 행이라 _update_message 가 버린다 — 여기서 넘기지 않으면 답장이 끝내 안 간다.
    """
    from app.msghub.schemas import SentQueryItem

    processed = 0
    campaign_ids: set[int] = set()
    recovering_campaign_ids: set[int] = set()
    failed_msgs: list[Message] = []

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
            if not success:
                failed_msgs.append(msg)
        elif sq.status in ("REG", "ING") and msg.status != "FB_PENDING":
            # FB_PENDING 은 -fb 대체 SMS 접수·처리 중이라는 더 구체적인 상태라 덮지 않는다
            # (수신자 배지 fallback_sms).
            if msg.status == "FAILED":
                # 요청 예외로 실패 기록했지만 msghub 는 접수해 처리 중이다 — 집계를 실패에서 대기로
                # 옮긴다. 이후엔 미완료 행이라 리포트나 재조정이 확정한다.
                campaign_ids.add(msg.campaign_id)
                recovering_campaign_ids.add(msg.campaign_id)
            msg.status = sq.status

    fallback_needed = _mark_chat_fallback(db, failed_msgs)

    # autoflush=False — 집계 SELECT 전에 ORM 변경을 명시 flush (process_report 참조)
    if campaign_ids:
        db.flush()
        for cid in campaign_ids:
            _refresh_campaign_counters(db, cid)
            if cid in recovering_campaign_ids:
                campaign = db.get(Campaign, cid)
                if (
                    campaign is not None
                    and campaign.pending_count > 0
                    and campaign.state in _REPORT_DRIVEN_STATES
                ):
                    # 요청 예외를 실패로 봤지만 실제 발송은 진행 중이다. DISPATCHED 는 API/알림이
                    # 발송 완료로 표시하므로 DISPATCHING 으로 복구한다. 예약 건도 실행 시각이 지난
                    # 뒤 재조정 대상이 된다. 첫 결과 시각(completed_at)은 알림 읽음 기준이라 유지한다.
                    campaign.state = "DISPATCHING"

    db.flush()
    if recovered_campaign_ids is not None:
        recovered_campaign_ids.update(recovering_campaign_ids)
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
    """cliKey → 대체 발송 전후 짝 키 → msgKey → (cliKey 없는 리포트만) phone 순으로 Message를 찾는다.

    msghub v11 delivery report는 cliKey 외에도 phone 필드를 포함한다. cliKey
    없이 리포트가 도달하는 엣지 케이스(콘솔 설정 누락, 대량발송 일부 유실 등)
    에서 phone으로 최근 발송 중인 메시지를 찾아 보조 매칭한다.

    cliKey 가 있는 리포트는 phone 으로 찾지 않는다. cliKey 는 메시지마다 고유해(compose._make_cli_key,
    대체 발송은 -fb, 양방향 답장은 롤백된 캠페인 id 를 다음 캠페인이 다시 받아 시도마다 토큰을 붙인다 —
    compose._make_chat_reply_cli_key) 그 키로 못 찾은 리포트는 같은 번호의 다른 메시지가 아니라 기록하지 않은 메시지의
    것이다 — 행 기록 전(웹훅이 재전송을 받는다, split_unrecorded), 같은 웹훅을 쓰는 다른 시스템의 발송, 롤백된
    양방향 답장(compose.dispatch_chat_reply). phone 으로 붙이면 다른 메시지가 그 결과(msgKey·채널·과금)로
    확정되고, 그 메시지의 제 리포트는 DONE 이라 버려졌다.

    {cliKey}-fb 는 양방향 실패 후 대체 SMS 를 보내며 cliKey 를 바꾼 행이다
    (send_sms_fallback). 원래 키로 재전송된 실패 리포트를 그 행에
    붙여야 _update_message 가 버린다. 반대로 -fb 리포트인데 행이 원래 키로 남았으면 대체 SMS 를
    보낸 뒤 키를 바꾼 트랜잭션이 커밋되지 못한 것이다(웹훅 400) — SMS 는 나갔으므로 그 행의 결과다
    (_update_message 가 키를 맞춘다).
    """
    if cli_key:
        msg = db.execute(
            select(Message).where(Message.cli_key == cli_key)
        ).scalar_one_or_none()
        if msg:
            return msg
        paired_key = cli_key.removesuffix("-fb") if cli_key.endswith("-fb") else f"{cli_key}-fb"
        msg = db.execute(
            select(Message).where(Message.cli_key == paired_key)
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

    # 원래 키 행에 매칭된 -fb 리포트(_find_message) — 행을 그 키로 맞춘다. 안 맞추면 대체 SMS 가 실패일 때
    # process_report 가 양방향 실패로 보고 같은 -fb cliKey 로 대체 SMS 를 또 요청한다.
    if item.cli_key == f"{msg.cli_key}-fb":
        msg.cli_key = item.cli_key

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
# send_sms_fallback, compose._record_failed_chunk(발송 때 FAILED·PARTIAL_FAILED·
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

    예약 취소(CANCELED) 행은 성공·실패·대기 어디에도 세지 않는다. 대기로 세면 일부 청크만
    취소돼 RESERVED 로 남은 캠페인이 나머지가 전달돼도 완료로 전이하지 못한다.

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
    is_canceled = Message.status == "CANCELED"
    is_rcs = (Message.channel == "RCS") & is_success
    is_fallback = (Message.channel.in_(("SMS", "LMS", "MMS"))) & is_success

    row = db.execute(
        select(
            func.count().label("total"),
            func.sum(case((is_success, 1), else_=0)).label("ok"),
            func.sum(case((is_fail, 1), else_=0)).label("fail"),
            func.sum(case((is_canceled, 1), else_=0)).label("canceled"),
            func.coalesce(func.sum(Message.cost), 0).label("total_cost"),
            func.sum(case((is_rcs, 1), else_=0)).label("rcs_count"),
            func.sum(case((is_fallback, 1), else_=0)).label("fallback_count"),
        ).where(Message.campaign_id == campaign_id)
    ).one()

    campaign.ok_count = row.ok or 0
    campaign.fail_count = row.fail or 0
    campaign.pending_count = max(
        0, (row.total or 0) - (row.ok or 0) - (row.fail or 0) - (row.canceled or 0)
    )
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
