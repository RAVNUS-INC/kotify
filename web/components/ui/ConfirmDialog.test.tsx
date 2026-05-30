import { describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { useConfirm, type ConfirmOptions } from './ConfirmDialog';

/** useConfirm 을 쓰는 최소 테스트 컴포넌트 — 열기 버튼 클릭 시 confirm 결과를 onResult 로 보고. */
function Harness({
  onResult,
  options,
}: {
  onResult: (ok: boolean) => void;
  options: ConfirmOptions;
}) {
  const { confirm, dialog } = useConfirm();
  return (
    <>
      <button type="button" onClick={async () => onResult(await confirm(options))}>
        열기
      </button>
      {dialog}
    </>
  );
}

const baseOptions: ConfirmOptions = {
  title: '연락처 삭제',
  description: '홍길동 연락처를 삭제하시겠습니까?',
  tone: 'danger',
  confirmLabel: '삭제',
};

describe('useConfirm', () => {
  it('초기에는 다이얼로그가 보이지 않는다', () => {
    render(<Harness onResult={() => {}} options={baseOptions} />);
    expect(screen.queryByText('연락처 삭제')).not.toBeInTheDocument();
  });

  it('열면 제목·설명이 표시된다', async () => {
    const user = userEvent.setup();
    render(<Harness onResult={() => {}} options={baseOptions} />);

    await user.click(screen.getByRole('button', { name: '열기' }));

    expect(await screen.findByText('연락처 삭제')).toBeInTheDocument();
    expect(screen.getByText('홍길동 연락처를 삭제하시겠습니까?')).toBeInTheDocument();
  });

  it('확인 버튼을 누르면 true 로 resolve 된다', async () => {
    const user = userEvent.setup();
    const onResult = vi.fn();
    render(<Harness onResult={onResult} options={baseOptions} />);

    await user.click(screen.getByRole('button', { name: '열기' }));
    await user.click(await screen.findByRole('button', { name: '삭제' }));

    await waitFor(() => expect(onResult).toHaveBeenCalledWith(true));
  });

  it('취소 버튼을 누르면 false 로 resolve 된다', async () => {
    const user = userEvent.setup();
    const onResult = vi.fn();
    render(<Harness onResult={onResult} options={baseOptions} />);

    await user.click(screen.getByRole('button', { name: '열기' }));
    await user.click(await screen.findByRole('button', { name: '취소' }));

    await waitFor(() => expect(onResult).toHaveBeenCalledWith(false));
  });

  it('ESC 로 닫으면 false 로 resolve 된다 (확인 없이 파괴적 액션 차단)', async () => {
    const user = userEvent.setup();
    const onResult = vi.fn();
    render(<Harness onResult={onResult} options={baseOptions} />);

    await user.click(screen.getByRole('button', { name: '열기' }));
    await screen.findByRole('button', { name: '삭제' });
    await user.keyboard('{Escape}');

    await waitFor(() => expect(onResult).toHaveBeenCalledWith(false));
  });

  it('확인 후 다이얼로그가 닫힌다', async () => {
    const user = userEvent.setup();
    render(<Harness onResult={() => {}} options={baseOptions} />);

    await user.click(screen.getByRole('button', { name: '열기' }));
    await user.click(await screen.findByRole('button', { name: '삭제' }));

    await waitFor(() =>
      expect(screen.queryByText('연락처 삭제')).not.toBeInTheDocument(),
    );
  });

  it('default tone 은 확인 라벨 기본값이 "확인"', async () => {
    const user = userEvent.setup();
    render(
      <Harness onResult={() => {}} options={{ title: '계속할까요?' }} />,
    );

    await user.click(screen.getByRole('button', { name: '열기' }));

    expect(await screen.findByRole('button', { name: '확인' })).toBeInTheDocument();
  });
});
