"""아웃바운드 알림 — 고객 회신(MO) 수신 시 외부(n8n 등) 웹훅으로 전달.

설계 의도:
- n8n Webhook 노드 URL 로 회신 1건당 JSON 1개를 POST 한다. n8n 쪽에서 이를
  트리거로 받아 하이웍스 등으로 포워딩한다.
- MO와 알림 요청을 같은 DB 트랜잭션에 저장한 뒤 HTTP 전송은 분리한다. n8n이
  느리거나 실패해도 msghub 응답을 막지 않고, 실패 행은 outbox에서 재시도한다.
- 페이로드는 평탄한 형태로 — n8n 에서 `{{ $json.from }}` 처럼 바로 꺼내 쓰기 쉽게.

설정 키 (Setting 테이블, 모두 공개=비암호화):
- ``notify.n8n_enabled`` : "true" 일 때만 전송
- ``notify.n8n_url``     : n8n Webhook 노드 URL (예: https://n8n.example.com/webhook/abc)
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Campaign, Message, MsghubRequest, NotificationDelivery, User
from app.msghub.codes import SUCCESS_CODE
from app.security.settings_store import SettingsStore
from app.util.time import parse_mixed_ts

log = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")

# n8n 전송 타임아웃 (초) — 웹훅 핸들러를 오래 잡지 않도록 짧게.
_TIMEOUT = 5.0
_INLINE_RETRIES = 3
_OUTBOX_BATCH = 100
_OUTBOX_LOCK_TIMEOUT = timedelta(minutes=5)
_ACCEPTED_STATUSES = frozenset({"REG", "ING"})
_RESERVATION_NOT_SENT_STATES = frozenset({"RESERVED", "RESERVE_FAILED", "RESERVE_CANCELED"})


def _format_phone_display(digits: str) -> str:
    """저장값(숫자만)을 표시용 하이픈 형태로. 프론트 formatPhone 과 동일 규칙(휴대폰/서울).

    n8n→하이웍스 알림 문구에서 바로 보기 좋게 쓰도록 표시형도 같이 보낸다.
    규칙에 안 맞으면 원본(숫자) 반환.
    """
    d = "".join(c for c in (digits or "") if c.isdigit())
    if not d:
        return digits or ""
    if d.startswith(("010", "011", "016", "017", "018", "019")):
        if len(d) == 11:
            return f"{d[:3]}-{d[3:7]}-{d[7:]}"
        if len(d) == 10:
            return f"{d[:3]}-{d[3:6]}-{d[6:]}"
    if d.startswith("02"):
        if len(d) == 10:
            return f"{d[:2]}-{d[2:6]}-{d[6:]}"
        if len(d) == 9:
            return f"{d[:2]}-{d[2:5]}-{d[5:]}"
    return d


def lookup_last_sender(db: Session, phone: str) -> dict | None:
    """이 고객 번호로 실제 발송이 확인된 마지막 담당자를 조회한다.

    ``DONE/10000``은 전달 성공, ``REG``·``ING``은 msghub가 즉시 요청을
    접수했지만 아직 리포트가 오지 않은 상태다. 예약 대기/취소/실패/PENDING은
    고객에게 실제로 전달됐다는 근거가 없어 후보에서 제외한다. 정렬은 캠페인
    생성 시각이 아니라 리포트 완료 시각 또는 msghub 요청 시각을 사용한다.

    Args:
        db: 활성 DB 세션.
        phone: 고객 번호(숫자만, MO.mo_number 와 동일 정규화 가정).

    Returns:
        {"id", "email", "name", "sentAt", "messageId"} 또는 매칭 없으면 None.
        id 는 하이웍스/AD 식별용으로 email 을 사용(User 에 sAMAccountName 없음).
    """
    if not phone:
        return None

    rows = db.execute(
        select(
            Message.id,
            Message.status,
            Message.result_code,
            Message.complete_time,
            MsghubRequest.sent_at,
            Campaign.created_by,
            Campaign.created_at,
            Campaign.state,
            Campaign.reserve_time,
        )
        .join(Campaign, Message.campaign_id == Campaign.id)
        .join(MsghubRequest, Message.msghub_request_id == MsghubRequest.id)
        .where(Message.to_number == phone)
    ).all()

    now = datetime.now(UTC)
    candidates: list[tuple[float, int, object, datetime]] = []
    for row in rows:
        status = row.status
        if status == "DONE":
            if row.result_code != SUCCESS_CODE:
                continue
            timestamp_raw = row.complete_time or row.sent_at or row.created_at
        elif status == "DELIVERED":
            # NCP 시절 레거시 성공 상태. 이력의 마지막 담당자 연결은 유지한다.
            timestamp_raw = row.complete_time or row.sent_at or row.created_at
        elif status in _ACCEPTED_STATUSES:
            # 예약 요청은 reserve_time 시각이 지나기 전까지 실제 발송 후보가 아니다.
            if row.state in _RESERVATION_NOT_SENT_STATES:
                if row.state != "RESERVED":
                    continue
                reserve_dt = parse_mixed_ts(row.reserve_time)
                if reserve_dt is None or reserve_dt.astimezone(UTC) > now:
                    continue
                timestamp_raw = row.reserve_time
            else:
                timestamp_raw = row.sent_at or row.complete_time or row.created_at
            if row.result_code not in (None, SUCCESS_CODE):
                continue
        else:
            continue

        timestamp = parse_mixed_ts(timestamp_raw) or parse_mixed_ts(row.created_at)
        if timestamp is None:
            continue
        candidates.append((timestamp.astimezone(UTC).timestamp(), row.id, row, timestamp))

    # 같은 시각이면 더 큰 메시지 ID가 나중에 기록된 발송이다.
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for _, msg_id, row, timestamp in candidates:
        user = db.get(User, row.created_by)
        if user is None:
            # 삭제된 계정 하나 때문에 더 오래된 유효 담당자까지 차단하지 않는다.
            continue
        return {
            "id": user.email,
            "email": user.email,
            "name": user.display_name or user.name or "",
            "sentAt": timestamp.astimezone(KST).isoformat(),
            "messageId": f"MT-{msg_id}",
        }
    return None


def _mo_to_payload(mo, last_sender: dict | None = None) -> dict:
    """MoMessage ORM → n8n 으로 보낼 평탄한 JSON.

    Args:
        mo: 방금 저장한 app.models.MoMessage 인스턴스.
        last_sender: lookup_last_sender 결과 (없으면 None).
    """
    return {
        "event": "message.received",
        # 고객(회신 발신) 번호 — 저장값은 숫자만, 표시형도 함께.
        "from": mo.mo_number,
        "fromDisplay": _format_phone_display(mo.mo_number),
        # 우리 발신번호(고객이 답장한 대상). 없을 수 있음.
        "to": mo.mo_callback or "",
        "text": mo.mo_msg or "",
        "title": mo.mo_title or "",
        "channel": mo.mo_type or "",
        "telco": mo.telco or "",
        # msghub 가 준 수신 시각 원본(있으면) + 우리 저장 시각(UTC ISO).
        "moReceivedDt": mo.mo_recv_dt or "",
        "receivedAt": mo.received_at or "",
        # 이 고객에게 마지막으로 문자 보낸 담당자(회신 알림 라우팅용). 없으면 null.
        "lastSender": last_sender,
    }


def prepare_n8n_delivery(db: Session, mos: list) -> tuple[str | None, list[dict]]:
    """전송 대상 URL 과 페이로드를 준비한다 (DB 읽기 — 요청 컨텍스트에서 호출).

    설정과 담당자 정보를 읽어 직렬화 가능한 페이로드로 확정한다. 호출자는 이를
    MO와 같은 트랜잭션의 outbox에 저장하고 HTTP 전송은 응답 뒤에 수행한다.

    Args:
        db: 활성 DB 세션 (설정 읽기용).
        mos: 방금 저장한 MoMessage 인스턴스 리스트.

    Returns:
        (url, payloads). 비활성/URL 미설정/빈 목록이면 (None, []).
    """
    if not mos:
        return None, []

    store = SettingsStore(db)
    enabled = (store.get("notify.n8n_enabled", "false") or "false").lower() == "true"
    url = (store.get("notify.n8n_url", "") or "").strip()
    if not (enabled and url):
        return None, []

    # 같은 배치에 동일 고객 번호가 여러 건이면 발송 이력 조회를 1회로 캐시.
    sender_cache: dict[str, dict | None] = {}
    payloads: list[dict] = []
    for mo in mos:
        phone = mo.mo_number or ""
        if phone not in sender_cache:
            sender_cache[phone] = lookup_last_sender(db, phone)
        payloads.append(_mo_to_payload(mo, sender_cache[phone]))

    return url, payloads


def enqueue_n8n_delivery(
    db: Session, mos: list, url: str, payloads: list[dict]
) -> list[int]:
    """MO와 같은 트랜잭션에 n8n 알림을 내구성 있게 기록한다."""
    now = datetime.now(UTC).isoformat()
    delivery_ids: list[int] = []
    for mo, payload in zip(mos, payloads, strict=True):
        existing = db.execute(
            select(NotificationDelivery.id).where(NotificationDelivery.mo_id == mo.id)
        ).scalar_one_or_none()
        if existing is not None:
            delivery_ids.append(existing)
            continue
        delivery = NotificationDelivery(
            mo_id=mo.id,
            url=url,
            payload=json.dumps(payload, ensure_ascii=False),
            status="PENDING",
            attempts=0,
            next_attempt_at=now,
            created_at=now,
        )
        db.add(delivery)
        db.flush()
        delivery_ids.append(delivery.id)
    return delivery_ids


async def _post_with_retry(
    client: httpx.AsyncClient, url: str, payload: dict
) -> tuple[bool, str | None]:
    """n8n에 2xx만 성공으로 처리하고 일시 오류는 짧게 재시도한다."""
    last_error = ""
    for attempt in range(_INLINE_RETRIES):
        try:
            resp = await client.post(url, json=payload)
            if 200 <= resp.status_code < 300:
                return True, None
            last_error = f"HTTP {resp.status_code}"
            # 4xx(429/408 제외)와 3xx는 즉시 실패로 남긴다.
            if 300 <= resp.status_code < 500 and resp.status_code not in (408, 429):
                break
        except httpx.HTTPError as exc:
            last_error = str(exc) or exc.__class__.__name__
        if attempt + 1 < _INLINE_RETRIES:
            await asyncio.sleep(0)
    return False, last_error or "unknown n8n delivery error"


async def deliver_n8n(url: str, payloads: list[dict]) -> int:
    """준비된 페이로드를 n8n 으로 POST 한다 (순수 HTTP — DB 의존 없음).

    각 전송 실패는 개별적으로 로그만 남기고 계속 진행한다(부분 실패 허용).
    호출자(BackgroundTask)에게 예외를 던지지 않는다.

    Returns:
        성공적으로 전송한 건수.
    """
    if not (url and payloads):
        return 0

    sent = 0
    # 단일 클라이언트로 여러 건 전송 (연결 재사용).
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
        for payload in payloads:
            ok, error = await _post_with_retry(client, url, payload)
            if ok:
                sent += 1
            else:
                log.warning("n8n 알림 전송 실패: %s", error)

    if sent:
        log.info("n8n 알림 전송 완료: %d건", sent)
    return sent


async def process_n8n_outbox(
    db: Session | None = None, *, batch_size: int = _OUTBOX_BATCH
) -> int:
    """대기 중인 알림을 전송하고 실패 건의 다음 시각을 예약한다.

    ``db``를 생략하면 새 세션을 열어 앱 재시작 후에도 큐를 처리한다. 요청
    직후 BackgroundTask에서는 현재 세션을 넘길 수 있고, lifespan 주기 작업은
    별도 세션을 사용한다.
    """
    session = db or SessionLocal()
    owns_session = db is None
    now_dt = datetime.now(UTC)
    now = now_dt.isoformat()
    stale = (now_dt - _OUTBOX_LOCK_TIMEOUT).isoformat()
    delivered = 0
    try:
        # 프로세스가 죽어 SENDING에 남은 행은 다음 실행에서 다시 시도한다.
        session.execute(
            update(NotificationDelivery)
            .where(
                NotificationDelivery.status == "SENDING",
                NotificationDelivery.locked_at.is_not(None),
                NotificationDelivery.locked_at < stale,
            )
            .values(
                status="FAILED",
                locked_at=None,
                next_attempt_at=now,
                last_error="stale lock recovered",
            )
        )
        session.commit()

        rows = session.execute(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.status.in_(("PENDING", "FAILED")),
                NotificationDelivery.next_attempt_at <= now,
            )
            .order_by(NotificationDelivery.id)
            .limit(batch_size)
        ).scalars().all()
        if not rows:
            return 0

        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
            for delivery in rows:
                url, payload_text = delivery.url, delivery.payload
                attempts = delivery.attempts + 1
                claim_time = datetime.now(UTC).isoformat()
                # 여러 웹훅 BackgroundTask가 동시에 큐를 훑어도 한 작업만 행을
                # 선점한다. 조건부 UPDATE가 실패하면 다른 작업이 처리 중이다.
                claimed = session.execute(
                    update(NotificationDelivery)
                    .where(
                        NotificationDelivery.id == delivery.id,
                        NotificationDelivery.status.in_(("PENDING", "FAILED")),
                    )
                    .values(status="SENDING", attempts=attempts, locked_at=claim_time)
                ).rowcount
                session.commit()
                if not claimed:
                    continue
                session.refresh(delivery)
                try:
                    payload = json.loads(payload_text)
                    if not isinstance(payload, dict):
                        raise TypeError("payload must be a JSON object")
                    ok, error = await _post_with_retry(client, url, payload)
                except (ValueError, TypeError) as exc:
                    ok, error = False, f"invalid payload: {exc}"

                if ok:
                    delivery.status = "DELIVERED"
                    delivery.delivered_at = datetime.now(UTC).isoformat()
                    delivery.locked_at = None
                    delivery.last_error = None
                    delivered += 1
                else:
                    # 지수 backoff: 2s, 4s, ... 최대 1시간. 영구 큐라서 횟수 제한은 두지 않는다.
                    delay = min(3600, 2 ** min(attempts, 12))
                    delivery.status = "FAILED"
                    delivery.next_attempt_at = (datetime.now(UTC) + timedelta(seconds=delay)).isoformat()
                    delivery.locked_at = None
                    delivery.last_error = error
                    log.warning(
                        "n8n 알림 outbox 실패: delivery_id=%s attempts=%s error=%s",
                        delivery.id, attempts, error,
                    )
                session.commit()
        if delivered:
            log.info("n8n 알림 outbox 전송 완료: %d건", delivered)
        return delivered
    except Exception:  # noqa: BLE001
        session.rollback()
        log.exception("n8n 알림 outbox 처리 오류 — 다음 주기에 재시도")
        return delivered
    finally:
        if owns_session:
            session.close()


async def notify_n8n_mo(db: Session, mos: list) -> int:
    """저장된 MO 목록을 n8n 으로 전달한다 (준비 + 전송 일괄).

    설정에서 비활성/URL 미설정이면 0 반환. 동기 컨텍스트(또는 DB 세션이 끝까지
    살아있는 경우)용 편의 래퍼.
    """
    url, payloads = prepare_n8n_delivery(db, mos)
    if not (url and payloads):
        return 0
    return await deliver_n8n(url, payloads)


async def send_n8n_test(url: str, recipient: dict) -> tuple[bool, str]:
    """설정 화면 '테스트 전송' 용 — 샘플 페이로드를 n8n 으로 1건 POST.

    Args:
        url: 테스트할 n8n Webhook URL.
        recipient: 실제 Telegram 수신자를 찾는 데 사용할 현재 로그인 사용자 정보.

    Returns:
        (성공여부, 메시지).
    """
    sample = {
        "event": "message.received",
        "from": "01012345678",
        "fromDisplay": "010-1234-5678",
        "to": "025771000",
        "text": "[테스트] kotify → n8n 연동 확인용 메시지입니다.",
        "title": "",
        "channel": "SMS",
        "telco": "",
        "moReceivedDt": "",
        "receivedAt": datetime.now(UTC).isoformat(),
        # test=true는 현재 n8n 워크플로에서 발송을 건너뛴다. 실제 알림과 같은
        # lastSender 라우팅을 사용해 테스트를 누른 사용자에게 전송한다.
        "lastSender": recipient,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
            ok, error = await _post_with_retry(client, url, sample)
        if not ok:
            return False, f"n8n 전송 실패: {error}"
        return True, "n8n 웹훅 접수 성공 (로그인 사용자 대상 Telegram 알림 요청됨)"
    except httpx.HTTPError as exc:
        return False, f"연결 실패: {exc}"


# 저장값은 webhook 단계에서 이미 숫자만으로 정규화돼 있다고 가정한다.
__all__ = [
    "prepare_n8n_delivery",
    "deliver_n8n",
    "notify_n8n_mo",
    "enqueue_n8n_delivery",
    "process_n8n_outbox",
    "send_n8n_test",
    "lookup_last_sender",
]
