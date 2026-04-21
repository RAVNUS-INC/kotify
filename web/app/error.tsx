'use client';

import { useEffect, useMemo } from 'react';
import '../styles/globals.css';
import { ErrorPage } from '@/components/error';
import { Button, Icon } from '@/components/ui';

type RootErrorProps = {
  error: Error & { digest?: string };
  reset: () => void;
};

export default function RootError({ error, reset }: RootErrorProps) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error('[RootError]', error);
  }, [error]);

  const now = useMemo(
    () => new Date().toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }),
    [],
  );

  const isNetwork =
    error.message.includes('fetch failed') ||
    error.message.includes('ECONNREFUSED') ||
    error.message.includes('ENOTFOUND');

  return (
    <html lang="ko">
      <body>
        <ErrorPage
          code={isNetwork ? 'NETWORK' : '500'}
          icon="error"
          tone="danger"
          title={
            isNetwork ? 'API에 연결할 수 없습니다' : '페이지를 불러오지 못했습니다'
          }
          description={
            isNetwork
              ? 'FastAPI 서버 상태를 확인하거나 잠시 후 다시 시도하세요.'
              : error.message || '알 수 없는 오류가 발생했습니다.'
          }
          diagnostics={[
            { label: 'trace_id', value: error.digest ?? '—' },
            { label: 'time', value: now },
            { label: 'service', value: 'kotify-web' },
          ]}
          actions={
            <>
              <Button
                variant="primary"
                onClick={reset}
                icon={<Icon name="refresh" size={12} />}
              >
                다시 시도
              </Button>
              <a
                href="/"
                className="inline-flex h-9 items-center rounded border border-gray-4 bg-surface px-3 text-sm font-medium text-ink transition-colors duration-fast ease-out hover:bg-gray-1"
              >
                홈으로
              </a>
            </>
          }
        />
      </body>
    </html>
  );
}
