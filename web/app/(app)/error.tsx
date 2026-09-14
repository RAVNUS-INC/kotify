'use client';

import { useEffect, useState } from 'react';
import { ErrorPage, ForbiddenNotice } from '@/components/error';
import { Button, Icon } from '@/components/ui';
import { parseApiErrorDigest } from '@/lib/api-error';

const LINK_BUTTON_CLASS =
  'inline-flex h-9 items-center rounded border border-gray-4 bg-surface px-3 text-sm font-medium text-ink transition-colors duration-fast ease-out hover:bg-gray-1';

type AppErrorProps = {
  error: Error & { digest?: string };
  reset: () => void;
};

export default function AppError({ error, reset }: AppErrorProps) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error('[AppError]', error);
  }, [error]);

  // hydration-safe (RootError와 동일 패턴)
  const [now, setNow] = useState('');
  useEffect(() => {
    setNow(new Date().toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' }));
  }, []);

  // 프로덕션에선 message 가 가려지므로 ApiError digest 로 원인을 구분한다.
  const apiError = parseApiErrorDigest(error.digest);
  if (apiError?.status === 403) return <ForbiddenNotice />;
  if (apiError?.code === 'auth_required' || apiError?.code === 'setup_required') {
    const needsSetup = apiError.code === 'setup_required';
    return (
      <div className="k-page">
        <ErrorPage
          code={needsSetup ? 'SETUP' : '401'}
          icon={needsSetup ? 'settings' : 'lock'}
          tone="warning"
          title={needsSetup ? '초기 설정이 완료되지 않았습니다' : '로그인이 필요합니다'}
          description={
            needsSetup
              ? '관리자가 초기 설정을 마쳐야 사용할 수 있습니다. 관리자에게 문의하세요.'
              : '세션이 만료되었습니다. 다시 로그인해 주세요.'
          }
          actions={
            <a href={needsSetup ? '/setup' : '/login'} className={LINK_BUTTON_CLASS}>
              {needsSetup ? '설정 화면으로' : '로그인'}
            </a>
          }
        />
      </div>
    );
  }

  const isNetwork =
    error.message.includes('fetch failed') ||
    error.message.includes('ECONNREFUSED') ||
    error.message.includes('ENOTFOUND');

  return (
    <div className="k-page">
      <ErrorPage
        code={isNetwork ? 'NETWORK' : 'ERROR'}
        icon="error"
        tone="danger"
        title={
          isNetwork ? 'API에 연결할 수 없습니다' : '페이지를 불러오지 못했습니다'
        }
        description={
          isNetwork
            ? 'FastAPI 서버가 기동 중인지 확인하거나 잠시 후 다시 시도하세요.'
            : error.message || '알 수 없는 오류가 발생했습니다.'
        }
        diagnostics={[
          { label: 'trace_id', value: error.digest ?? '—' },
          { label: 'time', value: now || '—' },
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
            <a href="/" className={LINK_BUTTON_CLASS}>
              홈으로
            </a>
          </>
        }
      />
    </div>
  );
}
