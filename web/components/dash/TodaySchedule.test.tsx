import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { TodaySchedule } from './TodaySchedule';
import { InboxCard } from './InboxCard';

describe('오늘 일정', () => {
  it('캠페인을 시각 순으로, 상태를 글자로 보여준다', () => {
    render(
      <TodaySchedule
        now="23:52"
        events={[
          { id: '3', time: '14:30', label: '가을 이벤트', state: 'failed' },
          { id: '1', time: '00:10', label: '업데이트 소식', state: 'done' },
          { id: '2', time: '18:00', label: '미팅 리마인드', state: 'scheduled' },
        ]}
      />,
    );

    const rows = screen.getAllByRole('listitem');
    expect(rows.map((r) => within(r).getAllByText(/./)[0]?.textContent)).toEqual([
      '00:10',
      '14:30',
      '18:00',
    ]);
    expect(within(rows[0]!).getByText('완료')).toBeInTheDocument();
    expect(within(rows[1]!).getByText('실패')).toBeInTheDocument();
    expect(within(rows[2]!).getByText('예약')).toBeInTheDocument();
    expect(screen.getByText('23:52 기준')).toBeInTheDocument();
  });

  it('오늘 캠페인이 없으면 빈 상태 문구를 보여준다', () => {
    render(<TodaySchedule now="09:00" events={[]} />);
    expect(screen.getByText('오늘 발송한 캠페인이 없습니다')).toBeInTheDocument();
  });
});

describe('답장 대기 카드', () => {
  it('행을 누르면 그 대화방으로 간다', () => {
    render(
      <InboxCard
        unread={1}
        today="2030-03-15"
        threads={[
          {
            id: '0215880000:01055500037',
            name: '01055500037',
            phone: '01055500037',
            preview: '점검 시간 조정 가능할까요?',
            time: '22:32',
            date: '2030-03-15',
            unread: true,
          },
        ]}
      />,
    );

    expect(screen.getByRole('link', { name: /010-5550-0037/ })).toHaveAttribute(
      'href',
      '/chat/0215880000%3A01055500037',
    );
    expect(screen.getByRole('link', { name: '대화방에서 보기' })).toHaveAttribute('href', '/chat');
  });
});
