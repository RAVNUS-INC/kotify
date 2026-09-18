import { notFound } from 'next/navigation';
import Link from 'next/link';
import { PageHeader } from '@/components/shell';
import {
  ChatLiveRefresh,
  ThreadRecipientCard,
  ThreadView,
} from '@/components/chat';
import { Button, Icon } from '@/components/ui';
import { fetchThread, getDeliveryRefreshIds } from '@/lib/chat';
import { ApiError } from '@/lib/api';
import { formatPhone } from '@/lib/phone';

type PageProps = {
  params: { id: string };
};

export default async function ThreadDetailPage({ params }: PageProps) {
  const id = decodeURIComponent(params.id);
  let thread;
  try {
    thread = await fetchThread(id);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) {
      notFound();
    }
    throw err;
  }

  return (
    <div className="k-page">
      {/* SSE 구독 — 고객 회신, 전달 대기 메시지 결과를 새로고침 없이 갱신(UI 없음). */}
      <ChatLiveRefresh
        threadId={thread.id}
        deliveryRefreshIds={getDeliveryRefreshIds(thread)}
      />
      <PageHeader
        title={thread.name}
        sub={`${formatPhone(thread.phone)} · ${thread.messages.length}개 메시지`}
        actions={
          <Link
            href="/chat"
            className="inline-flex h-8 items-center gap-1 rounded border border-gray-4 bg-surface px-2.5 text-sm text-ink-muted transition-colors duration-fast ease-out hover:bg-gray-1"
          >
            <Icon name="arrowLeft" size={12} />
            대화방 목록
          </Link>
        }
      />

      <div
        className="grid gap-4 min-h-[600px]"
        style={{ gridTemplateColumns: '1fr 320px' }}
      >
        <ThreadView thread={thread} />
        <ThreadRecipientCard thread={thread} />
      </div>
    </div>
  );
}
