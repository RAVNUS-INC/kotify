import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import { InboxCard } from './InboxCard';

const row = (phone: string, time: string, date: string) => ({
  id: `0212345678:${phone}`, name: phone, phone, preview: `${phone} 회신`, time, date,
});

describe('대시보드 최근 대화 시각', () => {
  // 기준일은 실제 오늘과 먼 날짜 — 컴포넌트가 브라우저 시계를 쓰면 이 테스트가 깨진다.
  it('대시보드 응답의 기준일(inbox.today)로 오늘은 시각, 어제는 "어제", 그 전은 날짜로 보인다', () => {
    render(<InboxCard unread={0} today="2030-03-15" threads={[
      row('01000000001', '14:05', '2030-03-15'),
      row('01000000002', '23:59', '2030-03-14'),
      row('01000000003', '09:00', '2030-01-02'),
      row('01000000004', '09:00', '2029-12-31'),
    ]} />);

    const item = (phone: string) => within(screen.getByText(`${phone} 회신`).closest('li')!);
    expect(item('01000000001').getByText('14:05')).toBeInTheDocument();
    expect(item('01000000002').getByText('어제')).toBeInTheDocument();
    expect(item('01000000003').getByText('1월 2일')).toBeInTheDocument();
    expect(item('01000000004').getByText('2029. 12. 31.')).toBeInTheDocument();
    expect(screen.queryByText('23:59')).not.toBeInTheDocument();
    expect(screen.queryByText('09:00')).not.toBeInTheDocument();
  });
});
