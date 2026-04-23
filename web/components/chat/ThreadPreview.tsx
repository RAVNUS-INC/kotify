import Link from 'next/link';
import type { Route } from 'next';
import type { ChatThread } from '@/types/chat';
import { Badge, Button, EmptyState, Icon } from '@/components/ui';
import { cn } from '@/lib/cn';

export type ThreadPreviewProps = {
  thread?: ChatThread;
};

const CHANNEL_KIND_MAP: Record<ChatThread['channel'], 'brand' | 'neutral'> = {
  rcs: 'brand',
  sms: 'neutral',
  lms: 'neutral',
  mms: 'neutral',
  kakao: 'neutral',
};

export function ThreadPreview({ thread }: ThreadPreviewProps) {
  if (!thread) {
    return (
      <div className="flex items-center justify-center bg-surface-subtle">
        <EmptyState
          icon="chat"
          title="대화 선택"
          description="왼쪽 목록에서 대화를 선택하면 이곳에 요약이 표시됩니다."
          size="md"
        />
      </div>
    );
  }

  const href = `/chat/${encodeURIComponent(thread.id)}` as Route;

  return (
    <div className="flex flex-col overflow-y-auto bg-surface">
      <div className="border-b border-line px-6 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div
              className={cn(
                'flex h-10 w-10 shrink-0 items-center justify-center rounded-full font-mono text-[13px] text-ink',
                'bg-gray-3',
              )}
            >
              {thread.name.charAt(0)}
            </div>
            <div>
              <div className="text-base font-semibold text-ink">
                {thread.name}
                {thread.unread && (
                  <Badge kind="brand" className="ml-2">
                    새 메시지
                  </Badge>
                )}
              </div>
              <div className="font-mono text-[12.5px] text-ink-dim">
                {thread.phone}
              </div>
            </div>
          </div>

          <Link
            href={href}
            className="inline-flex h-8 items-center gap-1 rounded border border-brand bg-brand px-3 text-sm font-medium text-white transition-colors duration-fast ease-out hover:bg-brand-hover"
          >
            <Icon name="external" size={12} />
            스레드 열기
          </Link>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Badge kind={CHANNEL_KIND_MAP[thread.channel]}>
            {thread.channel.toUpperCase()}
          </Badge>
          {thread.lastCampaign && (
            <Badge kind="neutral" icon={<Icon name="zap" size={10} />}>
              {thread.lastCampaign}
            </Badge>
          )}
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-3 px-6 py-5">
        <div className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-ink-dim">
          최근 메시지
        </div>
        <div className="rounded-lg border border-line bg-gray-1 p-4 text-sm text-ink-muted">
          <p className="italic">{thread.preview}</p>
          <p className="mt-2 font-mono text-[11px] text-ink-dim">
            {thread.time}
          </p>
        </div>

        <div className="mt-2 grid grid-cols-2 gap-3">
          <Button variant="secondary" size="sm" icon={<Icon name="send" size={12} />}>
            답장
          </Button>
          <Button variant="ghost" size="sm" icon={<Icon name="check" size={12} />}>
            읽음 표시
          </Button>
        </div>

      </div>
    </div>
  );
}
