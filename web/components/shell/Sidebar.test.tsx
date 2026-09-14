import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import type { SessionUser } from '@/lib/auth';
import { Sidebar } from './Sidebar';

// Sidebar 는 usePathname() 를 쓰고 next/link 는 app-router 컨텍스트를 요구한다.
// 유닛 테스트에서는 최소 목킹으로 대체한다.
vi.mock('next/navigation', () => ({
  usePathname: () => '/',
}));
vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

function makeUser(roles: string[]): SessionUser {
  return {
    sub: 'sub-1',
    email: 'staff@example.com',
    name: '김직원',
    display: '김직원',
    roles,
  };
}

describe('Sidebar 권한 게이트', () => {
  it('admin 은 설정·감사 로그 링크를 본다', () => {
    render(<Sidebar user={makeUser(['admin'])} />);
    expect(screen.getByRole('link', { name: /설정/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /감사 로그/ })).toBeInTheDocument();
  });

  it.each([['viewer'], ['sender'], ['viewer', 'sender']])(
    '비admin(%s) 은 설정·감사 로그 링크가 노출되지 않는다',
    (...roles: string[]) => {
      render(<Sidebar user={makeUser(roles)} />);
      expect(screen.queryByRole('link', { name: /설정/ })).not.toBeInTheDocument();
      expect(
        screen.queryByRole('link', { name: /감사 로그/ }),
      ).not.toBeInTheDocument();
    },
  );

  it('비admin(viewer) 도 발신번호 링크는 본다 (백엔드가 조회 허용)', () => {
    render(<Sidebar user={makeUser(['viewer'])} />);
    expect(screen.getByRole('link', { name: /발신번호/ })).toBeInTheDocument();
  });

  it('공통 링크(홈·발송 이력)는 역할과 무관하게 노출된다', () => {
    render(<Sidebar user={makeUser(['viewer'])} />);
    expect(screen.getByRole('link', { name: /홈/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /발송 이력/ })).toBeInTheDocument();
  });
});
