import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ThreadComposer } from './ThreadComposer';
import { ApiError } from '@/lib/api-error';
import type { ReplyValidation } from '@/lib/reply-validation';

const mocks = vi.hoisted(() => ({
  refresh: vi.fn(),
  sendMessageClient: vi.fn(),
  validateReplyClient: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: mocks.refresh }),
}));
vi.mock('@/lib/chat', () => ({
  sendMessageClient: mocks.sendMessageClient,
}));
vi.mock('@/lib/reply-validation', () => ({
  validateReplyClient: mocks.validateReplyClient,
}));

beforeEach(() => {
  mocks.refresh.mockReset();
  mocks.sendMessageClient.mockReset();
  mocks.validateReplyClient.mockReset();
  mocks.validateReplyClient.mockResolvedValue({
    byteLength: 10, maxBytes: 90, valid: true, error: null,
  });
  mocks.sendMessageClient.mockResolvedValue({
    id: 'm-out-1',
    side: 'us',
    kind: 'rcs',
    text: '안녕하세요',
    time: '10:00',
  });
});

afterEach(() => vi.useRealTimers());

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
    await waitFor(() => expect(sendButton()).toBeEnabled());
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
    await waitFor(() => expect(sendButton()).toBeEnabled());
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
    await waitFor(() => expect(sendButton()).toBeEnabled());
    await user.click(sendButton());

    await waitFor(() =>
      expect(mocks.sendMessageClient).toHaveBeenCalledWith('t1', '안녕하세요', 'rcs'),
    );
  });

  it('단축키(Shift+Enter) 발송도 선택된 방식으로 보낸다', async () => {
    const user = userEvent.setup();
    render(<ThreadComposer threadId="t1" defaultSendChannel="sms" />);

    await user.type(textbox(), '안녕하세요');
    await waitFor(() => expect(sendButton()).toBeEnabled());
    await user.keyboard('{Shift>}{Enter}{/Shift}');

    await waitFor(() =>
      expect(mocks.sendMessageClient).toHaveBeenCalledWith('t1', '안녕하세요', 'sms'),
    );
  });
});

describe('ThreadComposer 서버 바이트 검증', () => {
  it('빈 입력은 기본 한도와 0바이트를 안내하며 검증·발송 요청하지 않는다', () => {
    render(<ThreadComposer threadId="t1" />);
    expect(screen.getByText('답장은 최대 90바이트 · 한글 약 45자, 영문 약 90자')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('현재 0 / 90바이트');
    expect(sendButton()).toBeDisabled();
    fireEvent.change(textbox(), { target: { value: '   \n  ' } });
    expect(mocks.validateReplyClient).not.toHaveBeenCalled();
    expect(mocks.sendMessageClient).not.toHaveBeenCalled();
  });

  it('300ms 동안 입력을 합치고 trim한 본문을 서버에서 확인한 뒤 같은 본문으로 발송한다', async () => {
    vi.useFakeTimers();
    render(<ThreadComposer threadId="t1" />);
    fireEvent.change(textbox(), { target: { value: '앞' } });
    await act(() => vi.advanceTimersByTimeAsync(200));
    fireEvent.change(textbox(), { target: { value: '  앞뒤 공백  ' } });
    expect(screen.getByRole('status')).toHaveTextContent('길이 확인 중');
    expect(sendButton()).toBeDisabled();
    await act(() => vi.advanceTimersByTimeAsync(299));
    expect(mocks.validateReplyClient).not.toHaveBeenCalled();
    await act(() => vi.advanceTimersByTimeAsync(1));
    expect(mocks.validateReplyClient).toHaveBeenCalledOnce();
    expect(mocks.validateReplyClient).toHaveBeenCalledWith('앞뒤 공백', expect.any(AbortSignal));
    expect(screen.getByRole('status')).toHaveTextContent('현재 10 / 90바이트');
    await act(async () => fireEvent.submit(textbox().closest('form')!));
    expect(mocks.sendMessageClient).toHaveBeenCalledWith('t1', '앞뒤 공백', 'rcs');
    expect(textbox()).toHaveValue('');
  });

  it.each([
    { text: '가'.repeat(46), byteLength: 92, error: '답장은 90바이트 이내로 입력해 주세요.' },
    { text: '🙂', byteLength: null, error: '메시지에 지원되지 않는 문자가 포함되어 있습니다.' },
  ])('서버가 거부한 입력은 길이·오류를 표시하고 모든 발송 경로를 차단한다: $byteLength', async ({ text, byteLength, error }) => {
    vi.useFakeTimers();
    mocks.validateReplyClient.mockResolvedValue({ byteLength, maxBytes: 90, valid: false, error });
    render(<ThreadComposer threadId="t1" />);
    fireEvent.change(textbox(), { target: { value: text } });
    // 서버 응답을 기다리는 동안도 단축키와 직접 submit 은 발송하지 않는다.
    fireEvent.keyDown(textbox(), { key: 'Enter', ctrlKey: true });
    fireEvent.submit(textbox().closest('form')!);
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(screen.getByRole('alert')).toHaveTextContent(error);
    expect(textbox()).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByRole('status')).toHaveTextContent(
      byteLength === null ? '길이 확인 불가' : '현재 92 / 90바이트',
    );
    for (const modifiers of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }]) {
      fireEvent.keyDown(textbox(), { key: 'Enter', ...modifiers });
    }
    fireEvent.submit(textbox().closest('form')!);
    expect(sendButton()).toBeDisabled();
    expect(mocks.sendMessageClient).not.toHaveBeenCalled();
    expect(textbox()).toHaveValue(text);
  });

  it('이전 입력의 늦은 성공 응답은 취소되어 새 입력의 실패 검증을 덮지 않는다', async () => {
    vi.useFakeTimers();
    let finishOld!: (value: ReplyValidation) => void;
    mocks.validateReplyClient.mockImplementationOnce(() => new Promise<ReplyValidation>((resolve) => {
      finishOld = resolve;
    }));
    mocks.validateReplyClient.mockResolvedValueOnce({
      byteLength: 92, maxBytes: 90, valid: false, error: '90바이트 초과',
    });
    render(<ThreadComposer threadId="t1" />);
    fireEvent.change(textbox(), { target: { value: '이전 입력' } });
    await act(() => vi.advanceTimersByTimeAsync(300));
    const oldSignal = mocks.validateReplyClient.mock.calls[0]![1] as AbortSignal;
    fireEvent.change(textbox(), { target: { value: '가'.repeat(46) } });
    expect(oldSignal.aborted).toBe(true);
    await act(() => vi.advanceTimersByTimeAsync(300));
    await act(async () => finishOld({ byteLength: 9, maxBytes: 90, valid: true, error: null }));
    expect(screen.getByRole('status')).toHaveTextContent('현재 92 / 90바이트');
    expect(screen.getByRole('alert')).toHaveTextContent('90바이트 초과');
    fireEvent.keyDown(textbox(), { key: 'Enter', shiftKey: true });
    expect(mocks.sendMessageClient).not.toHaveBeenCalled();
  });

  it('검증된 본문을 바꾸면 이전 결과로 단축키 발송할 수 없다', async () => {
    vi.useFakeTimers();
    render(<ThreadComposer threadId="t1" />);
    fireEvent.change(textbox(), { target: { value: '검증한 본문' } });
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(sendButton()).toBeEnabled();
    fireEvent.change(textbox(), { target: { value: '바뀐 본문' } });
    fireEvent.keyDown(textbox(), { key: 'Enter', shiftKey: true });
    expect(sendButton()).toBeDisabled();
    expect(mocks.sendMessageClient).not.toHaveBeenCalled();
  });

  it('검증 조회와 재시도가 실패하면 오류를 유지하고 성공한 재시도 후에만 발송을 허용한다', async () => {
    vi.useFakeTimers();
    mocks.validateReplyClient.mockRejectedValueOnce(new Error('HTTP 503'));
    mocks.validateReplyClient.mockRejectedValueOnce(new Error('연결 오류'));
    render(<ThreadComposer threadId="t1" />);
    fireEvent.change(textbox(), { target: { value: '확인 요청' } });
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(screen.getByRole('alert')).toHaveTextContent('길이를 확인하지 못했습니다 (HTTP 503)');
    expect(sendButton()).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '다시 확인' }));
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(screen.getByRole('alert')).toHaveTextContent('연결 오류');
    expect(sendButton()).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '다시 확인' }));
    await act(() => vi.advanceTimersByTimeAsync(300));
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(sendButton()).toBeEnabled();
    expect(mocks.sendMessageClient).not.toHaveBeenCalled();
  });

  it('검증을 통과해도 disabled 는 발송을 막고 발송 거부 시 본문을 보존한다', async () => {
    vi.useFakeTimers();
    mocks.sendMessageClient.mockRejectedValueOnce(new Error('발송 권한이 없습니다'));
    const { rerender } = render(<ThreadComposer threadId="t1" />);
    fireEvent.change(textbox(), { target: { value: '보존할 본문' } });
    await act(() => vi.advanceTimersByTimeAsync(300));
    rerender(<ThreadComposer threadId="t1" disabled />);
    fireEvent.submit(textbox().closest('form')!);
    expect(mocks.sendMessageClient).not.toHaveBeenCalled();
    rerender(<ThreadComposer threadId="t1" />);
    await act(async () => fireEvent.submit(textbox().closest('form')!));
    expect(textbox()).toHaveValue('보존할 본문');
    expect(screen.getByRole('alert')).toHaveTextContent('발송 권한이 없습니다');
    expect(sendButton()).toBeEnabled();
  });

  it('발송 중 입력과 채널 선택을 잠그고 중복 submit 을 막는다', async () => {
    vi.useFakeTimers();
    let finishSend!: () => void;
    mocks.sendMessageClient.mockImplementationOnce(() => new Promise<void>((resolve) => {
      finishSend = resolve;
    }));
    render(<ThreadComposer threadId="t1" />);
    fireEvent.change(textbox(), { target: { value: '발송 중인 본문' } });
    await act(() => vi.advanceTimersByTimeAsync(300));
    fireEvent.submit(textbox().closest('form')!);
    expect(textbox()).toBeDisabled();
    expect(rcsRadio()).toBeDisabled();
    expect(smsRadio()).toBeDisabled();
    fireEvent.submit(textbox().closest('form')!);
    fireEvent.keyDown(textbox(), { key: 'Enter', shiftKey: true });
    expect(mocks.sendMessageClient).toHaveBeenCalledOnce();
    await act(async () => finishSend());
    expect(textbox()).toBeEnabled();
    expect(textbox()).toHaveValue('');
  });
});


describe('ThreadComposer 발송 오류 이력 갱신', () => {
  it.each(['send_status_unknown', 'send_failed'])('%s는 본문을 유지하고 기록만 갱신하며 자동 재발송하지 않는다', async (code) => {
    vi.useFakeTimers();
    mocks.sendMessageClient.mockRejectedValue(new ApiError(502, code, '접수 여부를 확인한 후 다시 보내 주세요.'));
    render(<ThreadComposer threadId="t1" />);
    fireEvent.change(textbox(), { target: { value: '확인할 답장' } });
    await act(() => vi.advanceTimersByTimeAsync(300));
    fireEvent.click(sendButton());
    await act(async () => {});
    expect(textbox()).toHaveValue('확인할 답장');
    expect(screen.getByRole('alert')).toHaveTextContent('접수 여부를 확인한 후 다시 보내 주세요.');
    expect(mocks.refresh).toHaveBeenCalledTimes(1);
    await act(() => vi.advanceTimersByTimeAsync(60_000));
    expect(mocks.sendMessageClient).toHaveBeenCalledTimes(1);
  });
});
