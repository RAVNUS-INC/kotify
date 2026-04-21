import type { ApiKey } from '@/types/settings';
import { Badge, Button, EmptyState, Icon, Pill } from '@/components/ui';

export type ApiKeysListProps = {
  keys: ReadonlyArray<ApiKey>;
};

export function ApiKeysList({ keys }: ApiKeysListProps) {
  if (keys.length === 0) {
    return (
      <EmptyState
        icon="key"
        title="API 키 없음"
        description="API 키를 생성하면 외부에서 Kotify를 호출할 수 있습니다."
        size="sm"
      />
    );
  }

  return (
    <ul role="list" className="flex flex-col divide-y divide-line">
      {keys.map((k) => (
        <li key={k.id} className="flex items-center gap-3 py-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate text-sm font-medium text-ink">
                {k.name}
              </span>
              {k.scopes.map((s) => (
                <Pill key={s} tone="neutral">
                  {s}
                </Pill>
              ))}
            </div>
            <div className="mt-0.5 flex items-center gap-2 font-mono text-[12.5px] text-ink-muted">
              <span>{k.prefix}...</span>
              <span className="text-ink-dim">·</span>
              <span>
                {k.lastUsedAt
                  ? `최근 사용 ${k.lastUsedAt}`
                  : '사용 이력 없음'}
              </span>
            </div>
          </div>
          <Badge kind="neutral" icon={<Icon name="calendar" size={10} />}>
            {k.createdAt}
          </Badge>
          <Button
            variant="ghost"
            size="sm"
            disabled
            aria-label={`${k.name} API 키 삭제`}
          >
            <Icon name="trash" size={12} />
          </Button>
        </li>
      ))}
    </ul>
  );
}
