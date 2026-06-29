"""아웃바운드 알림 — 고객 회신(MO) 수신 시 외부(n8n 등) 웹훅으로 전달.

설계 의도:
- n8n Webhook 노드 URL 로 회신 1건당 JSON 1개를 POST 한다. n8n 쪽에서 이를
  트리거로 받아 하이웍스 등으로 포워딩한다.
- **수신 처리(MO 저장)와 완전히 분리**한다: n8n 전송이 실패하거나 느려도
  msghub 웹훅 응답(success)에는 절대 영향을 주지 않는다. 실패는 로그만 남기고
  삼킨다(통신사 재시도 폭주 방지).
- 페이로드는 평탄한 형태로 — n8n 에서 `{{ $json.from }}` 처럼 바로 꺼내 쓰기 쉽게.

설정 키 (Setting 테이블, 모두 공개=비암호화):
- ``notify.n8n_enabled`` : "true" 일 때만 전송
- ``notify.n8n_url``     : n8n Webhook 노드 URL (예: https://n8n.example.com/webhook/abc)
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Campaign, Message, User
from app.security.settings_store import SettingsStore

log = logging.getLogger(__name__)

KST = ZoneInfo("Asia/Seoul")

# n8n 전송 타임아웃 (초) — 웹훅 핸들러를 오래 잡지 않도록 짧게.
_TIMEOUT = 5.0


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


def _to_kst_iso(iso_utc: str | None) -> str:
    """UTC ISO 문자열 → KST(+09:00) ISO. 파싱 실패 시 원본 그대로."""
    if not iso_utc:
        return ""
    try:
        dt = datetime.fromisoformat(iso_utc)
    except (ValueError, TypeError):
        return iso_utc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(KST).isoformat()


def lookup_last_sender(db: Session, phone: str) -> dict | None:
    """이 고객 번호로 마지막으로 발송한 담당자를 조회한다.

    경로: messages.to_number == phone 인 가장 최근 발송 → 그 campaign 의
    created_by(=users.sub) → User. 정렬은 campaign.created_at DESC.

    기간 제한 없음 — "그 고객과 마지막으로 접촉한 담당자"가 회신 담당이므로,
    오래된 발송이라도 그 사람이 적임이다. 퇴사 등으로 직원 레코드가 사라진
    경우는 아래 User 조회에서 None 이 되어 자연히 제외된다(→ 관리자 fallback).

    Args:
        db: 활성 DB 세션.
        phone: 고객 번호(숫자만, MO.mo_number 와 동일 정규화 가정).

    Returns:
        {"id", "email", "name", "sentAt", "messageId"} 또는 매칭 없으면 None.
        id 는 하이웍스/AD 식별용으로 email 을 사용(User 에 sAMAccountName 없음).
    """
    if not phone:
        return None

    # to_number 인덱스 + created_at DESC + LIMIT 1. created_at 은 ISO 문자열이라
    # lexicographic 정렬이 시간순과 일치(전부 UTC ISO).
    row = db.execute(
        select(Message.id, Campaign.created_by, Campaign.created_at)
        .join(Campaign, Message.campaign_id == Campaign.id)
        .where(Message.to_number == phone)
        .order_by(Campaign.created_at.desc())
        .limit(1)
    ).first()
    if row is None:
        return None

    msg_id, created_by, created_at = row
    user = db.get(User, created_by)
    if user is None:
        # 발송 직원이 삭제된 경우 등 — 식별자 없으면 알림 라우팅 불가하니 None.
        return None

    return {
        # 하이웍스/AD 식별자: User 에 sAMAccountName 컬럼이 없어 email 을 사용.
        "id": user.email,
        "email": user.email,
        "name": user.display_name or user.name or "",
        "sentAt": _to_kst_iso(created_at),
        "messageId": f"MT-{msg_id}",
    }


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

    실제 HTTP 전송은 deliver_n8n 으로 분리해, 응답 후 BackgroundTask 에서
    수행한다. 이렇게 나눈 이유: BackgroundTask 시점엔 요청 스코프 DB 세션이
    이미 닫혀 있을 수 있으므로, 세션이 살아있는 동안 설정·페이로드를 모두
    확정해 둔다.

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
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for payload in payloads:
            try:
                resp = await client.post(url, json=payload)
                if resp.status_code >= 400:
                    log.warning("n8n 알림 전송 실패 HTTP %s", resp.status_code)
                    continue
                sent += 1
            except httpx.HTTPError as exc:
                # 네트워크/타임아웃 — 로그만, MO 수신 처리에는 영향 없음.
                log.warning("n8n 알림 전송 예외: %s", exc)

    if sent:
        log.info("n8n 알림 전송 완료: %d건", sent)
    return sent


async def notify_n8n_mo(db: Session, mos: list) -> int:
    """저장된 MO 목록을 n8n 으로 전달한다 (준비 + 전송 일괄).

    설정에서 비활성/URL 미설정이면 0 반환. 동기 컨텍스트(또는 DB 세션이 끝까지
    살아있는 경우)용 편의 래퍼.
    """
    url, payloads = prepare_n8n_delivery(db, mos)
    if not (url and payloads):
        return 0
    return await deliver_n8n(url, payloads)


async def send_n8n_test(url: str) -> tuple[bool, str]:
    """설정 화면 '테스트 전송' 용 — 샘플 페이로드를 n8n 으로 1건 POST.

    Args:
        url: 테스트할 n8n Webhook URL.

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
        "receivedAt": "",
        "lastSender": None,
        "test": True,
    }
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(url, json=sample)
        if resp.status_code >= 400:
            return False, f"n8n 응답 HTTP {resp.status_code}"
        return True, f"전송 성공 (HTTP {resp.status_code})"
    except httpx.HTTPError as exc:
        return False, f"연결 실패: {exc}"


# 저장값은 webhook 단계에서 이미 숫자만으로 정규화돼 있다고 가정한다.
__all__ = [
    "prepare_n8n_delivery",
    "deliver_n8n",
    "notify_n8n_mo",
    "send_n8n_test",
    "lookup_last_sender",
]
