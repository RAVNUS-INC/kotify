import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ThreadComposer } from './ThreadComposer';

const mocks = vi.hoisted(() => ({
  refresh: vi.fn(),
  sendMessageClient: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: mocks.refresh }),
}));
vi.mock('@/lib/chat', () => ({
  sendMessageClient: mocks.sendMessageClient,
}));

beforeEach(() => {
  mocks.refresh.mockReset();
  mocks.sendMessageClient.mockReset();
  mocks.sendMessageClient.mockResolvedValue({
    id: 'm-out-1',
    side: 'us',
    kind: 'rcs',
    text: '안녕하세요',
    time: '10:00',
  });
});

const rcsRadio = () => screen.getByRole('radio', { name: 'RCS' });
const smsRadio = () => screen.getByRole('radio', { name: '일반 SMS' });
const textbox = () => screen.getByRole('textbox', { name: '메시지 입력' });
const sendButton = () => screen.getByRole('button', { name: /발송/ });

describe('ThreadComposer 전송 방식', () => {
  it('최근 전달 성공 방식을 RCS 기본값보다 우선해 선택하고 그 방식으로 발송한다', async () => {
    const user = userEvent.setup();
    render(<ThreadComposer threadId="0212345678:01099998888" defaultSendChannel="sms" />);

    expect(smsRadio()).toBeChecked();
    expect(rcsRadio()).not.toBeChecked();
    expect(screen.getByText('최근 전달 성공 방식')).toBeInTheDocument();

    await user.type(textbox(), '안녕하세요');
    await user.click(sendButton());

    await waitFor(() =>
      expect(mocks.sendMessageClient).toHaveBeenCalledWith(
        '0212345678:01099998888',
        '안녕하세요',
        'sms',
      ),
    );
    expect(mocks.refresh).toHaveBeenCalled();
  });

  it('다른 방식으로 바꾸면 바꾼 방식으로 발송하고 최근 방식 안내는 사라진다', async () => {
    const user = userEvent.setup();
    render(<ThreadComposer threadId="t1" defaultSendChannel="rcs" />);

    await user.click(smsRadio());
    expect(smsRadio()).toBeChecked();
    expect(screen.queryByText('최근 전달 성공 방식')).not.toBeInTheDocument();

    await user.type(textbox(), '확인했습니다');
    await user.click(sendButton());

    await waitFor(() =>
      expect(mocks.sendMessageClient).toHaveBeenCalledWith('t1', '확인했습니다', 'sms'),
    );
  });

  it('전달 성공 이력이 없으면 새 발송 화면처럼 RCS 를 기본 선택한다(최근 방식 안내 없음)', async () => {
    const user = userEvent.setup();
    render(<ThreadComposer threadId="t1" />);

    expect(rcsRadio()).toBeChecked();
    expect(smsRadio()).not.toBeChecked();
    expect(screen.queryByText('최근 전달 성공 방식')).not.toBeInTheDocument();

    await user.type(textbox(), '안녕하세요');
    await user.click(sendButton());

    await waitFor(() =>
      expect(mocks.sendMessageClient).toHaveBeenCalledWith('t1', '안녕하세요', 'rcs'),
    );
  });

  it('단축키(Shift+Enter) 발송도 선택된 방식으로 보낸다', async () => {
    const user = userEvent.setup();
    render(<ThreadComposer threadId="t1" defaultSendChannel="sms" />);

    await user.type(textbox(), '안녕하세요');
    await user.keyboard('{Shift>}{Enter}{/Shift}');

    await waitFor(() =>
      expect(mocks.sendMessageClient).toHaveBeenCalledWith('t1', '안녕하세요', 'sms'),
    );
  });
});
