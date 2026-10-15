import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';

import type { CallRecord, FaxInboxItem } from '@/types/pbx';
import { CallsTable } from './CallsTable';
import { FaxInboxTable } from './FaxInboxTable';
import { validateFaxInput } from './FaxComposer';
import { RecentCalls } from './RecentCalls';
import { formatDateTime } from '@/lib/datetime';

vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>,
}));
vi.mock('next/navigation', () => ({ useRouter: () => ({ refresh: vi.fn() }) }));

const call = (overrides: Partial<CallRecord> = {}): CallRecord => ({
  id: 1,
  at: '2026-10-15T09:05:00+09:00',
  direction: 'in',
  from: '01000000001',
  to: '101',
  durationSec: 80,
  billSec: 75,
  disposition: 'ANSWERED',
  recordingToken: 'tok-1',
  ...overrides,
});

const pdf = (size = 10, name = 'a.pdf', type = 'application/pdf') =>
  new File([new Uint8Array(size)], name, { type });

describe('validateFaxInput', () => {
  it('번호·파일을 서버와 같은 규칙으로 먼저 거른다', () => {
    expect(validateFaxInput('1234', pdf())).toMatch('번호');
    expect(validateFaxInput('02-0000-0000', null)).toMatch('선택');
    expect(validateFaxInput('02-0000-0000', pdf(0))).toBe('빈 파일입니다');
    expect(validateFaxInput('02-0000-0000', pdf(10, 'a.png', 'image/png'))).toMatch('PDF');
    expect(validateFaxInput('02-0000-0000', pdf())).toBeNull();
  });
});

describe('CallsTable', () => {
  it('녹음은 버튼을 누른 뒤에야 kotify 서버 경로로 audio 를 만든다', () => {
    const { container } = render(<CallsTable calls={[call(), call({ id: 2, recordingToken: null })]} />);
    expect(container.querySelector('audio')).toBeNull();
    expect(screen.getAllByRole('button', { name: /녹음 재생/ })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: /녹음 재생/ }));
    const audio = container.querySelector('audio');
    expect(audio?.getAttribute('src')).toBe('/api/pbx/recordings/tok-1');
    expect(screen.getAllByText('010-0000-0001')).toHaveLength(2);
    expect(screen.getAllByText('1:15')).toHaveLength(2);
  });
});

describe('CallsTable 이름', () => {
  it('주소록 이름이 있으면 이름 아래에 번호를 보인다', () => {
    render(<CallsTable calls={[call({ name: '가상 고객 (가상회사)' })]} />);
    expect(screen.getByText('가상 고객 (가상회사)')).toBeInTheDocument();
    expect(screen.getByText('010-0000-0001')).toBeInTheDocument();
  });
});

describe('RecentCalls', () => {
  it('PBX 를 쓸 수 없으면 섹션을 숨긴다', () => {
    const { container } = render(<RecentCalls phone="01000000001" result={{ status: 'unavailable' }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('최근 통화와 전체 보기 링크를 보여 준다', () => {
    render(<RecentCalls phone="01000000001" result={{ status: 'ok', calls: [call()] }} />);
    expect(screen.getByRole('link', { name: '전체 보기' })).toHaveAttribute('href', '/calls?phone=01000000001');
    expect(screen.getByText(/수신 · 통화/)).toBeInTheDocument();
  });
});

const inboxItem = (overrides: Partial<FaxInboxItem> = {}): FaxInboxItem => ({
  id: 7,
  receivedAt: '2026-10-15T16:06:00+00:00',
  senderNumber: '0200000009',
  senderName: null,
  status: 'RECEIVED',
  error: null,
  fetchStatus: 'FETCHED',
  sizeBytes: 25_600,
  firstViewedAt: null,
  firstViewedBy: null,
  ...overrides,
});

describe('FaxInboxTable', () => {
  it('새 팩스·PDF 보기 링크·KST 시각·이름을 보여 준다', () => {
    render(<FaxInboxTable items={[inboxItem({ senderName: '가상 거래처' })]} />);
    // UTC 16:06 → KST 01:06(다음 날). 표는 올해면 '10월 16일 01:06' 처럼 줄여 보인다.
    expect(screen.getByText(formatDateTime('2026-10-16 01:06'))).toBeInTheDocument();
    expect(screen.getByText('가상 거래처')).toBeInTheDocument();
    expect(screen.getByText('새 팩스')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /PDF 보기 25KB/ })).toHaveAttribute('href', '/api/fax/inbox/7/pdf');
  });

  it('수신 실패·가져오기 실패는 링크 없이, 다시 가져오기는 관리자만', () => {
    const items = [
      inboxItem({ id: 1, status: 'FAILED', fetchStatus: 'NONE', error: 'Timer T2 expired', sizeBytes: null }),
      inboxItem({ id: 2, fetchStatus: 'FETCH_FAILED', sizeBytes: null }),
    ];
    const { rerender } = render(<FaxInboxTable items={items} />);
    expect(screen.getByText('수신 실패')).toBeInTheDocument();
    expect(screen.getByText('Timer T2 expired')).toBeInTheDocument();
    expect(screen.getByText('PDF 못 가져옴')).toBeInTheDocument();
    expect(screen.queryByRole('link')).toBeNull();
    expect(screen.queryByRole('button', { name: /다시 가져오기/ })).toBeNull();
    rerender(<FaxInboxTable items={items} canRefetch />);
    expect(screen.getByRole('button', { name: /다시 가져오기/ })).toBeInTheDocument();
  });
});

describe('RecordingPlayer', () => {
  it('펼치면 재생 버튼·끌 수 있는 막대·시간을 직접 그리고, 막대를 옮기면 그 위치로 간다', () => {
    const { container } = render(<CallsTable calls={[call()]} />);
    fireEvent.click(screen.getByRole('button', { name: /녹음 재생/ }));
    const audio = container.querySelector('audio')!;
    // 브라우저 기본 재생기는 쓰지 않는다(표 칸에서 찌그러져 끌 수 없었다)
    expect(audio.hasAttribute('controls')).toBe(false);

    const slider = screen.getByRole('slider', { name: /재생 위치/ });
    expect(slider).toBeDisabled(); // 길이를 알기 전에는 끌 수 없다
    Object.defineProperty(audio, 'duration', { configurable: true, value: 62 });
    fireEvent(audio, new Event('loadedmetadata'));
    expect(slider).toBeEnabled();
    expect(screen.getByText('0:00 / 1:02')).toBeInTheDocument();

    fireEvent.change(slider, { target: { value: '30' } });
    expect(audio.currentTime).toBe(30);
    expect(screen.getByText('0:30 / 1:02')).toBeInTheDocument();
  });
});
