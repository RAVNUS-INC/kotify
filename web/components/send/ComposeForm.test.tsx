import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { apiSend } from '@/lib/csrf-client';
import { ComposeForm, computeEstimate } from './ComposeForm';

const push = vi.hoisted(() => vi.fn());

// ComposeForm 은 useRouter() 를 쓰고, 발송·주소록 조회는 apiSend 로 나간다.
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push }),
}));
vi.mock('@/lib/csrf-client', () => ({
  apiSend: vi.fn(),
}));

describe('computeEstimate', () => {
  it('첨부 없는 단문(≤90B)은 RCS 17원 (기본 모드)', () => {
    const e = computeEstimate('안녕하세요', 10, false);
    expect(e.channel).toBe('SMS');
    expect(e.perUnit).toBe(17);
    expect(e.cost).toBe(170);
  });

  it('첨부 없는 장문(>90B)은 LMS 27원', () => {
    const e = computeEstimate('a'.repeat(100), 10, false);
    expect(e.channel).toBe('LMS');
    expect(e.perUnit).toBe(27);
  });

  it('첨부(이미지) 있으면 MMS 85원', () => {
    const e = computeEstimate('이미지 캠페인', 10, true);
    expect(e.channel).toBe('MMS');
    expect(e.perUnit).toBe(85);
    expect(e.cost).toBe(850);
  });

  it('첨부가 바이트 길이보다 우선 — 짧은 캡션 이미지도 MMS 85 (17원 과소추정 회귀 방지)', () => {
    const e = computeEstimate('여름 세일', 100, true);
    expect(e.perUnit).toBe(85);
    expect(e.cost).toBe(8500);
  });

  it('일반(sms) 모드 단문은 SMS 9원 (RCS 17 대비 절감)', () => {
    const e = computeEstimate('안녕하세요', 10, false, 'sms');
    expect(e.channel).toBe('SMS');
    expect(e.perUnit).toBe(9);
    expect(e.cost).toBe(90);
  });

  it('장문·이미지는 전송 방식과 무관하게 동일 단가 (27 / 85)', () => {
    expect(computeEstimate('a'.repeat(100), 10, false, 'sms').perUnit).toBe(27);
    expect(computeEstimate('a'.repeat(100), 10, false, 'rcs').perUnit).toBe(27);
    expect(computeEstimate('x', 10, true, 'sms').perUnit).toBe(85);
    expect(computeEstimate('x', 10, true, 'rcs').perUnit).toBe(85);
  });
});

describe('ComposeForm 전송 방식 기본값', () => {
  beforeEach(() => {
    // 발신번호 목록 (승인된 번호 1개).
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(JSON.stringify({ data: [{ number: '0212345678', brand: '코티파이' }] })),
      ),
    );
    vi.mocked(apiSend).mockImplementation(
      async (url) =>
        new Response(
          JSON.stringify(
            url === '/api/campaigns'
              ? { data: { id: 'c1' } }
              : {
                  data: {
                    byteLength: 9,
                    maxBytes: 2000,
                    valid: true,
                    error: null,
                    recipientCount: 1,
                    channel: 'SMS',
                    costMin: 17,
                    costMax: 17,
                  },
                },
          ),
        ),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  async function renderLoaded() {
    const user = userEvent.setup();
    render(<ComposeForm />);
    // 발신번호 로딩이 끝나야 발송 가능 상태가 된다.
    await waitFor(() => expect(screen.getByLabelText(/발신번호/)).toHaveValue('0212345678'));
    return user;
  }

  it('RCS 가 미리 선택되어 견적이 바로 보이고, 일반으로 바꿀 수 있다', async () => {
    const user = await renderLoaded();

    expect(screen.getByRole('radio', { name: /^RCS/ })).toBeChecked();
    expect(screen.getByRole('radio', { name: /^일반/ })).not.toBeChecked();
    expect(screen.getByText('자동 채널: RCS·SMS · 0 bytes')).toBeInTheDocument();

    await user.click(screen.getByRole('radio', { name: /^일반/ }));
    expect(screen.getByRole('radio', { name: /^일반/ })).toBeChecked();
    expect(screen.getByText('자동 채널: SMS · 0 bytes')).toBeInTheDocument();
  });

  it('전송 방식을 건드리지 않고 발송하면 sendChannel=rcs 로 요청한다', async () => {
    const user = await renderLoaded();

    await user.type(screen.getByRole('textbox', { name: /수신자/ }), '01012345678{Enter}');
    await user.type(screen.getByRole('textbox', { name: /메시지/ }), '안내 문자');
    await waitFor(() => expect(screen.getByText(/예상 1건/)).toBeInTheDocument());
    await user.click(screen.getByRole('checkbox', { name: /발송됨을 확인/ }));
    await user.click(screen.getByRole('button', { name: '발송' }));

    await waitFor(() => expect(push).toHaveBeenCalledWith('/campaigns'));
    const call = vi.mocked(apiSend).mock.calls.find(([url]) => url === '/api/campaigns');
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ sendChannel: 'rcs' });
  });
});
