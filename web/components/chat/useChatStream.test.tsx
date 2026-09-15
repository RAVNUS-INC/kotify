import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, renderHook } from '@testing-library/react';

import { ChatLiveRefresh } from './ChatLiveRefresh';
import { useChatStream, type ChatStreamOptions } from './useChatStream';

const mocks = vi.hoisted(() => ({ refresh: vi.fn() }));

vi.mock('next/navigation', () => {
  // 실제 Next 라우터처럼 렌더마다 같은 객체 — 바뀌면 연결 effect 가 다시 돌아 재연결된다.
  const router = { refresh: mocks.refresh };
  return { useRouter: () => router };
});

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  readonly url: string;
  closed = false;
  private readonly listeners = new Map<string, Array<() => void>>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: () => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  close() {
    this.closed = true;
  }

  emit(type: string) {
    act(() => {
      for (const listener of this.listeners.get(type) ?? []) listener();
    });
  }
}

/** 가장 최근에 연 SSE 연결. */
function stream(): FakeEventSource {
  const es = FakeEventSource.instances[FakeEventSource.instances.length - 1];
  if (!es) throw new Error('EventSource 가 열리지 않았습니다');
  return es;
}

function renderStream(initialProps: ChatStreamOptions = {}) {
  return renderHook((props: ChatStreamOptions) => useChatStream(props), { initialProps });
}

/** 대기로 남는 메시지(예약 취소 캠페인 등)가 열린 채 대량 발송 리포트가 오간 뒤 — 간격 60초. */
function reachMaxBackoff() {
  for (let i = 0; i < 40; i++) {
    stream().emit('thread.updated'); // 서버가 5초 창마다 보내는 이벤트
    vi.advanceTimersByTime(5_000);
  }
  vi.advanceTimersByTime(60_000); // 잡혀 있던 새로고침까지 흘려보낸다
  mocks.refresh.mockClear();
}

const T1 = '0212345678:01011112222';
const T2 = '0212345678:01033334444';
const STUCK = { threadId: T1, pendingDeliveryIds: ['m-out-1'] };

beforeEach(() => {
  vi.useFakeTimers();
  FakeEventSource.instances = [];
  vi.stubGlobal('EventSource', FakeEventSource);
  mocks.refresh.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('useChatStream 고객 회신(message.new)', () => {
  it('대기 메시지가 없어도 바로 새로고침한다', () => {
    renderStream();

    stream().emit('message.new');

    expect(mocks.refresh).toHaveBeenCalledTimes(1);
  });
});

describe('useChatStream 전달 상태(thread.updated)', () => {
  it('목록만 보거나 모두 확정된 대화방은 새로고침하지 않는다', () => {
    renderStream({ threadId: T1 });

    stream().emit('thread.updated');

    expect(mocks.refresh).not.toHaveBeenCalled();
  });

  it('열린 대화방에 대기 메시지가 있으면 바로 새로고침하고, 확정되면 더는 하지 않는다', () => {
    const { rerender } = renderStream(STUCK);

    stream().emit('thread.updated');
    expect(mocks.refresh).toHaveBeenCalledTimes(1);

    rerender({ threadId: T1, pendingDeliveryIds: [] }); // 리포트 반영 — 전달/실패로 확정
    vi.advanceTimersByTime(60_000);
    stream().emit('thread.updated');
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
  });

  it('답장 직후 새로고침이 끝나기 전에 온 이벤트도 대기 답장이 렌더되면 한 번 따라잡는다', () => {
    // 이벤트는 답장이 아직 없는(대기 없음) 화면에서 도착하고, 이어서 같은 대화에 대기 답장이 렌더된다.
    const { rerender } = renderStream({ threadId: T1, pendingDeliveryIds: [] });
    stream().emit('thread.updated');
    expect(mocks.refresh).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1_000);
    rerender({ threadId: T1, pendingDeliveryIds: ['m-out-2'] });
    expect(mocks.refresh).toHaveBeenCalledTimes(1);

    rerender({ threadId: T1, pendingDeliveryIds: ['m-out-2', 'm-out-3'] }); // 흘려보낸 이벤트 1건엔 1회만
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
  });

  it('오래전에 흘려보낸 이벤트로는 따라잡지 않는다', () => {
    const { rerender } = renderStream({ threadId: T1, pendingDeliveryIds: [] });
    stream().emit('thread.updated');

    vi.advanceTimersByTime(15_000);
    rerender({ threadId: T1, pendingDeliveryIds: ['m-out-2'] });

    expect(mocks.refresh).not.toHaveBeenCalled();
  });

  it('대량 발송 중 대기 메시지가 있는 다른 대화를 골라도 한 번 더 새로고침하지 않는다', () => {
    // 목록을 보는 동안 흘려보낸 이벤트는 대화 이동 요청보다 먼저라 새 화면에 이미 반영돼 있다.
    const { rerender } = renderStream();
    stream().emit('thread.updated');

    vi.advanceTimersByTime(1_000);
    rerender({ threadId: T2, pendingDeliveryIds: ['m-out-42'] });
    expect(mocks.refresh).not.toHaveBeenCalled();

    stream().emit('thread.updated'); // 발송이 이어지면 다음 이벤트는 대기 메시지가 보이니 반영
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
  });

  it('대화를 옮기면 이전 대화 때문에 늘어난 간격·미뤄 둔 새로고침을 버린다', () => {
    const { rerender } = renderStream(STUCK);
    reachMaxBackoff();
    stream().emit('thread.updated'); // 이전 대화 기준으로 60초 뒤로 미뤄진다

    rerender({ threadId: T2, pendingDeliveryIds: [] });
    vi.advanceTimersByTime(120_000);
    expect(mocks.refresh).not.toHaveBeenCalled();

    rerender(STUCK); // 다시 돌아와도 백오프 없이 처음부터
    stream().emit('thread.updated');
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
  });

  it('대기 목록이 그대로면 리포트가 계속 와도 간격을 두 배씩 늘린다(최대 60초)', () => {
    const start = Date.now();
    const refreshedAt: number[] = [];
    mocks.refresh.mockImplementation(() => {
      refreshedAt.push((Date.now() - start) / 1_000);
    });
    renderStream(STUCK);

    for (let t = 0; t < 200; t += 5) {
      stream().emit('thread.updated'); // 서버가 5초 창마다 보내는 이벤트 40회
      vi.advanceTimersByTime(5_000);
    }

    expect(refreshedAt).toEqual([0, 5, 15, 35, 75, 135, 195]);
  });

  it('새 답장이 대기로 보이면 간격이 처음으로 돌아가 그 리포트는 바로 반영된다', () => {
    const { rerender } = renderStream(STUCK);
    reachMaxBackoff();

    rerender({ threadId: T1, pendingDeliveryIds: ['m-out-1', 'm-out-9'] });
    stream().emit('thread.updated');

    expect(mocks.refresh).toHaveBeenCalledTimes(1);
  });

  it('늘어난 간격으로 미뤄진 이벤트가 있을 때 새 답장이 렌더되면 기다리지 않는다', () => {
    const { rerender } = renderStream(STUCK);
    reachMaxBackoff();

    vi.advanceTimersByTime(10_000);
    stream().emit('thread.updated'); // 새 답장의 리포트 — 화면엔 아직 이전 대기 메시지뿐이라 미뤄진다
    expect(mocks.refresh).not.toHaveBeenCalled();

    rerender({ threadId: T1, pendingDeliveryIds: ['m-out-1', 'm-out-9'] });
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
  });

  it('시스템 시각이 뒤로 가도 간격이 그만큼 밀리지 않는다', () => {
    renderStream(STUCK);
    stream().emit('thread.updated');
    expect(mocks.refresh).toHaveBeenCalledTimes(1);

    vi.setSystemTime(Date.now() - 3_600_000); // 벽시계만 1시간 뒤로
    vi.advanceTimersByTime(5_000);
    stream().emit('thread.updated');

    expect(mocks.refresh).toHaveBeenCalledTimes(2);
  });
});

describe('useChatStream 연결', () => {
  it('연결이 열릴 때 대기 메시지가 있으면 구독 전에 온 리포트를 반영하려 새로고침한다', () => {
    renderStream(STUCK);

    stream().emit('open');

    expect(mocks.refresh).toHaveBeenCalledTimes(1);
  });

  it('대기 메시지가 없으면 연결이 열려도 새로고침하지 않는다', () => {
    renderStream();

    stream().emit('open');

    expect(mocks.refresh).not.toHaveBeenCalled();
  });

  it('끊기면 backoff 뒤 다시 연결하고, 다시 열리면 끊긴 동안의 리포트를 반영한다', () => {
    renderStream(STUCK);
    const first = stream();

    first.emit('error');
    expect(first.closed).toBe(true);
    vi.advanceTimersByTime(999);
    expect(FakeEventSource.instances).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(FakeEventSource.instances).toHaveLength(2);

    stream().emit('open');
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
  });

  it('언마운트하면 연결을 닫고 미뤄 둔 새로고침도 취소한다', () => {
    const { unmount } = renderStream(STUCK);
    stream().emit('thread.updated'); // 바로 새로고침
    stream().emit('thread.updated'); // 최소 간격 뒤로 미뤄진다

    unmount();
    vi.advanceTimersByTime(60_000);

    expect(stream().closed).toBe(true);
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
  });
});

describe('ChatLiveRefresh', () => {
  it('대화를 바꿔도 연결 하나를 유지하고, 열린 대화에 대기 메시지가 있을 때만 전달 상태를 반영한다', () => {
    const { rerender } = render(<ChatLiveRefresh />);
    stream().emit('thread.updated');
    expect(mocks.refresh).not.toHaveBeenCalled();

    rerender(<ChatLiveRefresh threadId={T1} pendingDeliveryIds={['m-out-1']} />); // 대기 답장이 있는 대화 선택
    expect(mocks.refresh).not.toHaveBeenCalled();
    stream().emit('thread.updated');

    expect(mocks.refresh).toHaveBeenCalledTimes(1);
    expect(FakeEventSource.instances).toHaveLength(1);
  });
});
