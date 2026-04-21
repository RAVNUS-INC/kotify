'use client';

import { useEffect } from 'react';
import { Button, Icon } from '@/components/ui';

type ErrorProps = {
  error: Error & { digest?: string };
  reset: () => void;
};

export default function AppError({ error, reset }: ErrorProps) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error('[AppError]', error);
  }, [error]);

  const isNetwork =
    error.message.includes('fetch failed') ||
    error.message.includes('ECONNREFUSED') ||
    error.message.includes('ENOTFOUND');

  return (
    <div className="k-page">
      <div
        role="alert"
        aria-live="assertive"
        className="mx-auto flex max-w-md flex-col items-center gap-3 py-16 text-center"
      >
        <div className="flex h-14 w-14 items-center justify-center rounded-full bg-danger-bg text-danger">
          <Icon name="error" size={26} />
        </div>

        <div className="font-mono text-[11px] uppercase tracking-[0.08em] text-danger">
          {isNetwork ? 'API 연결 실패' : 'Error'}
        </div>

        <h1 className="text-2xl font-semibold tracking-tight">
          페이지를 불러오지 못했습니다
        </h1>

        <p className="text-sm leading-relaxed text-ink-muted">
          {isNetwork
            ? '백엔드 API에 연결할 수 없습니다. FastAPI 서버가 기동 중인지 확인하세요.'
            : error.message || '알 수 없는 오류가 발생했습니다.'}
        </p>

        {error.digest && (
          <p className="font-mono text-[11px] text-ink-dim">
            trace_id: <span className="font-semibold">{error.digest}</span>
          </p>
        )}

        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          <Button
            variant="primary"
            onClick={reset}
            icon={<Icon name="refresh" />}
          >
            다시 시도
          </Button>
          <a
            href="/"
            className="inline-flex h-9 items-center rounded border border-gray-4 bg-surface px-3 text-sm font-medium text-ink transition-colors duration-fast ease-out hover:bg-gray-1"
          >
            홈으로
          </a>
        </div>
      </div>
    </div>
  );
}
