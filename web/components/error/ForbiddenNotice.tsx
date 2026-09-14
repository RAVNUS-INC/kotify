import Link from 'next/link';
import { FORBIDDEN_DESCRIPTION, FORBIDDEN_TITLE } from '@/lib/forbidden-page';
import { ErrorPage } from './ErrorPage';

/**
 * 권한 부족(403) 안내 — 앱 셸 안에서 보여줄 때.
 *
 * 역할 제한 경로는 middleware 가 먼저 막고 403 HTML(lib/forbidden-page.ts)을
 * 내려준다. 여기는 그 밖에 서버 컴포넌트의 apiFetch 가 403 을 던진 경우로,
 * (app)/error.tsx 가 ApiError digest 로 식별해 렌더한다.
 */
export function ForbiddenNotice() {
  return (
    <div className="k-page">
      <ErrorPage
        code="403"
        icon="lock"
        tone="warning"
        title={FORBIDDEN_TITLE}
        description={FORBIDDEN_DESCRIPTION}
        actions={
          <Link
            href="/"
            className="inline-flex h-9 items-center rounded border border-gray-4 bg-surface px-3 text-sm font-medium text-ink transition-colors duration-fast ease-out hover:bg-gray-1"
          >
            홈으로
          </Link>
        }
      />
    </div>
  );
}
