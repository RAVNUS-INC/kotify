import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { ApiError } from '@/lib/api-error';
import AppError from './error';

vi.mock('next/link', () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

// 프로덕션처럼 message 는 가려지고 digest 만 남은 에러를 흉내낸다.
function maskedError(digest: string): Error & { digest: string } {
  return Object.assign(new Error('An error occurred in the Server Components render.'), {
    digest,
  });
}

describe('(app) error boundary', () => {
  it('ApiError 403 이면 권한 안내를 보여준다', () => {
    const { digest } = new ApiError(403, 'forbidden', '권한이 없습니다.');
    render(<AppError error={maskedError(digest)} reset={() => {}} />);
    expect(screen.getByText('접근 권한이 없습니다')).toBeInTheDocument();
  });

  it('세션 만료(auth_required)면 로그인 링크를 보여준다', () => {
    const { digest } = new ApiError(303, 'auth_required', '로그인이 필요합니다.');
    render(<AppError error={maskedError(digest)} reset={() => {}} />);
    expect(screen.getByText('로그인이 필요합니다')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '로그인' })).toHaveAttribute('href', '/login');
  });

  it('그 밖의 에러는 다시 시도 화면을 유지한다', () => {
    render(<AppError error={maskedError('3194136073')} reset={() => {}} />);
    expect(screen.getByText('페이지를 불러오지 못했습니다')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /다시 시도/ })).toBeInTheDocument();
  });
});
