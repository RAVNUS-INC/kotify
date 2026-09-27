import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { ChatFilters } from './ChatFilters';
import { ThreadList } from './ThreadList';

const thread = {
  id: 'caller:phone', name: '고객', phone: '01011112222', preview: '확인', time: '12:30', date: '2026-09-27',
  channel: 'sms' as const,
};

describe('대화 목록 페이지 이동', () => {
  it('200개 이후에도 다음·이전 링크로 접근하며 선택·검색·필터를 보존한다', () => {
    render(<ThreadList threads={[thread]} filter="unread" activeId={thread.id} q="고객" page={{
      total: 450, unreadTotal: 490, offset: 200, limit: 200, hasMore: true, today: '2026-09-27',
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
        total: 450, unreadTotal: 250, offset: 200, limit: 200, hasMore: true, today: '2026-09-27',
      }} />
    </>);
    const filter = new URL(screen.getByRole('link', { name: /안읽음\s*250/ }).getAttribute('href')!, 'http://localhost');
    expect(Object.fromEntries(filter.searchParams)).toEqual({ filter: 'unread', selected: thread.id, q: '고객' });
    const form = container.querySelector('form')!;
    const fields = Object.fromEntries(new FormData(form));
    expect(fields).toEqual({ selected: thread.id, q: '고객' });
  });
});

describe('대화 목록 시각', () => {
  // 기준일은 실제 오늘과 먼 날짜 — 컴포넌트가 브라우저 시계를 쓰면 이 테스트가 깨진다.
  it('목록 응답의 기준일(meta.today)로 오늘은 시각, 어제는 "어제", 그 전은 날짜로 보인다', () => {
    const rows = [
      { ...thread, id: 'c:1', name: '가 고객', time: '14:05', date: '2030-03-15' },
      { ...thread, id: 'c:2', name: '나 고객', time: '23:59', date: '2030-03-14' },
      { ...thread, id: 'c:3', name: '다 고객', time: '09:00', date: '2030-01-02' },
      { ...thread, id: 'c:4', name: '라 고객', time: '09:00', date: '2029-12-31' },
    ];
    render(<ThreadList threads={rows} filter="all" page={{
      total: 4, unreadTotal: 0, offset: 0, limit: 200, hasMore: false, today: '2030-03-15',
    }} />);

    const row = (name: string) => within(screen.getByRole('link', { name: new RegExp(name) }));
    expect(row('가 고객').getByText('14:05')).toBeInTheDocument();
    expect(row('나 고객').getByText('어제')).toBeInTheDocument();
    expect(row('다 고객').getByText('1월 2일')).toBeInTheDocument();
    expect(row('라 고객').getByText('2029. 12. 31.')).toBeInTheDocument();
    expect(screen.queryByText('23:59')).not.toBeInTheDocument();
    expect(screen.queryByText('09:00')).not.toBeInTheDocument();
  });
});
