import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { CampaignDetailActions } from './CampaignDetailActions';

const mocks = vi.hoisted(() => ({
  refresh: vi.fn(),
  cancelCampaignClient: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ refresh: mocks.refresh }),
}));
vi.mock('@/lib/campaigns-client', () => ({
  cancelCampaignClient: mocks.cancelCampaignClient,
  buildCampaignExportHref: (id: string) => `/api/campaigns/${id}/export.csv`,
}));

beforeEach(() => {
  mocks.refresh.mockReset();
  mocks.cancelCampaignClient.mockReset();
  mocks.cancelCampaignClient.mockResolvedValue({
    id: 'c1', status: 'cancelled', message: '예약이 취소되었습니다',
  });
});

describe('CampaignDetailActions 예약 취소', () => {
  it('일부 요청 실패라도 서버가 남은 예약을 알리면 확인 후 취소하고 새로고침한다', async () => {
    const user = userEvent.setup();
    render(<CampaignDetailActions campaignId="c1" canCancel canCancelReservation />);

    await user.click(screen.getByRole('button', { name: '예약 취소' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: '예약 취소' }));

    await waitFor(() => expect(mocks.cancelCampaignClient).toHaveBeenCalledWith('c1'));
    expect(mocks.refresh).toHaveBeenCalledOnce();
  });

  it.each([
    { name: '취소 권한이 없는 사용자', canCancel: false, canCancelReservation: true },
    { name: '접수된 예약이 없는 즉시 발송', canCancel: true, canCancelReservation: false },
    { name: '이미 알려진 예약을 모두 취소한 캠페인', canCancel: true, canCancelReservation: false },
  ])('$name에게 취소 버튼을 표시하지 않는다', ({ canCancel, canCancelReservation }) => {
    render(<CampaignDetailActions
      campaignId="c1" canCancel={canCancel} canCancelReservation={canCancelReservation}
    />);

    expect(screen.queryByRole('button', { name: '예약 취소' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: '수신자 CSV' })).toBeInTheDocument();
  });

  it('미확정 예약이 남으면 콘솔 확인 안내를 알리고 갱신한다', async () => {
    const user = userEvent.setup();
    const warning = '10명은 접수 여부를 확인하지 못했습니다. msghub 웹 콘솔에서 확인하고 취소해 주세요.';
    mocks.cancelCampaignClient.mockResolvedValue({ id: 'c1', status: 'scheduled', message: warning });
    const alert = vi.spyOn(window, 'alert').mockImplementation(() => undefined);
    render(<CampaignDetailActions campaignId="c1" canCancel canCancelReservation />);

    await user.click(screen.getByRole('button', { name: '예약 취소' }));
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: '예약 취소' }));

    await waitFor(() => expect(alert).toHaveBeenCalledWith(warning));
    expect(mocks.refresh).toHaveBeenCalledOnce();
    alert.mockRestore();
  });
});
