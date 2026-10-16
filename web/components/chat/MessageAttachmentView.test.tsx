import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { MessageAttachmentView } from './MessageAttachmentView';

describe('MessageAttachmentView', () => {
  it('받아 둔 이미지는 말풍선 안에 바로 보인다', () => {
    render(<MessageAttachmentView attachment={{ status: 'ready', url: '/api/threads/mo/3/content', isImage: true }} />);
    expect(screen.getByRole('img', { name: '받은 사진' })).toHaveAttribute('src', '/api/threads/mo/3/content');
  });

  it('이미지가 아니면 내려받기 링크만 준다', () => {
    render(<MessageAttachmentView attachment={{ status: 'ready', url: '/api/threads/mo/4/content', isImage: false }} />);
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '첨부 파일 받기' })).toHaveAttribute('href', '/api/threads/mo/4/content');
  });

  it('받아 오는 중·받을 수 없음을 글로 알린다', () => {
    const { rerender } = render(<MessageAttachmentView attachment={{ status: 'pending' }} />);
    expect(screen.getByText('첨부 파일을 받아 오는 중입니다')).toBeInTheDocument();
    rerender(<MessageAttachmentView attachment={{ status: 'unavailable' }} />);
    expect(screen.getByText(/첨부 파일을 받을 수 없습니다/)).toBeInTheDocument();
  });
});
