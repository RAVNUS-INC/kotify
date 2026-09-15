import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { RecipientStatusBadge } from './RecipientStatusBadge';

describe('RecipientStatusBadge', () => {
  it('예약 취소된 수신자는 대기가 아니라 캠페인 상태 배지와 같은 취소로 표시한다', () => {
    render(<RecipientStatusBadge status="cancelled" />);

    expect(screen.getByText('취소')).toHaveClass('text-warning');
    expect(screen.queryByText('대기')).not.toBeInTheDocument();
  });

  it('결과를 기다리는 수신자는 그대로 대기다', () => {
    render(<RecipientStatusBadge status="queued" />);

    expect(screen.getByText('대기')).toBeInTheDocument();
  });
});
