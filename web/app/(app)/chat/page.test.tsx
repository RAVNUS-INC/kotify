import { isValidElement, type ReactElement, type ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ChatLiveRefresh } from '@/components/chat';
import { fetchThread, fetchThreads } from '@/lib/chat';
import type { ChatThreadDetail } from '@/types/chat';
import ThreadDetailPage from './[id]/page';
import ChatPage from './page';

vi.mock('@/lib/chat', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/chat')>();
  return { ...actual, fetchThreads: vi.fn(), fetchThread: vi.fn() };
});

const TID = '0212345678:01011112222';

const detail: ChatThreadDetail = {
  id: TID,
  name: '01011112222',
  phone: '01011112222',
  preview: '',
  time: '10:00',
  channel: 'rcs',
  messages: [
    { id: 'm-in-1', side: 'them', kind: 'rcs', text: '배송 언제 오나요?', time: '09:58' },
    { id: 'm-out-2', side: 'us', kind: 'rcs', text: '내일 도착 예정입니다.', time: '10:00', status: 'pending' },
    { id: 'm-out-3', side: 'us', kind: 'sms', text: '안내드립니다', time: '09:00', status: 'sent' },
  ],
};

/** 서버 컴포넌트가 돌려준 트리에서 type 이 같은 첫 엘리먼트. */
function findElement(node: ReactNode, type: unknown): ReactElement | null {
  if (Array.isArray(node)) {
    for (const child of node) {
      const found = findElement(child, type);
      if (found) return found;
    }
    return null;
  }
  if (!isValidElement(node)) return null;
  if (node.type === type) return node;
  return findElement((node.props as { children?: ReactNode }).children, type);
}

beforeEach(() => {
  vi.mocked(fetchThreads).mockResolvedValue([]);
  vi.mocked(fetchThread).mockResolvedValue(detail);
});

describe('대화방 페이지 실시간 갱신 연결', () => {
  it('/chat 에서 대화를 고르면 그 대화와 전달 대기 메시지를 구독기에 넘긴다', async () => {
    const tree = await ChatPage({ searchParams: { selected: TID } });

    expect(findElement(tree, ChatLiveRefresh)?.props).toEqual({
      threadId: TID,
      pendingDeliveryIds: ['m-out-2'],
    });
  });

  it('/chat 에서 목록만 볼 땐 열린 대화도 대기 메시지도 없다', async () => {
    const tree = await ChatPage({ searchParams: {} });

    expect(findElement(tree, ChatLiveRefresh)?.props).toEqual({
      threadId: undefined,
      pendingDeliveryIds: [],
    });
  });

  it('/chat/[id] 도 같은 구독기를 붙인다', async () => {
    const tree = await ThreadDetailPage({ params: { id: encodeURIComponent(TID) } });

    expect(findElement(tree, ChatLiveRefresh)?.props).toEqual({
      threadId: TID,
      pendingDeliveryIds: ['m-out-2'],
    });
  });
});
