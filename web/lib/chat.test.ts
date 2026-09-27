import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import type { ChatMessage, ChatThreadDetail } from '@/types/chat';
import {
  fetchThreadPage, fetchThreads, formatChatDate, formatThreadTime, getDeliveryRefreshIds,
  markReadClient, sendMessageClient, withDateDividers,
} from './chat';
import { apiSend } from './csrf-client';

vi.mock('./csrf-client', () => ({ apiSend: vi.fn() }));
vi.mock('next/headers', () => ({
  cookies: () => ({ getAll: () => [{ name: 'session', value: 'test-session' }] }),
}));

beforeEach(() => vi.mocked(apiSend).mockReset());
afterEach(() => vi.unstubAllGlobals());

function thread(messages: ChatThreadDetail['messages']): ChatThreadDetail {
  return {
    id: '0212345678:01011112222',
    name: '01011112222',
    phone: '01011112222',
    preview: '',
    time: '10:00',
    date: '2026-09-27',
    channel: 'rcs',
    messages,
    lastInboundMessageId: null,
  };
}

describe('getDeliveryRefreshIds', () => {
  it('전달 대기와 늦은 리포트로 복구될 수 있는 실패를 고른다', () => {
    const detail = thread([
      { id: 'm-out-1', side: 'us', kind: 'rcs', text: '대기', time: '10:00', date: '2026-09-27', status: 'pending' },
      { id: 'm-out-2', side: 'us', kind: 'sms', text: '전달', time: '10:01', date: '2026-09-27', status: 'sent' },
      { id: 'm-out-3', side: 'us', kind: 'rcs', text: '실패', time: '10:02', date: '2026-09-27', status: 'failed' },
      { id: 'm-out-4', side: 'us', kind: 'sms', text: '결과를 알 수 없는 과거 발송', time: '10:03', date: '2026-09-27' },
      { id: 'm-in-5', side: 'them', kind: 'rcs', text: '회신', time: '10:04', date: '2026-09-27' },
      { id: 'm-out-6', side: 'us', kind: 'sms', text: '취소', time: '10:05', date: '2026-09-27', status: 'cancelled' },
    ]);

    expect(getDeliveryRefreshIds(detail)).toEqual(['m-out-1', 'm-out-3']);
  });

  it('열린 대화가 없으면 빈 목록', () => {
    expect(getDeliveryRefreshIds(null)).toEqual([]);
  });
});

describe('withDateDividers', () => {
  const message = (id: string, date: string): ChatMessage => ({
    id, side: 'them', kind: 'rcs', text: id, time: '10:00', date,
  });

  it('대화의 첫 메시지와 날짜가 바뀌는 첫 메시지 앞에만 구분선을 둔다', () => {
    const items = withDateDividers([
      message('a', '2026-09-26'), message('b', '2026-09-26'),
      message('c', '2026-09-27'), message('d', '2026-09-27'),
    ]);
    expect(items.map((item) => [item.message.id, item.dividerDate])).toEqual([
      ['a', '2026-09-26'], ['b', null], ['c', '2026-09-27'], ['d', null],
    ]);
  });

  it('날짜를 모르는 메시지는 구분선을 만들지 않고 비교 기준 날짜도 바꾸지 않는다', () => {
    const items = withDateDividers([
      message('a', ''), message('b', '2026-09-26'), message('c', ''),
      message('d', '2026-09-26'), message('e', '2026-09-27'),
    ]);
    expect(items.map((item) => item.dividerDate)).toEqual([null, '2026-09-26', null, null, '2026-09-27']);
  });
});

describe('formatChatDate', () => {
  afterEach(() => vi.unstubAllEnvs());

  it.each([
    ['2026-09-27', '2026년 9월 27일 일요일'],
    ['2026-09-26', '2026년 9월 26일 토요일'],
    ['2026-01-01', '2026년 1월 1일 목요일'],
    ['2024-02-29', '2024년 2월 29일 목요일'],
  ])('%s → %s', (date, label) => {
    expect(formatChatDate(date)).toBe(label);
  });

  it('브라우저 시간대와 무관하다 — UTC 보다 늦은 시간대에서도 요일이 하루 밀리지 않는다', () => {
    vi.stubEnv('TZ', 'America/Los_Angeles');
    expect(formatChatDate('2026-09-27')).toBe('2026년 9월 27일 일요일');
  });

  it.each(['', '2026-9-27', '2026-02-30', '날짜 없음'])('형식에 맞지 않거나 달력에 없는 %j 는 그대로 둔다', (date) => {
    expect(formatChatDate(date)).toBe(date);
  });
});

describe('formatThreadTime', () => {
  afterEach(() => vi.unstubAllEnvs());

  const last = (date: string, time = '14:05') => ({ time, date });

  it.each([
    ['2026-09-27', '14:05'],
    ['2026-09-26', '어제'],
    ['2026-09-25', '9월 25일'],
    ['2026-01-01', '1월 1일'],
    ['2025-12-31', '2025. 12. 31.'],
    // 월·일이 오늘과 같아도 해가 다르면 연도까지 — 오늘로 보이지 않는다.
    ['2025-09-27', '2025. 9. 27.'],
    // 시계 오차로 오늘보다 늦은 날짜 — 시각이나 "어제"로 보이지 않는다.
    ['2026-09-28', '9월 28일'],
  ])('기준일 2026-09-27 에 %s 대화는 %s', (date, label) => {
    expect(formatThreadTime(last(date), '2026-09-27')).toBe(label);
  });

  it.each([
    ['2027-01-01', '2026-12-31'], // 해가 바뀌어도 전날은 연도 없이 어제
    ['2026-10-01', '2026-09-30'],
    ['2024-03-01', '2024-02-29'],
    ['2026-03-01', '2026-02-28'],
  ])('기준일 %s 의 전날 %s 는 어제', (today, date) => {
    expect(formatThreadTime(last(date), today)).toBe('어제');
  });

  it('날짜나 기준일을 모르면 이전처럼 시각만 보인다', () => {
    expect(formatThreadTime(last(''), '2026-09-27')).toBe('14:05');
    expect(formatThreadTime(last('', ''), '2026-09-27')).toBe('');
    expect(formatThreadTime(last('2026-02-30'), '2026-09-27')).toBe('14:05');
    expect(formatThreadTime(last('2026-09-20'), '')).toBe('14:05');
  });

  it.each(['America/Los_Angeles', 'Pacific/Kiritimati'])('브라우저 시간대(%s)와 무관하다', (tz) => {
    vi.stubEnv('TZ', tz);
    expect(formatThreadTime(last('2026-09-26'), '2026-09-27')).toBe('어제');
    expect(formatThreadTime(last('2025-12-31'), '2026-01-01')).toBe('어제');
    expect(formatThreadTime(last('2026-01-01'), '2026-09-27')).toBe('1월 1일');
    // 서머타임이 바뀌는 날(LA 2026-03-08·11-01)은 현지 자정 사이가 23·25시간이다.
    expect(formatThreadTime(last('2026-03-08'), '2026-03-09')).toBe('어제');
    expect(formatThreadTime(last('2026-11-01'), '2026-11-02')).toBe('어제');
  });
});


describe('대화 API 페이지와 읽음 계약', () => {
  it('서버 목록 metadata를 보존하고 기존 배열 API도 유지한다', async () => {
    const data = [thread([])];
    const meta = { total: 450, unreadTotal: 500, offset: 200, limit: 200, hasMore: true, today: '2026-09-27' };
    const fetchMock = vi.fn().mockImplementation(async () => Response.json({ data, meta }));
    vi.stubGlobal('fetch', fetchMock);
    expect(await fetchThreadPage({ q: '고객', unread: true, limit: 200, offset: 200 })).toEqual({ data, meta });
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(new URL(url).searchParams.get('offset')).toBe('200');
    expect(new URL(url).searchParams.get('q')).toBe('고객');
    expect(new URL(url).searchParams.get('unread')).toBe('true');
    expect(init).toMatchObject({ cache: 'no-store', headers: { cookie: 'session=test-session' } });
    expect(await fetchThreads()).toEqual(data);
  });

  it('관측한 회신 id를 JSON으로 전송하고 비정상 응답은 성공으로 처리하지 않는다', async () => {
    vi.mocked(apiSend).mockResolvedValue(new Response('', { status: 403 }));
    await expect(markReadClient('caller:phone', 42)).rejects.toThrow('403');
    expect(apiSend).toHaveBeenCalledWith('/api/threads/caller%3Aphone/read', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lastReadMessageId: 42 }),
    });
  });

  it('발송 접수 미확정 오류의 code와 campaignId를 유지한다', async () => {
    vi.mocked(apiSend).mockResolvedValue(Response.json({ error: {
      code: 'send_status_unknown', message: '접수 여부를 확인 중입니다.', fields: { campaignId: '42' },
    } }, { status: 502 }));
    await expect(sendMessageClient('caller:phone', '안내', 'rcs')).rejects.toMatchObject({
      status: 502, code: 'send_status_unknown', fields: { campaignId: '42' },
    });
    expect(apiSend).toHaveBeenCalledTimes(1);
  });
});
