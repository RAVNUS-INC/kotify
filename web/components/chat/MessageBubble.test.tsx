import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { MessageBubble, type MessageStatus } from './MessageBubble';

describe('MessageBubble 발신 전달 상태', () => {
  it('전송 실패한 발신은 메타 라벨과 aria-label 에 실패를 텍스트로 표시한다', () => {
    render(
      <MessageBubble side="us" kind="rcs" status="failed" timestamp="01:38" senderName="가상 담당가">
        답장입니다
      </MessageBubble>,
    );

    // 색만이 아니라 텍스트로 — danger 색은 보조.
    expect(screen.getByText('01:38 / RCS / 가상 담당가 · 실패')).toHaveClass('text-danger');
    expect(screen.getByLabelText('보낸 RCS 메시지, 전송 실패')).toHaveTextContent('답장입니다');
  });

  it('결과를 기다리는 발신(SMS 대체 발송 중 포함)은 대기로 표시한다', () => {
    render(
      <MessageBubble side="us" kind="sms" status="pending" timestamp="01:38" senderName="가상 담당가">
        답장입니다
      </MessageBubble>,
    );

    expect(screen.getByText('01:38 / SMS / 가상 담당가 · 대기')).not.toHaveClass('text-danger');
    expect(screen.getByLabelText('보낸 SMS 메시지, 전송 대기')).toBeInTheDocument();
  });

  it('예약 취소로 발송되지 않은 발신은 대기가 아니라 취소로, 실패 색 없이 표시한다', () => {
    render(
      <MessageBubble side="us" kind="sms" status="cancelled" timestamp="01:36" senderName="가상 담당가">
        예약 안내
      </MessageBubble>,
    );

    const meta = screen.getByText('01:36 / SMS / 가상 담당가 · 취소');
    expect(meta).toHaveClass('text-ink-dim');
    expect(meta).not.toHaveClass('text-danger');
    expect(screen.getByLabelText('보낸 SMS 메시지, 전송 취소')).toHaveTextContent('예약 안내');
    expect(screen.queryByText(/대기/)).not.toBeInTheDocument();
  });

  const unchanged: Array<{ name: string; status?: MessageStatus }> = [
    { name: '전달 성공', status: 'sent' },
    { name: '결과를 알 수 없는(상태 없음)' },
  ];
  it.each(unchanged)('$name 발신은 작성자를 표시하고 상태 라벨은 생략한다', ({ status }) => {
    render(
      <MessageBubble side="us" kind="rcs" status={status} timestamp="01:38" senderName="가상 담당가">
        답장입니다
      </MessageBubble>,
    );

    expect(screen.getByText('01:38 / RCS / 가상 담당가')).toHaveClass('text-ink-dim');
    expect(screen.getByLabelText('보낸 RCS 메시지')).toBeInTheDocument();
    expect(screen.queryByText(/대기|실패|취소/)).not.toBeInTheDocument();
  });

  it('시간이 없으면 채널·작성자·상태를 표시한다', () => {
    render(
      <MessageBubble side="us" kind="lms" status="failed" senderName="가상 담당가">
        답장입니다
      </MessageBubble>,
    );

    expect(screen.getByText('LMS / 가상 담당가 · 실패')).toBeInTheDocument();
  });

  it('수신 말풍선은 status 와 senderName 이 와도 표시가 바뀌지 않는다', () => {
    render(
      <MessageBubble side="them" kind="rcs" status="failed" timestamp="01:38" senderName="가상 수신자명">
        고객 회신
      </MessageBubble>,
    );

    expect(screen.getByText('01:38 / RCS')).toHaveClass('text-ink-dim');
    expect(screen.getByLabelText('받은 RCS 메시지')).toBeInTheDocument();
    expect(screen.queryByText(/실패/)).not.toBeInTheDocument();
    expect(screen.queryByText(/가상 수신자명|알 수 없음/)).not.toBeInTheDocument();
  });
});

describe('MessageBubble 발신 작성자', () => {
  it.each([undefined, '', '   '])('작성자 값 %j 이 없으면 알 수 없음으로 표시한다', (senderName) => {
    render(
      <MessageBubble side="us" kind="sms" timestamp="12:31" senderName={senderName}>
        과거 발송
      </MessageBubble>,
    );

    expect(screen.getByText('12:31 / SMS / 알 수 없음')).toBeInTheDocument();
  });

  it('긴 작성자 이름도 메타에서 확인할 수 있다', () => {
    const senderName = '가상 업무지원부 고객응대팀 담당자';
    render(
      <MessageBubble side="us" kind="sms" timestamp="12:31" senderName={senderName}>
        안내 메시지
      </MessageBubble>,
    );

    expect(screen.getByText(`12:31 / SMS / ${senderName}`)).toBeInTheDocument();
    expect(screen.getByLabelText('보낸 SMS 메시지')).toHaveTextContent('안내 메시지');
  });
});
