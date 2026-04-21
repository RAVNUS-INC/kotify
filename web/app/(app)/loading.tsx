import { Skeleton } from '@/components/motion';

export default function Loading() {
  return (
    <div className="k-page" aria-busy role="status" aria-label="대시보드 불러오는 중">
      <div className="k-page-head">
        <div>
          <Skeleton width="36%" height={28} radius={6} />
          <div className="mt-2">
            <Skeleton width="52%" height={14} radius={4} />
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Skeleton width={88} height={28} radius={6} />
          <Skeleton width={92} height={28} radius={6} />
        </div>
      </div>

      <Skeleton height={112} radius={8} />

      <div className="mt-6 grid gap-4 lg:grid-cols-[1.7fr_1fr]">
        <Skeleton height={420} radius={8} />

        <div className="flex flex-col gap-4">
          <Skeleton height={240} radius={8} />
          <div className="grid grid-cols-2 gap-3">
            <Skeleton height={92} radius={8} />
            <Skeleton height={92} radius={8} />
          </div>
          <Skeleton height={92} radius={8} />
        </div>
      </div>

      <span className="sr-only">콘텐츠를 불러오고 있습니다.</span>
    </div>
  );
}
