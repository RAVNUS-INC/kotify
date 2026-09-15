"""인메모리 이벤트 버스 — 대화방 실시간 갱신(SSE)용 pub/sub.

용도: 브라우저로 "화면을 갱신하라"는 신호를 밀어 새로고침 없이 대화방을 갱신한다.
프론트(useChatStream)가 이벤트를 받으면 router.refresh() 로 서버 컴포넌트를 재실행한다.
- `message.new`: 고객 회신(MO) 저장 — 즉시 발행(publish).
- `thread.updated`: 발신 전달 상태 변경(리포트 웹훅·재조정) — 창당 1회로 합쳐
  발행(publish_throttled). 프론트는 전달 대기 메시지가 보이는 대화방에서만 새로고침한다.

전제: uvicorn `--workers 1` 단일 프로세스 (deploy/kotify.service). 프로세스가
여러 개가 되면 한 워커가 발행한 이벤트를 다른 워커의 SSE 연결이 못 받으므로,
그때는 Redis pub/sub 등 외부 브로커로 교체해야 한다.

설계:
- 구독자마다 asyncio.Queue. publish 는 모든 큐에 넣기만 하고 즉시 반환(논블로킹).
- 큐가 가득 차면(느린/멈춘 클라이언트) 해당 이벤트는 버린다 — 메모리 무한 증가 방지.
  이벤트는 "갱신하라"는 신호일 뿐이라 유실돼도 다음 이벤트나 폴백으로 복구된다.
- publish 는 예외를 던지지 않는다(호출측 webhook 처리를 절대 방해하지 않음).
- publish_throttled: 새로고침 1회가 목록(list_threads)·상세 API 와 하이웍스 외부 MySQL
  조회를 다시 부르고 열린 탭 수만큼 곱해진다. 대량 발송 리포트는 몰려오므로 이벤트
  이름마다 창(window) 안에서 한 번만 보낸다 — 조용하던 뒤 첫 변경은 즉시(leading),
  창 안의 나머지는 창 끝에 한 번(trailing). 끝에 한 번 더 보내므로 몰려온 리포트의
  마지막 변경도 창 길이 안에 반영된다.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# 구독자당 큐 최대 길이. 넘치면 이벤트를 버린다(신호일 뿐이라 유실 허용).
_QUEUE_MAX = 32

# publish_throttled 기본 창(초). 같은 이벤트의 발행 간격은 이보다 좁아지지 않고,
# 어떤 변경이든 이 시간 안에 발행된다.
_THROTTLE_WINDOW_SECONDS = 5.0

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


@dataclass
class _Throttle:
    """이벤트 이름별 publish_throttled 상태 — 시각은 loop.time(), 그 루프에서만 유효."""

    loop: asyncio.AbstractEventLoop
    last_published: float | None = None
    trailing: asyncio.TimerHandle | None = None


_throttles: dict[str, _Throttle] = {}


def publish_throttled(event: str, window: float = _THROTTLE_WINDOW_SECONDS) -> None:
    """변경을 알리되 같은 이벤트는 window 초에 한 번만 발행한다.

    - 마지막 발행 후 window 가 지났으면 바로 발행한다(leading edge).
    - 아니면 창이 끝나는 시점에 한 번 발행하도록 예약한다(trailing edge). 이미 예약돼
      있으면 그 발행이 이번 변경도 싣는다.

    그래서 몰려온 변경이 몇 건이든 발행 간격은 window 이상이고, 마지막 변경도 window
    안에 발행된다. DB 커밋이 끝난 뒤 이벤트 루프 안(async 라우트·백그라운드 태스크)에서
    부른다. 루프 밖에서는 예약할 수 없어 바로 발행한다. publish 처럼 예외를 던지지 않는다.

    Args:
        event: SSE 이벤트 이름 (예: "thread.updated").
        window: 발행 최소 간격(초).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        publish(event)
        return

    state = _throttles.get(event)
    if state is None or state.loop is not loop:
        # 다른 루프에서 만든 상태는 그 루프의 타이머째 무효다(닫힌 루프의 예약은 영영 안 돈다).
        state = _throttles[event] = _Throttle(loop=loop)
    if state.trailing is not None:
        return  # 창 끝 발행이 예약돼 있다 — 이번 변경도 그때 반영된다

    now = loop.time()
    if state.last_published is None or now - state.last_published >= window:
        state.last_published = now
        publish(event)
        return
    state.trailing = loop.call_later(
        state.last_published + window - now, _publish_trailing, event, state
    )


def _publish_trailing(event: str, state: _Throttle) -> None:
    """창 끝 발행 — 창 안에서 합쳐진 변경들을 한 번에 알린다."""
    state.trailing = None
    state.last_published = state.loop.time()
    publish(event)


__all__ = [
    "subscribe",
    "unsubscribe",
    "publish",
    "publish_throttled",
    "subscriber_count",
]
