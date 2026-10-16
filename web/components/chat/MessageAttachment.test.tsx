import { describe, expect, it } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import { MessageAttachment } from './MessageAttachment';

describe('MessageAttachment 고객이 보낸 사진', () => {
  it('보관된 사진은 인증 경로 원본을 보여 주고 새 탭으로 연다', () => {
    render(<MessageAttachment attachment={{ kind: 'image', status: 'ready', url: '/api/chat/media/7' }} />);

    const img = screen.getByAltText('고객이 보낸 사진');
    expect(img).toHaveAttribute('src', '/api/chat/media/7');
    const link = screen.getByRole('link', { name: '고객이 보낸 사진 원본 보기 (새 탭)' });
    expect(link).toHaveAttribute('href', '/api/chat/media/7');
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  });

  it('원본 요청이 실패하면 깨진 그림 대신 문구를 보인다', () => {
    render(<MessageAttachment attachment={{ kind: 'image', status: 'ready', url: '/api/chat/media/7' }} />);
    fireEvent.error(screen.getByAltText('고객이 보낸 사진'));

    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.getByText('사진을 불러올 수 없습니다')).toBeInTheDocument();
  });

  it.each([
    ['pending', '사진을 불러오는 중입니다'],
    ['failed', '사진을 불러올 수 없습니다'],
    ['unsupported', '사진이 아닌 첨부 파일은 볼 수 없습니다'],
  ] as const)('%s 는 그림 없이 문구만', (status, text) => {
    render(<MessageAttachment attachment={{ kind: 'image', status }} />);

    expect(screen.getByText(text)).toBeInTheDocument();
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('사진이 아닌 MMS 첨부는 그림 없이 내려받기 링크만', () => {
    render(<MessageAttachment attachment={{ kind: 'file', status: 'ready', url: '/api/chat/media/9' }} />);

    expect(screen.queryByRole('img')).toBeNull();
    const link = screen.getByRole('link', { name: '첨부 파일 내려받기' });
    expect(link).toHaveAttribute('href', '/api/chat/media/9');
    expect(link).toHaveAttribute('download');
  });

  it('파일 첨부의 대기·실패 문구는 첨부 파일로', () => {
    const { rerender } = render(<MessageAttachment attachment={{ kind: 'file', status: 'pending' }} />);
    expect(screen.getByText('첨부 파일을 불러오는 중입니다')).toBeInTheDocument();
    rerender(<MessageAttachment attachment={{ kind: 'file', status: 'failed' }} />);
    expect(screen.getByText('첨부 파일을 불러올 수 없습니다')).toBeInTheDocument();
  });
});
