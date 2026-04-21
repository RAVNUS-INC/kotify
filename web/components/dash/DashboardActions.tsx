'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Button, Icon } from '@/components/ui';

/**
 * 대시보드 헤더 오른쪽 액션 (새로고침 / 새 발송).
 *
 * page.tsx 는 RSC 라 onClick 이 불가하므로 이 client wrapper 로 분리.
 * - 새로고침: `router.refresh()` — RSC 데이터 재페치 트리거
 * - 새 발송: `/send/new` 로 Link 이동
 */
export function DashboardActions() {
  const router = useRouter();

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        icon={<Icon name="refresh" size={12} />}
        onClick={() => router.refresh()}
      >
        새로고침
      </Button>
      <Link
        href="/send/new"
        className="inline-flex h-8 items-center gap-1.5 rounded border border-brand bg-brand px-3 text-sm font-medium text-white transition-colors duration-fast ease-out hover:bg-brand-hover focus-visible:outline-none focus-visible:shadow-[0_0_0_3px_rgba(59,0,139,0.12)]"
      >
        <Icon name="send" size={12} />
        새 발송
      </Link>
    </>
  );
}
