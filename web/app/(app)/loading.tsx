import { Skeleton } from '@/components/motion';

// 홈(page.tsx)과 같은 배치: 머리글 → 숫자 카드 4개 → 답장 대기·오늘 일정 → 최근 발송 표
export default function Loading() {
  return (
    <div
      className="k-page flex flex-col gap-6"
      aria-busy
      role="status"
      aria-label="대시보드 불러오는 중"
    >
      <div className="k-page-head !mb-0">
        <div>
          <Skeleton width="36%" height={28} radius={6} />
          <div className="mt-2">
            <Skeleton width="52%" height={14} radius={4} />
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Skeleton width={88} height={36} radius={6} />
          <Skeleton width={92} height={36} radius={6} />
        </div>
      </div>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(200px,1fr))] gap-4">
        <Skeleton height={112} radius={10} />
        <Skeleton height={112} radius={10} />
        <Skeleton height={112} radius={10} />
        <Skeleton height={112} radius={10} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Skeleton height={360} radius={10} />
        <Skeleton height={360} radius={10} />
      </div>

      <Skeleton height={280} radius={10} />

      <span className="sr-only">콘텐츠를 불러오고 있습니다.</span>
    </div>
  );
}
