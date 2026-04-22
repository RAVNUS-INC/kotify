'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { SetupWizard } from '@/components/setup';
import { fetchSetupStatus, type SetupStatus } from '@/lib/setup';
import '../../styles/globals.css';

/**
 * Fresh install 초기 설정 페이지. (app) 그룹 *밖* 이라 shell/sidebar 미적용.
 *
 * SSR 로 /setup/status 를 불러오면 Starlette SessionMiddleware 가 발급하는
 * Set-Cookie 가 Next.js 서버에서 소실되어 브라우저에 전달되지 않는다. 그 결과
 * 후속 POST (CSRF 검증 필요) 시 "CSRF 토큰이 없습니다" 오류. 해결책으로 세션
 * 쿠키가 직접 브라우저에 세팅될 수 있도록 client-side 에서 fetch.
 *
 * 이미 완료된 환경에서 접근하면 홈(`/`) 으로 라우터 push.
 */
export default function SetupPage() {
  const router = useRouter();
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const s = await fetchSetupStatus();
        if (cancelled) return;
        if (s.completed) {
          router.replace('/');
          return;
        }
        setStatus(s);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : '상태 확인 실패');
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router]);

  if (error) {
    return (
      <main className="min-h-screen bg-canvas px-6 py-10">
        <div className="mx-auto mt-16 max-w-xl rounded-lg border border-line bg-surface p-6 text-center">
          <h1 className="text-lg font-semibold text-ink">
            설정 상태를 확인할 수 없습니다
          </h1>
          <p className="mt-2 text-sm text-ink-muted">{error}</p>
        </div>
      </main>
    );
  }

  if (!status) {
    return (
      <main className="min-h-screen bg-canvas px-6 py-10">
        <div className="mx-auto max-w-xl p-6 text-center text-sm text-ink-dim">
          설정 상태 확인 중…
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-canvas px-6 py-10">
      <SetupWizard initial={status} />
    </main>
  );
}
