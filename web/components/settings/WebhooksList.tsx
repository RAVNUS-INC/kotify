import type { Webhook } from '@/types/settings';
import { Badge, Button, EmptyState, Icon, Pill } from '@/components/ui';
import { cn } from '@/lib/cn';

export type WebhooksListProps = {
  webhooks: ReadonlyArray<Webhook>;
};

export function WebhooksList({ webhooks }: WebhooksListProps) {
  if (webhooks.length === 0) {
    return (
      <EmptyState
        icon="zap"
        title="웹훅 없음"
        description="외부 시스템에 실시간 이벤트를 전달하려면 웹훅을 등록하세요."
        size="sm"
      />
    );
  }

  return (
    <ul role="list" className="flex flex-col divide-y divide-line">
      {webhooks.map((w) => (
        <li
          key={w.id}
          className={cn(
            'flex items-center gap-3 py-3',
            !w.active && 'opacity-60',
          )}
        >
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate font-mono text-[12.5px] text-ink">
                {w.url}
              </span>
              {!w.active && <Badge kind="neutral">비활성</Badge>}
            </div>
            <div className="mt-0.5 flex flex-wrap gap-1">
              {w.events.map((e) => (
                <Pill key={e} tone="neutral">
                  {e}
                </Pill>
              ))}
            </div>
          </div>
          <div className="font-mono text-[11px] text-ink-dim">{w.createdAt}</div>
          <Button
            variant="ghost"
            size="sm"
            disabled
            aria-label={`${w.url} 웹훅 삭제`}
          >
            <Icon name="trash" size={12} />
          </Button>
        </li>
      ))}
    </ul>
  );
}
