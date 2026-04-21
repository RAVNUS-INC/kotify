import Link from 'next/link';
import type { Route } from 'next';
import { Icon } from '@/components/ui';
import { cn } from '@/lib/cn';

export type ChatFilter = 'all' | 'unread' | 'urgent';

export type ChatFiltersProps = {
  active: ChatFilter;
  unreadCount?: number;
};

type Item = {
  value: ChatFilter;
  label: string;
  icon: Parameters<typeof Icon>[0]['name'];
};

const ITEMS: ReadonlyArray<Item> = [
  { value: 'all', label: '전체', icon: 'inbox' },
  { value: 'unread', label: '안읽음', icon: 'bell' },
  { value: 'urgent', label: '긴급', icon: 'alert' },
];

export function ChatFilters({ active, unreadCount = 0 }: ChatFiltersProps) {
  return (
    <aside
      aria-label="대화 필터"
      className="flex flex-col gap-1 border-r border-line bg-gray-1 p-3"
    >
      <div className="mb-1 px-2 font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-ink-dim">
        대화
      </div>

      {ITEMS.map((item) => {
        const isActive = item.value === active;
        const href = (item.value === 'all' ? '/chat' : `/chat?filter=${item.value}`) as Route;
        const count = item.value === 'unread' ? unreadCount : undefined;
        return (
          <Link
            key={item.value}
            href={href}
            aria-current={isActive ? 'page' : undefined}
            className={cn(
              'flex items-center justify-between rounded px-2 py-1.5 text-md transition-colors duration-fast ease-out',
              isActive
                ? 'bg-surface text-ink font-medium shadow-xs'
                : 'text-ink-muted hover:bg-surface hover:text-ink',
            )}
          >
            <span className="flex items-center gap-2">
              <Icon name={item.icon} size={13} strokeWidth={1.6} />
              {item.label}
            </span>
            {count != null && count > 0 && (
              <span
                className={cn(
                  'font-mono text-[11px]',
                  isActive ? 'text-brand font-semibold' : 'text-ink-dim',
                )}
              >
                {count}
              </span>
            )}
          </Link>
        );
      })}

      <div className="mt-5 mb-1 px-2 font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-ink-dim">
        최근 캠페인
      </div>
      <div className="px-2 text-xs text-ink-dim">
        Phase 7에서 연결됩니다.
      </div>
    </aside>
  );
}
