import Link from 'next/link';
import { ErrorPage } from './ErrorPage';

export type ForbiddenNoticeProps = {
  /** 페이지 성격에 맞춘 안내 문구 (기본: 관리자 전용). */
  description?: string;
};

/**
 * 권한 부족(403) 안내 페이지.
 *
 * admin 전용 페이지(설정·감사 로그 등)를 비admin이 직접 URL/북마크로 열었을 때,
 * 서버 컴포넌트가 apiFetch 403 을 그대로 throw 하면 error.tsx 경계로 떨어지는데
 * 프로덕션에서 Next 가 서버 렌더 에러 메시지를 마스킹해 "권한 없음"임을 알 수 없다.
 * 그래서 페이지에서 역할을 미리 확인하고 이 컴포넌트를 렌더해 명확히 안내한다.
 */
export function ForbiddenNotice({
  description = '이 페이지는 관리자만 볼 수 있습니다. 접근이 필요하면 관리자에게 권한을 요청하세요.',
}: ForbiddenNoticeProps) {
  return (
    <div className="k-page">
      <ErrorPage
        code="403"
        icon="lock"
        tone="warning"
        title="접근 권한이 없습니다"
        description={description}
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
