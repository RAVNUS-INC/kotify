import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { ChatFilters } from './ChatFilters';
import { ThreadList } from './ThreadList';

const thread = { id: 'caller:phone', name: '고객', phone: '01011112222', preview: '확인', time: '12:30', channel: 'sms' as const };

describe('대화 목록 페이지 이동', () => {
  it('200개 이후에도 다음·이전 링크로 접근하며 선택·검색·필터를 보존한다', () => {
    render(<ThreadList threads={[thread]} filter="unread" activeId={thread.id} q="고객" page={{
      total: 450, unreadTotal: 490, offset: 200, limit: 200, hasMore: true,
    }} />);
    const next = new URL(screen.getByRole('link', { name: '다음' }).getAttribute('href')!, 'http://localhost');
    expect(Object.fromEntries(next.searchParams)).toEqual({ selected: thread.id, filter: 'unread', q: '고객', offset: '400' });
    const previous = new URL(screen.getByRole('link', { name: '이전' }).getAttribute('href')!, 'http://localhost');
    expect(previous.searchParams.has('offset')).toBe(false);
    const row = new URL(screen.getByRole('link', { name: /고객.*확인/ }).getAttribute('href')!, 'http://localhost');
    expect(row.searchParams.get('offset')).toBe('200');
    expect(row.searchParams.get('q')).toBe('고객');
    expect(screen.getByText('450개 대화')).toBeInTheDocument();
  });

  it('검색 제출과 필터 변경은 페이지를 초기화하며 열린 대화를 유지한다', () => {
    const { container } = render(<>
      <ChatFilters active="all" selected={thread.id} q="고객" unreadCount={250} />
      <ThreadList threads={[thread]} filter="all" activeId={thread.id} q="고객" page={{
        total: 450, unreadTotal: 250, offset: 200, limit: 200, hasMore: true,
      }} />
    </>);
    const filter = new URL(screen.getByRole('link', { name: /안읽음\s*250/ }).getAttribute('href')!, 'http://localhost');
    expect(Object.fromEntries(filter.searchParams)).toEqual({ filter: 'unread', selected: thread.id, q: '고객' });
    const form = container.querySelector('form')!;
    const fields = Object.fromEntries(new FormData(form));
    expect(fields).toEqual({ selected: thread.id, q: '고객' });
  });
});
