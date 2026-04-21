import Link from 'next/link';
import { ErrorPage } from '@/components/error';
import { Icon } from '@/components/ui';

// Service Worker로 오프라인 시 이 페이지를 서빙 (Phase 11+). 현재는 수동 네비
// 테스트용 정적 라우트 + middleware PUBLIC_PATTERNS에 이미 포함.
export default function OfflinePage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-subtle">
      <ErrorPage
        code="OFFLINE"
        icon="wifi"
        tone="neutral"
        title="연결이 끊겼습니다"
        description={
          <>
            네트워크 연결을 확인하세요.
            <br />
            연결이 복구되면 아래 버튼으로 다시 시도할 수 있습니다.
          </>
        }
        pulseDot
        actions={
          <>
            <a
              href="/"
              className="inline-flex h-9 items-center gap-1.5 rounded border border-brand bg-brand px-3 text-sm font-medium text-white transition-colors duration-fast ease-out hover:bg-brand-hover"
            >
              <Icon name="refresh" size={12} />
              다시 시도
            </a>
            <Link
              href="/login"
              className="inline-flex h-9 items-center rounded border border-gray-4 bg-surface px-3 text-sm font-medium text-ink transition-colors duration-fast ease-out hover:bg-gray-1"
            >
              로그인 화면
            </Link>
          </>
        }
      />
    </div>
  );
}
