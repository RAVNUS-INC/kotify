import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { ChatThreadDetail } from '@/types/chat';
import { ThreadView } from './ThreadView';

vi.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: vi.fn() }),
}));
vi.mock('./useChatStream', () => ({
  useChatStream: () => {},
}));
vi.mock('@/lib/chat', () => ({
  markReadClient: vi.fn().mockResolvedValue(undefined),
  sendMessageClient: vi.fn(),
}));

function thread(
  id: string,
  defaultSendChannel?: ChatThreadDetail['defaultSendChannel'],
): ChatThreadDetail {
  const phone = id.split(':')[1] ?? id;
  return {
    id,
    name: phone,
    phone,
    preview: '',
    time: '10:00',
    channel: 'rcs',
    messages: [],
    defaultSendChannel,
  };
}

describe('ThreadView 대화방 전환', () => {
  it('다른 대화방으로 바뀌면 입력 초안과 전송 방식이 새 번호 기준으로 리셋된다', async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <ThreadView thread={thread('0212345678:01011112222', 'rcs')} />,
    );

    await user.type(screen.getByRole('textbox', { name: '메시지 입력' }), 'A 고객에게 쓰던 답장');
    expect(screen.getByRole('radio', { name: 'RCS' })).toBeChecked();

    // 목록에서 다른 고객 선택 — 같은 위치의 ThreadView 에 새 thread 가 들어온다.
    rerender(<ThreadView thread={thread('0212345678:01033334444', 'sms')} />);

    expect(screen.getByRole('textbox', { name: '메시지 입력' })).toHaveValue('');
    expect(screen.getByRole('radio', { name: '일반 SMS' })).toBeChecked();
  });
});
