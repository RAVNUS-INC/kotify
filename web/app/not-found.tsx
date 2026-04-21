import Link from 'next/link';
import '../styles/globals.css';
import { ErrorPage } from '@/components/error';
import { Icon } from '@/components/ui';

export default function NotFound() {
  return (
    <html lang="ko">
      <body>
        <ErrorPage
          code="404"
          icon="search"
          tone="neutral"
          title="페이지를 찾을 수 없습니다"
          description={
            <>
              주소가 정확한지 확인하거나 홈으로 돌아가세요.
              <br />
              삭제된 자원이거나 권한이 없을 수도 있습니다.
            </>
          }
          actions={
            <>
              <Link
                href="/"
                className="inline-flex h-9 items-center gap-1.5 rounded border border-brand bg-brand px-3 text-sm font-medium text-white transition-colors duration-fast ease-out hover:bg-brand-hover"
              >
                <Icon name="home" size={12} />
                홈으로
              </Link>
              <Link
                href="/search"
                className="inline-flex h-9 items-center gap-1.5 rounded border border-gray-4 bg-surface px-3 text-sm font-medium text-ink transition-colors duration-fast ease-out hover:bg-gray-1"
              >
                <Icon name="search" size={12} />
                검색
              </Link>
            </>
          }
        />
      </body>
    </html>
  );
}
