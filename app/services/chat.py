"""대화방 서비스 — MT(발송) + MO(수신)을 스레드 단위로 머지.

스레드 키: (caller_number, phone) = (mo_callback, mo_number)
답장: 기존 dispatch_campaign 재사용 (단건 캠페인 생성).
"""
from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.orm import Session

from app.models import Campaign, Message, MoMessage, ThreadRead, User
from app.msghub.codes import (
    CHAT_SESSION_CAP_KRW,
    CHAT_SESSION_MAX_UNITS,
    CHAT_SESSION_WINDOW_HOURS,
    REPLY_ID_SAFETY_MARGIN_MINUTES,
    REPLY_ID_VALID_HOURS,
    SUCCESS_CODE,
    chat_session_cost,
)
from app.services.compose import (
    dispatch_campaign,
    dispatch_chat_reply,
    validate_message,
)
from app.util.time import parse_mixed_ts

if TYPE_CHECKING:
    from app.msghub.client import MsghubClient

log = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    """대화방 한 개의 메시지(발신 또는 수신)."""

    direction: str                    # "OUT" (우리→고객) 또는 "IN" (고객→우리)
    body: str
    timestamp: str                    # ISO 문자열 (정렬 및 표시용)
    status: str | None = None         # OUT 전용
    delivery: str | None = None       # OUT 전용: pending/sent/failed/cancelled, 모르면 None
    channel: str | None = None        # OUT 전용: RCS/SMS/LMS/MMS
    cost: int | None = None           # OUT 전용: 원
    telco: str | None = None          # IN 전용
    product_code: str | None = None   # IN 전용 (MORCS/SMSMO 등)
    mo_id: int | None = None
    campaign_id: int | None = None
    msg_id: int | None = None


@dataclass
class ChatThread:
    """대화방 목록 한 건."""

    caller: str
    phone: str
    last_timestamp: str
    last_body: str
    last_direction: str
    unread: bool          # 안읽음 = 마지막 고객(MO) 메시지가 팀 read_at 이후
    mo_count: int
    mt_count: int


SEND_CHANNELS = ("rcs", "sms")

# 캠페인 message_type → 일반(직접) 발송 채널. 신규 행은 short/long/image, 과거 행은 SMS/LMS/MMS.
_DIRECT_CHANNEL = {
    "short": "SMS", "long": "LMS", "image": "MMS",
    "SMS": "SMS", "LMS": "LMS", "MMS": "MMS",
}


def outbound_channel(
    report_channel: str | None,
    rcs_messagebase_id: str | None,
    message_type: str | None,
    cli_key: str | None,
    status: str | None,
) -> str:
    """발신(OUT) 메시지의 표시 채널 — 리포트의 실제 도달 채널, 없으면 요청한 전송 방식.

    Message.channel 은 웹훅 리포트가 와야 채워진다. 접수 직후·리포트 미도착·발송 실패
    건은 비어 있어, 예전엔 무조건 SMS 로 표시되어 RCS 로 보낸 답장도 SMS 처럼 보였다.

    cliKey 가 "-fb" 인 건은 RCS 요청이 실패해 직접 SMS/LMS/MMS 로 대체 발송된 것이다
    (compose._send_chunk_direct, webhook._send_sms_fallback). 그 리포트가 오기 전(DONE
    아님)엔 캠페인이 RCS 여도 대체 발송 채널로 표시한다.
    """
    direct = _DIRECT_CHANNEL.get(message_type or "", "SMS")
    if (cli_key or "").endswith("-fb") and status != "DONE":
        return direct
    if report_channel:
        return report_channel
    return "RCS" if rcs_messagebase_id else direct


# 리포트(최종 결과)를 기다리는 상태. FB_PENDING 은 양방향 리포트 실패 후 webhook 이
# 일반 SMS 로 대체 발송해 그 리포트를 기다리는 중이다(routes.webhook._send_sms_fallback).
_AWAITING_REPORT_STATUSES = frozenset({"PENDING", "REG", "ING", "FB_PENDING"})


def delivery_status(
    status: str | None, result_code: str | None, cli_key: str | None
) -> str | None:
    """발신(OUT) 메시지의 전달 상태 — "pending" | "sent" | "failed" | "cancelled", 모르면 None.

    result_code 만으로는 판정할 수 없다. 접수(REG) 행에는 접수 응답의 성공 코드(10000)가,
    FB_PENDING 행에는 실패한 RCS 리포트 코드가 남아 있어 코드만 보면 각각 전달·실패로
    오판한다. 리포트 수신(DONE)일 때만 코드로 성공을 가린다.

    - PENDING·REG·ING·FB_PENDING: 리포트 대기(대체 발송 중 포함) → pending
    - DONE: 성공 코드면 sent, 아니면(코드 없음 포함) failed
    - FAILED: 요청 단계 실패(청크·item 거부, 대체 발송 요청 실패) → failed
    - CANCELED: 예약 취소로 발송되지 않음 → cancelled. 취소 라우트(routes.campaigns.
      cancel_campaign)가 대기 행을 바꾸고, 기존 행은 alembic 0017 이 옮겨 cliKey 없는 NCP
      시절 행도 올 수 있다.
    - NCP 시절 행: 결과 컬럼이 alembic 0007 에서 삭제돼 알 수 없음 → None. COMPLETED·
      UNKNOWN 등은 그 외 상태로 걸러지고, 그때도 쓰던 PENDING 은 cliKey 없음으로 가린다
      — msghub 이후 PENDING 행은 항상 cliKey 가 있고(compose), 없는 행은 재조정도
      안 돼 영영 대기로 남는다.

    실패 기준은 캠페인 집계(report._refresh_campaign_counters)와 같다. 취소는 실패로
    세지 않는다.
    """
    if status == "PENDING" and not cli_key:
        return None
    if status in _AWAITING_REPORT_STATUSES:
        return "pending"
    if status == "DONE":
        return "sent" if result_code == SUCCESS_CODE else "failed"
    if status == "FAILED":
        return "failed"
    if status == "CANCELED":
        return "cancelled"
    return None


def _coalesce_ts(*values: str | None) -> str:
    """None이 아닌 첫 번째 문자열 반환. 전부 None이면 빈 문자열."""
    for v in values:
        if v:
            return v
    return ""


def _parse_ts_for_sort(raw: str | None) -> float:
    """정렬용 통일 키 — ISO 8601 또는 msghub 네이티브(yyyyMMddHHmmss) 모두 지원.

    ISO 와 msghub 네이티브 포맷이 섞이면 lexicographic 비교가 틀어진다
    ('2026-04-22T...' vs '20260422...' 에서 '-' < '0' 이라 ISO 가 항상 앞).
    실시간 값으로 변환 후 epoch float 를 돌려 정렬 키로 사용.
    실패 시 0.0 반환 (가장 앞).
    """
    # 단일 파서(app.util.time.parse_mixed_ts)로 위임 — ISO(오프셋)·msghub naive KST
    # ·14자리 네이티브를 모두 일관 처리. 실패 시 0.0(가장 앞).
    dt = parse_mixed_ts(raw)
    return dt.timestamp() if dt else 0.0


def thread_unread(last_mo_ts: str | None, read_at: str | None) -> bool:
    """안읽음 판정 — 고객(MO) 최종 메시지가 팀 read_at 이후인가.

    ISO/msghub 네이티브(yyyyMMddHHmmss) 혼재 포맷을 epoch 로 파싱해 비교한다.
    고객 메시지가 없으면 False, read_at 이 없으면(한 번도 안 읽음) True.
    목록(list_threads)과 상세(routes.threads)가 동일 기준을 쓰도록 공유한다.
    """
    if not last_mo_ts:
        return False
    return _parse_ts_for_sort(last_mo_ts) > _parse_ts_for_sort(read_at or "")


def _ts_rank(raw: str | None) -> tuple[int, float]:
    """대화방 목록의 시각 비교 키 — 시각(실제 시각순) > 파싱할 수 없는 값 > 값 없음.

    저장 포맷이 섞여(msghub 원본은 오프셋 없는 KST, 우리가 기록하는 값은 UTC ISO) 문자열
    대소로는 비교할 수 없다. 파싱 불가 값을 값 없음 위에 두어, 그런 시각의 회신뿐인 대화방도
    빈 발송이 아니라 그 회신(IN)으로 보인다.
    """
    if not raw:
        return (0, 0.0)
    dt = parse_mixed_ts(raw)
    return (2, dt.timestamp()) if dt else (1, 0.0)


# 시각 문자열 모양 — 자릿수·구분자 위치·시간대가 고정이라 같은 모양끼리는 문자열 대소가 실제
# 시각 순서다. 모양이 섞이면 어긋난다: KST 벽시계와 UTC 는 9시간 차이, 같은 날짜면 공백 구분이
# 'T' 보다 작고, '2026-..' 은 '2026..' 보다 늘 작다. 흔한 모양을 먼저 둔다(CASE 는 앞에서 멈춤).
_D2, _D4 = "[0-9]" * 2, "[0-9]" * 4
_YMD, _HMS = f"{_D4}-{_D2}-{_D2}", f"{_D2}:{_D2}:{_D2}"
_TS_SHAPES = (
    f"{_YMD}T{_HMS}",                      # msghub rptDt·moRecvDt (오프셋 없음 = KST)
    f"{_YMD}T{_HMS}.{'[0-9]' * 6}+00:00",  # datetime.now(UTC).isoformat() — 리포트·수신 시각 대체값
    f"{_YMD}T{_HMS}+00:00",                # 같은 값에서 마이크로초가 0 인 경우
    f"{_YMD} {_HMS}",                      # moRecvDt 공백 구분 표기 (구 문서)
    "[0-9]" * 14,                          # yyyyMMddHHmmss (KST)
)


def _ts_shape(ts: ColumnElement[str]) -> ColumnElement[str]:
    """SQL 식 — 시각 문자열의 모양 키. 목록에 없는 모양은 '~' + 문자열 자신이 키다.

    SQL 의 max()·ORDER BY 는 문자열 대소라 모양이 섞인 시각에서 늦은 값을 못 고른다. 그룹·
    파티션에 이 키를 더해 모양별 1위만 후보로 뽑고(번호당 보통 1~2행) 실제 시각 비교는
    Python(_ts_rank)에서 한다. 모르는 모양은 문자열마다 따로 후보가 되므로 결과는 그대로
    맞고 행만 늘어난다. NULL 은 NULL 키(한 그룹)다.
    """
    return case(
        *((ts.op("GLOB")(shape), str(n)) for n, shape in enumerate(_TS_SHAPES)),
        else_="~" + ts,
    )


# 번호 목록을 IN 절로 묶는 단위 — 구버전 SQLite 바인드 변수 상한(999) 아래로 유지.
_IN_CHUNK = 500


def _chunks(phones: list[str]) -> Iterator[list[str]]:
    for i in range(0, len(phones), _IN_CHUNK):
        yield phones[i : i + _IN_CHUNK]


def _latest_bodies(candidates: list) -> dict[str, str]:
    """(phone, id, ts, body) 후보 → phone 별 실제 시각이 가장 늦은 행의 본문.

    시각이 같으면 id 가 작은 행 — 예전 번호별 `ORDER BY 시각 DESC LIMIT 1` 을 SQLite 가 먼저
    스캔한(인덱스 순 = id 가 작은) 행으로 풀던 것과 같다. 모양이 다른 같은 순간도 같은 규칙.
    """
    best: dict[str, tuple] = {}  # phone → ((시각 비교 키, -id), 본문)
    for r in candidates:
        key = (_ts_rank(r.ts), -r.id)
        if r.phone not in best or key > best[r.phone][0]:
            best[r.phone] = (key, r.body or "")
    return {phone: body for phone, (_, body) in best.items()}


def _batch_last_mo_bodies(db: Session, phones: list[str]) -> dict[str, str]:
    """phone → 가장 최근 고객 수신(MO) 본문. 번호마다 쿼리하지 않고 창 함수로 한 번에 고른다.

    기준 시각은 coalesce(mo_recv_dt, received_at). 창 함수 정렬은 문자열 대소라 번호·시각
    모양별 1위만 후보로 뽑고 실제 시각은 _latest_bodies 가 비교한다. 목록 집계와 달리
    mo_callback 이 NULL 인 행도 후보다.
    """
    ts = func.coalesce(MoMessage.mo_recv_dt, MoMessage.received_at)
    candidates: list = []
    for chunk in _chunks(phones):
        ranked = (
            select(
                MoMessage.id,
                func.row_number()
                .over(
                    partition_by=(MoMessage.mo_number, _ts_shape(ts)),
                    order_by=(ts.desc(), MoMessage.id),
                )
                .label("rn"),
            )
            .where(MoMessage.mo_number.in_(chunk))
            .subquery()
        )
        candidates += db.execute(
            select(
                MoMessage.mo_number.label("phone"),
                MoMessage.id,
                ts.label("ts"),
                MoMessage.mo_msg.label("body"),
            )
            .select_from(ranked)
            .join(MoMessage, MoMessage.id == ranked.c.id)
            .where(ranked.c.rn == 1)
        ).all()
    return _latest_bodies(candidates)


def _batch_last_mt_bodies(db: Session, phones: list[str]) -> dict[str, str]:
    """phone → 가장 최근 발송(MT) 캠페인 본문. 고르는 규칙은 _batch_last_mo_bodies 와 같다.

    기준 시각은 coalesce(complete_time, report_dt) — 둘 다 NULL(리포트 전)인 행은 시각이 있는
    행에 진다. 순위는 id 만 매기고 본문은 1위 행에서만 읽는다(긴 LMS 본문을 번호의 발송 이력
    전체만큼 정렬하지 않도록).
    """
    ts = func.coalesce(Message.complete_time, Message.report_dt)
    candidates: list = []
    for chunk in _chunks(phones):
        ranked = (
            select(
                Message.id,
                func.row_number()
                .over(
                    partition_by=(Message.to_number, _ts_shape(ts)),
                    order_by=(ts.desc(), Message.id),
                )
                .label("rn"),
            )
            .join(Campaign, Campaign.id == Message.campaign_id)
            .where(Message.to_number.in_(chunk))
            .subquery()
        )
        candidates += db.execute(
            select(
                Message.to_number.label("phone"),
                Message.id,
                ts.label("ts"),
                Campaign.content.label("body"),
            )
            .select_from(ranked)
            .join(Message, Message.id == ranked.c.id)
            .join(Campaign, Campaign.id == Message.campaign_id)
            .where(ranked.c.rn == 1)
        ).all()
    return _latest_bodies(candidates)


def _batch_read_at(db: Session, phones: list[str]) -> dict[str, str]:
    """phone → 팀 공유 마지막 읽음 시각.

    대화방을 phone 으로 묶으므로 같은 고객에 caller 별 읽음행이 여럿이면 가장 최근 읽음
    시각으로 합친다(이미 읽은 대화가 안읽음으로 되살아나는 것 방지).
    """
    read_at: dict[str, str] = {}
    for chunk in _chunks(phones):
        for r in db.execute(
            select(ThreadRead.phone, ThreadRead.read_at).where(ThreadRead.phone.in_(chunk))
        ).all():
            if (r.read_at or "") > read_at.get(r.phone, ""):
                read_at[r.phone] = r.read_at or ""
    return read_at


def list_threads(
    db: Session, limit: int = 50, offset: int = 0
) -> tuple[list[ChatThread], int]:
    """대화방 목록을 최근 활동순으로 반환한다.

    정렬·자르기는 번호별 집계값(마지막 시각·방향)만으로 먼저 하고, 마지막 본문과 읽음
    상태는 잘라낸 페이지의 번호만 묶어 조회한다. 쿼리 수는 전체 번호 수와 무관하다
    (집계 2 + 읽음 1 + 본문 MO/MT 각 1). 번호마다 본문을 조회하면 대량 발송 수신자까지
    전부 쿼리해 번호 수에 비례해 느려진다.

    시각은 msghub 원본(오프셋 없는 KST)과 우리가 기록한 UTC ISO 가 섞여 있어 방향·마지막
    시각·대표 caller·정렬을 모두 파싱한 실제 시각(_ts_rank)으로 비교한다. SQL 집계는 시각
    모양별 최댓값만 후보로 뽑는다(_ts_shape) — 문자열 max 는 모양이 섞이면 늦은 값을 놓친다.
    """
    # MT 측 — campaigns.caller_number + messages.to_number (+ 시각 모양) 으로 그룹
    mt_ts = func.coalesce(Message.complete_time, Message.report_dt)
    mt_rows = db.execute(
        select(
            Campaign.caller_number.label("caller"),
            Message.to_number.label("phone"),
            func.max(mt_ts).label("last_t"),
            func.count().label("cnt"),
        )
        .join(Campaign, Campaign.id == Message.campaign_id)
        .group_by(Campaign.caller_number, Message.to_number, _ts_shape(mt_ts))
    ).all()

    # MO 측 — mo_callback + mo_number (+ 시각 모양) 으로 그룹
    mo_ts = func.coalesce(MoMessage.mo_recv_dt, MoMessage.received_at)
    mo_rows = db.execute(
        select(
            MoMessage.mo_callback.label("caller"),
            MoMessage.mo_number.label("phone"),
            func.max(mo_ts).label("last_t"),
            func.count().label("cnt"),
        )
        .where(MoMessage.mo_callback.is_not(None))
        .group_by(MoMessage.mo_callback, MoMessage.mo_number, _ts_shape(mo_ts))
    ).all()

    # 대량 발송 리포트는 같은 초에 몰려 같은 문자열이 반복되므로 서로 다른 값만 파싱한다.
    ranks: dict[str, tuple[int, float]] = {}

    def _rank(ts: str) -> tuple[int, float]:
        rank = ranks.get(ts)
        if rank is None:
            rank = ranks[ts] = _ts_rank(ts)
        return rank

    # 고객번호(phone) 단위로 머지. caller(우리 발신번호/chatbotId)는 발송·회신
    # 경로마다 다를 수 있어(RCS 양방향 회신은 mo_callback=chatbotId) 그룹핑 키에서
    # 제외한다. 대표 caller 는 "가장 최근 활동한 caller" 로 유지 — 답장 발송·읽음
    # 처리가 이 값을 쓴다. 같은 고객을 여러 발신번호로 상대해도 대화방은 1개.
    threads: dict[str, dict] = {}
    no_ts = _rank("")

    def _touch(phone: str) -> dict:
        return threads.setdefault(
            phone,
            {
                "caller": "",
                "phone": phone,
                "mt_last_t": "",
                "mt_rank": no_ts,
                "mt_count": 0,
                "mo_last_t": "",
                "mo_rank": no_ts,
                "mo_count": 0,
                "caller_rank": no_ts,  # 대표 caller 선정용 최신 활동 시각
            },
        )

    # 한 phone 이 발신번호·시각 모양마다 여러 행으로 온다 — 실제 시각이 가장 늦은 값을 남기고
    # 건수는 더한다. 대표 caller 도 같은 기준이고, 같은 시각이면 나중에 본 행(MO 가 MT 뒤).
    for side, rows in (("mt", mt_rows), ("mo", mo_rows)):
        last_key, rank_key, count_key = f"{side}_last_t", f"{side}_rank", f"{side}_count"
        for r in rows:
            if not r.caller or not r.phone:
                continue
            t = _touch(r.phone)
            ts = r.last_t or ""
            rank = _rank(ts)
            if rank >= t[rank_key]:
                t[last_key], t[rank_key] = ts, rank
            t[count_key] += r.cnt
            if rank >= t["caller_rank"]:
                t["caller"], t["caller_rank"] = r.caller, rank

    # 마지막 활동 시각·방향은 집계값만으로 정해진다 — 본문을 읽기 전에 정렬해 자른다.
    # 발송과 회신이 같은 시각이면 발송(OUT)으로 둔다.
    for t in threads.values():
        if t["mo_rank"] > t["mt_rank"]:
            t["last_t"], t["last_rank"], t["last_dir"] = t["mo_last_t"], t["mo_rank"], "IN"
        else:
            t["last_t"], t["last_rank"], t["last_dir"] = t["mt_last_t"], t["mt_rank"], "OUT"

    # 안정 정렬이라 시각이 같은 대화방은 집계 순서를 유지한다.
    ordered = sorted(threads.values(), key=lambda t: t["last_rank"], reverse=True)
    page = ordered[offset : offset + limit]

    in_bodies = _batch_last_mo_bodies(db, [t["phone"] for t in page if t["last_dir"] == "IN"])
    out_bodies = _batch_last_mt_bodies(db, [t["phone"] for t in page if t["last_dir"] == "OUT"])
    read_at_map = _batch_read_at(db, [t["phone"] for t in page])

    built = [
        ChatThread(
            caller=t["caller"],  # 대표(최근) caller
            phone=t["phone"],
            last_timestamp=t["last_t"],
            last_body=(in_bodies if t["last_dir"] == "IN" else out_bodies).get(t["phone"], ""),
            last_direction=t["last_dir"],
            # 안읽음 = 고객(MO) 최종 메시지가 팀 마지막 읽음 시각 이후.
            unread=thread_unread(t["mo_last_t"], read_at_map.get(t["phone"], "")),
            mo_count=t["mo_count"],
            mt_count=t["mt_count"],
        )
        for t in page
    ]
    return built, len(ordered)


def get_thread(db: Session, caller: str, phone: str) -> list[ChatMessage]:
    """특정 고객(phone) 스레드의 모든 메시지를 시간 오름차순으로 반환한다.

    대화방은 고객번호(phone) 단위로 묶는다. caller(우리 발신번호/chatbotId)는
    발송·회신 경로마다 다를 수 있어(특히 RCS 양방향은 mo_callback=chatbotId)
    그룹핑 키에서 제외한다 — caller 인자는 하위호환용으로 받되 조회엔 쓰지 않는다.
    같은 고객과 여러 발신번호로 주고받은 이력도 한 방에 모인다.
    """
    out: list[ChatMessage] = []

    # MT — 그 고객(phone)에게 보낸 모든 발송 (발신번호 무관).
    mt_rows = db.execute(
        select(Message, Campaign)
        .join(Campaign, Campaign.id == Message.campaign_id)
        .where(Message.to_number == phone)
    ).all()
    for msg, campaign in mt_rows:
        ts = _coalesce_ts(msg.complete_time, msg.report_dt, campaign.created_at)
        out.append(
            ChatMessage(
                direction="OUT",
                body=campaign.content or "",
                timestamp=ts,
                status=msg.status,
                delivery=delivery_status(msg.status, msg.result_code, msg.cli_key),
                channel=outbound_channel(
                    msg.channel,
                    campaign.rcs_messagebase_id,
                    campaign.message_type,
                    msg.cli_key,
                    msg.status,
                ),
                cost=msg.cost,
                campaign_id=campaign.id,
                msg_id=msg.id,
            )
        )

    # MO — 그 고객(phone)에게서 온 모든 회신 (mo_callback=발신번호/chatbotId 무관).
    mo_rows = db.execute(
        select(MoMessage).where(MoMessage.mo_number == phone)
    ).scalars().all()
    for mo in mo_rows:
        ts = _coalesce_ts(mo.mo_recv_dt, mo.received_at)
        out.append(
            ChatMessage(
                direction="IN",
                body=mo.mo_msg or "",
                timestamp=ts,
                telco=mo.telco,
                product_code=mo.product_code,
                mo_id=mo.id,
            )
        )

    # ISO 와 msghub 원본 포맷 섞여 있어 lexicographic 비교는 틀어진다.
    # _parse_ts_for_sort 로 epoch float 변환 후 정렬.
    out.sort(key=lambda m: _parse_ts_for_sort(m.timestamp))
    return out


def chat_session_summary(messages: list[ChatMessage]) -> dict:
    """대화방의 최근 24h 세션 과금 요약.

    RCS 양방향(CHAT)은 (챗봇, 고객) 쌍의 24시간 세션당 최대 80원(10건) 상한.
    Message.cost는 건당 8원으로 저장되지만 실 청구는 세션 단위로 capped된다.

    Returns:
        {
          "recent_out_count": 최근 24h 내 OUT 건수,
          "session_billed": 세션 상한 적용한 실 청구액(원),
          "session_raw": 상한 미적용 시 원래 합계(원),
          "capped": True면 상한에 도달해 축소됨,
          "cap_krw": 80,
          "max_units": 10,
        }
    """
    now = datetime.now(UTC)
    window_start = now - timedelta(hours=CHAT_SESSION_WINDOW_HOURS)

    out_count = 0
    raw_total = 0
    for m in messages:
        if m.direction != "OUT":
            continue
        try:
            ts = datetime.fromisoformat(m.timestamp)
        except (ValueError, TypeError):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ts >= window_start:
            out_count += 1
            raw_total += m.cost or 0

    billed = chat_session_cost(out_count)
    return {
        "recent_out_count": out_count,
        "session_billed": billed,
        "session_raw": raw_total,
        "capped": out_count >= CHAT_SESSION_MAX_UNITS,
        "cap_krw": CHAT_SESSION_CAP_KRW,
        "max_units": CHAT_SESSION_MAX_UNITS,
        "window_hours": CHAT_SESSION_WINDOW_HOURS,
    }


def validate_reply_content(content: str) -> dict:
    """답장 본문 검증 — 정책: 엄격(90byte 양방향 CHAT만).

    양방향 CHAT은 90byte 제한이므로 이를 넘기면 LMS(단방향)로 강등되어
    고객이 더 이상 답장할 수 없다. 대화 연속성을 위해 엄격 모드로 차단.

    완화하려면 아래 `SMS` 체크를 제거하여 validate_message 결과를 그대로 사용.
    """
    result = validate_message(content)
    if not result["ok"]:
        return result
    if result["message_type"] != "SMS":
        return {
            "ok": False,
            "error": (
                f"답장은 90바이트 이내 단문만 가능합니다 "
                f"(현재 {result['byte_len']}바이트 · 양방향 CHAT 제약)."
            ),
            "byte_len": result["byte_len"],
            "message_type": result["message_type"],
        }
    return result


def _fresh_reply_id(db: Session, caller: str, phone: str) -> str | None:
    """(caller, phone) 의 양방향 reply_id — 아직 유효한 최신 MO 것만. 없으면 None.

    양방향(8원) 응답은 고객 MO 의 replyId 가 필요하다(webhook 이 저장). replyId 는 받은 뒤
    24시간 유효하다(REPLY_ID_VALID_HOURS). 만료된 replyId 는 msghub 가 거부하거나 접수 후
    리포트에서 실패해, 답장이 리포트를 기다렸다가 대체 발송으로 늦게 나간다 — 예전엔 나이
    제한 없이 최신 replyId 를 써서 며칠 뒤 답장이 이 경로를 탔다. 경계 직전에 보낸 요청이
    이통사에 닿기 전에 만료되지 않게 여유(REPLY_ID_SAFETY_MARGIN_MINUTES)를 빼고 판정하고,
    그보다 오래됐으면 None 을 돌려 호출자가 바로 단방향 RCS 로 보내게 한다.

    유효시간은 msghub 가 MO 를 받은 시각(mo_recv_dt)부터 센다 — 우리 서버 수신 시각
    (received_at)은 웹훅 재전송으로 늦을 수 있어 mo_recv_dt 가 없을 때만 쓴다. 두 포맷
    (msghub KST·ISO)이 섞일 수 있어 문자열 정렬 대신 parse_mixed_ts 로 시각을 비교한다.
    """
    rows = db.execute(
        select(MoMessage.reply_id, MoMessage.mo_recv_dt, MoMessage.received_at).where(
            MoMessage.mo_callback == caller,
            MoMessage.mo_number == phone,
            MoMessage.reply_id.is_not(None),
        )
    ).all()
    latest: tuple[datetime, str] | None = None
    for r in rows:
        ts = parse_mixed_ts(r.mo_recv_dt) or parse_mixed_ts(r.received_at)
        if ts is not None and (latest is None or ts > latest[0]):
            latest = (ts, r.reply_id)
    if latest is None:
        return None
    usable_for = timedelta(hours=REPLY_ID_VALID_HOURS) - timedelta(
        minutes=REPLY_ID_SAFETY_MARGIN_MINUTES
    )
    if datetime.now(UTC) - latest[0] > usable_for:
        return None
    return latest[1]


def default_send_channel(db: Session, phone: str) -> str | None:
    """답장 전송 방식 기본값 — 이 번호로 가장 최근에 전달 성공한 발송의 전송 방식.

    기준은 실제 도달 채널(Message.channel)이 아니라 요청한 전송 방식이다
    (Campaign.rcs_messagebase_id 가 있으면 RCS, 없으면 일반). RCS 로 보냈으나 단말
    사정으로 SMS 로 대체 도달한 건도 "rcs" 로 본다 — 도달 채널을 따르면 일시적 대체
    한 번에 기본값이 일반으로 굳어 RCS 가 다시 끊긴다. 대체 도달은 SMS 단가(9원)라
    RCS 를 유지해도 손해가 없다.

    성공 = 리포트 수신(DONE) + 성공 코드. 접수 대기·실패 건은 건너뛴다. "최근" 은
    Message.id(발송 순) 기준 — 혼합 포맷 시각의 문자열 정렬을 피한다. 전달 성공
    이력이 없으면 None — 프론트가 새 발송 화면과 같은 기본값(RCS)을 쓴다.
    """
    row = db.execute(
        select(Campaign.rcs_messagebase_id)
        .join(Message, Message.campaign_id == Campaign.id)
        .where(
            Message.to_number == phone,
            Message.status == "DONE",
            Message.result_code == SUCCESS_CODE,
        )
        .order_by(Message.id.desc())
        .limit(1)
    ).first()
    if row is None:
        return None
    return "rcs" if row.rcs_messagebase_id else "sms"


async def send_reply(
    db: Session,
    msghub_client: MsghubClient,
    user: User,
    caller: str,
    phone: str,
    content: str,
    send_channel: str = "rcs",
) -> Campaign:
    """답장을 대화방에서 고른 전송 방식(send_channel)으로 발송한다.

    - "rcs": 24h 세션 안의 고객 MO reply_id 가 있으면 RCS 양방향(CHAT, 8원)으로
      응답하고, 없거나 양방향 요청이 즉시 실패하면 단방향 RCS(dispatch_campaign,
      17원)로 fallback 한다. 양방향이 접수된 뒤 리포트에서 실패하면 webhook 이 일반
      SMS 로 대체 발송한다(routes.webhook._send_sms_fallback) — 어느 경우든 답장은 전달된다.
    - "sms"(일반): RCS 를 쓰지 않고 직접 SMS(9원)로 보낸다.
    """
    if send_channel not in SEND_CHANNELS:
        raise ValueError(f"전송 방식은 'rcs' 또는 'sms' 여야 합니다: {send_channel}")

    # H2: 답장 길이 검증 — 90바이트 초과 시 단방향 LMS 로 강등되어 양방향 세션이
    # 끊기므로 차단한다. ValueError 는 라우트에서 422 로 변환됨.
    check = validate_reply_content(content)
    if not check["ok"]:
        raise ValueError(check["error"])

    reply_id = _fresh_reply_id(db, caller, phone) if send_channel == "rcs" else None
    if reply_id:
        try:
            return await dispatch_chat_reply(
                db=db,
                msghub_client=msghub_client,
                created_by=user.sub,
                caller_number=caller,
                content=content,
                phone=phone,
                reply_id=reply_id,
            )
        except Exception:
            log.warning(
                "양방향(8원) 응답 실패 → 단방향 fallback: caller=%s",
                caller,
                exc_info=True,
            )
            # fall through to 단방향

    # rcs: reply_id 없음(세션 밖) 또는 양방향 실패 → 단방향 RCS(17원).
    # sms: 일반 직접 발송(9원).
    return await dispatch_campaign(
        db=db,
        msghub_client=msghub_client,
        created_by=user.sub,
        caller_number=caller,
        content=content,
        recipients=[phone],
        message_type="SMS",
        subject=None,
        send_channel=send_channel,
    )
