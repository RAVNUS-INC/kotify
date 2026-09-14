import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import type { SessionUser } from '@/lib/auth';
import { Sidebar } from './Sidebar';

const pathname = vi.hoisted(() => ({ current: '/' }));

// Sidebar 는 usePathname() 를 쓰고 next/link 는 app-router 컨텍스트를 요구한다.
// 유닛 테스트에서는 최소 목킹으로 대체한다.
vi.mock('next/navigation', () => ({
  usePathname: () => pathname.current,
}));
vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string;
    children: ReactNode;
    'aria-current'?: 'page';
  }) => (
    <a href={href} aria-current={rest['aria-current']}>
      {children}
    </a>
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

beforeEach(() => {
  pathname.current = '/';
});

describe('Sidebar 권한 게이트', () => {
  it('admin 은 설정·감사 로그·새 발송 링크를 본다', () => {
    render(<Sidebar user={makeUser(['admin'])} />);
    expect(screen.getByRole('link', { name: /설정/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /감사 로그/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /새 발송/ })).toBeInTheDocument();
  });

  it.each([
    { label: 'viewer', roles: ['viewer'] },
    { label: 'sender', roles: ['sender'] },
    { label: 'viewer+sender', roles: ['viewer', 'sender'] },
  ])('비admin($label) 은 설정·감사 로그 링크가 노출되지 않는다', ({ roles }) => {
    render(<Sidebar user={makeUser(roles)} />);
    expect(screen.queryByRole('link', { name: /설정/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /감사 로그/ })).not.toBeInTheDocument();
  });

  it('새 발송 링크는 발송 권한(sender 이상)이 있을 때만 노출된다', () => {
    const { unmount } = render(<Sidebar user={makeUser(['viewer'])} />);
    expect(screen.queryByRole('link', { name: /새 발송/ })).not.toBeInTheDocument();
    unmount();

    render(<Sidebar user={makeUser(['sender'])} />);
    expect(screen.getByRole('link', { name: /새 발송/ })).toBeInTheDocument();
  });

  it('비admin(viewer) 도 발신번호 링크는 본다 (백엔드가 조회 허용)', () => {
    render(<Sidebar user={makeUser(['viewer'])} />);
    expect(screen.getByRole('link', { name: /발신번호/ })).toBeInTheDocument();
  });

  it('공통 링크(홈·발송 이력)는 역할과 무관하게 노출된다', () => {
    render(<Sidebar user={makeUser(['viewer'])} />);
    expect(screen.getByRole('link', { name: /홈/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /발송 이력/ })).toBeInTheDocument();
  });

  it('설정 링크는 기본 탭으로 바로 가고, 다른 탭에서도 활성 표시된다', () => {
    pathname.current = '/settings/messaging';
    render(<Sidebar user={makeUser(['admin'])} />);
    const link = screen.getByRole('link', { name: /설정/ });
    expect(link).toHaveAttribute('href', '/settings/org');
    expect(link).toHaveAttribute('aria-current', 'page');
  });
});
