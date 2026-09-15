import { describe, expect, it } from 'vitest';

import type { ChatThreadDetail } from '@/types/chat';
import { getPendingDeliveryIds } from './chat';

function thread(messages: ChatThreadDetail['messages']): ChatThreadDetail {
  return {
    id: '0212345678:01011112222',
    name: '01011112222',
    phone: '01011112222',
    preview: '',
    time: '10:00',
    channel: 'rcs',
    messages,
  };
}

describe('getPendingDeliveryIds', () => {
  it('우리가 보낸 메시지 중 결과 리포트를 기다리는 것만 고른다', () => {
    const detail = thread([
      { id: 'm-out-1', side: 'us', kind: 'rcs', text: '대기', time: '10:00', status: 'pending' },
      { id: 'm-out-2', side: 'us', kind: 'sms', text: '전달', time: '10:01', status: 'sent' },
      { id: 'm-out-3', side: 'us', kind: 'rcs', text: '실패', time: '10:02', status: 'failed' },
      { id: 'm-out-4', side: 'us', kind: 'sms', text: '결과를 알 수 없는 과거 발송', time: '10:03' },
      { id: 'm-in-5', side: 'them', kind: 'rcs', text: '회신', time: '10:04' },
    ]);

    expect(getPendingDeliveryIds(detail)).toEqual(['m-out-1']);
  });

  it('열린 대화가 없으면 빈 목록', () => {
    expect(getPendingDeliveryIds(null)).toEqual([]);
  });
});
