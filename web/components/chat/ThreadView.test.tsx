import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { ChatThreadDetail } from '@/types/chat';
import { ThreadView } from './ThreadView';
import { markReadClient } from '@/lib/chat';

const mocks = vi.hoisted(() => ({ refresh: vi.fn() }));

vi.mock('next/navigation', () => {
  const router = { refresh: mocks.refresh };
  return { useRouter: () => router };
});
vi.mock('@/lib/chat', () => ({
  markReadClient: vi.fn().mockResolvedValue(undefined),
  sendMessageClient: vi.fn(),
}));
vi.mock('@/lib/reply-validation', () => ({
  validateReplyClient: vi.fn().mockResolvedValue({
    byteLength: 0,
    maxBytes: 90,
    valid: false,
    error: null,
  }),
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
    lastInboundMessageId: null,
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

describe('ThreadView 실시간 갱신', () => {
  it('SSE 를 따로 구독하지 않는다 — 페이지의 ChatLiveRefresh 하나가 탭당 새로고침을 1회로 맡는다', () => {
    const EventSourceSpy = vi.fn();
    vi.stubGlobal('EventSource', EventSourceSpy);
    try {
      render(<ThreadView thread={thread('0212345678:01011112222')} />);
      expect(EventSourceSpy).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe('ThreadView 발신 작성자와 전달 상태', () => {
  it('각 메시지의 API 작성자·상태를 전달하고 과거 발신과 고객 회신을 구분한다', () => {
    render(
      <ThreadView
        thread={{
          ...thread('0212345678:01011112222'),
          messages: [
            {
              id: 'm-out-1',
              side: 'us',
              kind: 'rcs',
              text: '전달된 답장',
              time: '01:30',
              status: 'sent',
              senderName: '가상 담당가',
            },
            {
              id: 'm-out-2',
              side: 'us',
              kind: 'rcs',
              text: '실패한 답장',
              time: '01:38',
              status: 'failed',
              senderName: '가상 담당나',
            },
            {
              id: 'm-out-3',
              side: 'us',
              kind: 'sms',
              text: '작성자 정보 없는 과거 발송',
              time: '01:40',
            },
            {
              id: 'm-in-4',
              side: 'them',
              kind: 'rcs',
              text: '고객 회신',
              time: '01:42',
              senderName: '잘못 전달된 가상 작성자',
            },
          ],
        }}
      />,
    );

    expect(screen.getByText('01:30 / RCS / 가상 담당가')).toBeInTheDocument();
    expect(screen.getByText('01:38 / RCS / 가상 담당나 · 실패')).toBeInTheDocument();
    expect(screen.getByText('01:40 / SMS / 알 수 없음')).toBeInTheDocument();
    expect(screen.getByText('01:42 / RCS')).toBeInTheDocument();
    expect(screen.queryByText(/잘못 전달된 가상 작성자/)).not.toBeInTheDocument();
  });
});


beforeEach(() => {
  mocks.refresh.mockReset();
  vi.mocked(markReadClient).mockReset().mockResolvedValue(undefined);
});

describe('ThreadView 관측한 회신만 읽음 처리', () => {
  it('서버에서 실제로 조회한 회신 id를 보내며 unread가 계속 true여도 새 회신을 읽는다', async () => {
    const first = { ...thread('0212345678:01011112222'), unread: true, lastInboundMessageId: 41 };
    const { rerender } = render(<ThreadView thread={first} />);
    await waitFor(() => expect(markReadClient).toHaveBeenCalledWith(first.id, 41));
    rerender(<ThreadView thread={{ ...first, lastInboundMessageId: 42 }} />);
    await waitFor(() => expect(markReadClient).toHaveBeenLastCalledWith(first.id, 42));
    expect(markReadClient).toHaveBeenCalledTimes(2);
  });

  it('다른 대화로 이동한 후 도착하는 이전 읽음 응답은 새 화면을 갱신하지 않는다', async () => {
    let finish: (() => void) | undefined;
    vi.mocked(markReadClient).mockImplementationOnce(() => new Promise<void>((resolve) => { finish = resolve; }));
    const { rerender } = render(<ThreadView thread={{
      ...thread('0212345678:01011112222'), unread: true, lastInboundMessageId: 41,
    }} />);
    rerender(<ThreadView thread={thread('0212345678:01033334444')} />);
    await act(async () => { finish?.(); });
    expect(mocks.refresh).not.toHaveBeenCalled();
  });

  it('같은 회신의 읽음 실패는 재렌더만으로 반복 요청하지 않는다', async () => {
    vi.mocked(markReadClient).mockRejectedValue(new Error('읽음 처리 실패'));
    const detail = { ...thread('0212345678:01011112222'), unread: true, lastInboundMessageId: 41 };
    const { rerender } = render(<ThreadView thread={detail} />);
    await act(async () => {});
    rerender(<ThreadView thread={{ ...detail }} />);
    expect(markReadClient).toHaveBeenCalledTimes(1);
    expect(mocks.refresh).not.toHaveBeenCalled();
  });

  it('실제 관측한 회신이 없으면 읽음 요청을 보내지 않는다', () => {
    render(<ThreadView thread={{ ...thread('0212345678:01011112222'), unread: true }} />);
    expect(markReadClient).not.toHaveBeenCalled();
  });
});
