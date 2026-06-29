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

import httpx
from sqlalchemy.orm import Session

from app.security.settings_store import SettingsStore

log = logging.getLogger(__name__)

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


def _mo_to_payload(mo) -> dict:
    """MoMessage ORM → n8n 으로 보낼 평탄한 JSON.

    Args:
        mo: 방금 저장한 app.models.MoMessage 인스턴스.
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

    return url, [_mo_to_payload(mo) for mo in mos]


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
]
