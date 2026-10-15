import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import type { ReactNode } from 'react';

import type { CallRecord } from '@/types/pbx';
import { CallsTable } from './CallsTable';
import { validateFaxInput } from './FaxComposer';
import { RecentCalls } from './RecentCalls';

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
