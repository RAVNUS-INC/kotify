import { isValidElement, type ReactElement, type ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ChatFilters, ChatLiveRefresh, ThreadList } from '@/components/chat';
import { PageHeader } from '@/components/shell';
import { fetchThread, fetchThreadPage } from '@/lib/chat';
import type { ChatThreadDetail } from '@/types/chat';
import ThreadDetailPage from './[id]/page';
import ChatPage from './page';

vi.mock('@/lib/chat', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/chat')>();
  return { ...actual, fetchThreadPage: vi.fn(), fetchThread: vi.fn() };
});

const TID = '0212345678:01011112222';

const detail: ChatThreadDetail = {
  id: TID,
  name: '01011112222',
  phone: '01011112222',
  preview: '',
  time: '10:00',
  channel: 'rcs',
  lastInboundMessageId: 1,
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
  vi.mocked(fetchThreadPage).mockReset().mockResolvedValue({
    data: [], meta: { total: 0, unreadTotal: 0, offset: 0, limit: 200, hasMore: false },
  });
  vi.mocked(fetchThread).mockResolvedValue(detail);
});

describe('대화방 페이지 실시간 갱신 연결', () => {
  it('실패 메시지만 있는 대화도 목록 선택과 상세 페이지 모두에서 갱신을 감시한다', async () => {
    vi.mocked(fetchThread).mockResolvedValue({
      ...detail,
      lastInboundMessageId: 1,
  messages: [{
        id: 'm-out-4', side: 'us', kind: 'rcs', text: '응답 타임아웃', time: '10:00', status: 'failed',
      }],
    });
    const pages = [
      await ChatPage({ searchParams: { selected: TID } }),
      await ThreadDetailPage({ params: { id: encodeURIComponent(TID) } }),
    ];

    for (const tree of pages) {
      expect(findElement(tree, ChatLiveRefresh)?.props).toEqual({
        threadId: TID, deliveryRefreshIds: ['m-out-4'],
      });
    }
  });

  it('/chat 에서 대화를 고르면 그 대화와 전달 대기 메시지를 구독기에 넘긴다', async () => {
    const tree = await ChatPage({ searchParams: { selected: TID } });

    expect(findElement(tree, ChatLiveRefresh)?.props).toEqual({
      threadId: TID,
      deliveryRefreshIds: ['m-out-2'],
    });
  });

  it('/chat 에서 목록만 볼 땐 열린 대화도 대기 메시지도 없다', async () => {
    const tree = await ChatPage({ searchParams: {} });

    expect(findElement(tree, ChatLiveRefresh)?.props).toEqual({
      threadId: undefined,
      deliveryRefreshIds: [],
    });
  });

  it('/chat/[id] 도 같은 구독기를 붙인다', async () => {
    const tree = await ThreadDetailPage({ params: { id: encodeURIComponent(TID) } });

    expect(findElement(tree, ChatLiveRefresh)?.props).toEqual({
      threadId: TID,
      deliveryRefreshIds: ['m-out-2'],
    });
  });
});


describe('대화 목록 서버 페이지 정보', () => {
  it('검색·안읽음·offset을 API로 보내고 전체 결과·미읽음 수를 사용한다', async () => {
    const meta = { total: 450, unreadTotal: 460, offset: 200, limit: 200, hasMore: true };
    vi.mocked(fetchThreadPage).mockResolvedValue({ data: [detail], meta });
    const tree = await ChatPage({ searchParams: { filter: 'unread', q: ' 고객 ', selected: TID, offset: '200' } });
    expect(fetchThreadPage).toHaveBeenCalledWith({ unread: true, q: '고객', offset: 200, limit: 200 });
    expect(findElement(tree, PageHeader)?.props.sub).toBe('450개 대화 · 안읽음 460건');
    expect(findElement(tree, ChatFilters)?.props).toMatchObject({ unreadCount: 460, selected: TID, q: '고객' });
    expect(findElement(tree, ThreadList)?.props).toMatchObject({ page: meta, activeId: TID, q: '고객' });
  });

  it.each(['-1', 'oops', '2.5', 'Infinity', '9007199254740992'])('잘못된 offset %s는 첫 페이지로 정규화한다', async (offset) => {
    await ChatPage({ searchParams: { offset } });
    expect(fetchThreadPage).toHaveBeenCalledWith({ unread: false, q: '', offset: 0, limit: 200 });
  });
});
