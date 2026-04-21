import Link from 'next/link';
import { PageHeader } from '@/components/shell';
import { EmptyState, Icon } from '@/components/ui';

export default function ThreadNotFound() {
  return (
    <div className="k-page">
      <PageHeader title="스레드 없음" />
      <EmptyState
        icon="search"
        title="해당 대화를 찾을 수 없습니다"
        description="삭제되었거나 권한이 없는 스레드일 수 있습니다."
        size="md"
        action={
          <Link
            href="/chat"
            className="inline-flex h-8 items-center gap-1 rounded border border-brand bg-brand px-3 text-sm font-medium text-white transition-colors duration-fast ease-out hover:bg-brand-hover"
          >
            <Icon name="arrowLeft" size={12} />
            대화방으로
          </Link>
        }
      />
    </div>
  );
}
