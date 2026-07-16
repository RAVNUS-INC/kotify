"""인메모리 이벤트 버스 — 대화방 실시간 갱신(SSE)용 pub/sub.

용도: 고객 회신(MO) 수신 시 브라우저로 즉시 이벤트를 밀어 화면을 갱신한다.
프론트(useChatStream)가 `message.new` / `thread.updated` 이벤트를 받으면
router.refresh() 로 서버 컴포넌트를 재실행한다.

전제: uvicorn `--workers 1` 단일 프로세스 (deploy/kotify.service). 프로세스가
여러 개가 되면 한 워커가 발행한 이벤트를 다른 워커의 SSE 연결이 못 받으므로,
그때는 Redis pub/sub 등 외부 브로커로 교체해야 한다.

설계:
- 구독자마다 asyncio.Queue. publish 는 모든 큐에 넣기만 하고 즉시 반환(논블로킹).
- 큐가 가득 차면(느린/멈춘 클라이언트) 해당 이벤트는 버린다 — 메모리 무한 증가 방지.
  이벤트는 "갱신하라"는 신호일 뿐이라 유실돼도 다음 이벤트나 폴백으로 복구된다.
- publish 는 예외를 던지지 않는다(호출측 webhook 처리를 절대 방해하지 않음).
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)

# 구독자당 큐 최대 길이. 넘치면 이벤트를 버린다(신호일 뿐이라 유실 허용).
_QUEUE_MAX = 32

# 활성 구독자 큐 집합. 단일 프로세스 전제라 모듈 전역으로 충분.
_subscribers: set[asyncio.Queue[str]] = set()


def subscribe() -> asyncio.Queue[str]:
    """새 구독 큐를 만들어 등록하고 반환한다. 반드시 unsubscribe 로 해제할 것."""
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=_QUEUE_MAX)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue[str]) -> None:
    """구독 해제 — 연결 종료 시 반드시 호출(누수 방지)."""
    _subscribers.discard(q)


def subscriber_count() -> int:
    """현재 활성 SSE 구독자 수 (진단/테스트용)."""
    return len(_subscribers)


def publish(event: str) -> int:
    """모든 구독자에게 이벤트 이름을 발행한다.

    큐가 가득 찬 구독자는 건너뛴다. 예외를 던지지 않는다 — 호출측(webhook 등)의
    본 처리를 절대 방해하지 않기 위함.

    Args:
        event: SSE 이벤트 이름 (예: "message.new").

    Returns:
        실제로 전달된 구독자 수.
    """
    delivered = 0
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
            delivered += 1
        except asyncio.QueueFull:
            # 느린 클라이언트 — 이 이벤트는 버린다. 다음 이벤트에 다시 기회.
            log.debug("SSE 구독자 큐 가득참 — 이벤트 드롭: %s", event)
        except Exception:  # noqa: BLE001 — 발행은 절대 실패로 번지지 않게
            log.debug("SSE 이벤트 발행 실패(무시)", exc_info=True)
    return delivered


__all__ = ["subscribe", "unsubscribe", "publish", "subscriber_count"]
