import Link from 'next/link';
import type { Route } from 'next';
import { cn } from '@/lib/cn';

// 'urgent'(긴급)는 서버가 지원하지 않아 눌러도 전체 목록과 같았다 → 뺐다.
export type ChatFilter = 'all' | 'unread';

export type ChatFiltersProps = {
  active: ChatFilter;
  unreadCount?: number;
  selected?: string;
  q?: string;
};

const ITEMS: ReadonlyArray<{ value: ChatFilter; label: string }> = [
  { value: 'all', label: '전체' },
  { value: 'unread', label: '안읽음' },
];

/** 대화 목록 위의 세그먼트 필터. 열린 대화·검색어는 유지하고 페이지는 처음으로 돌린다. */
export function ChatFilters({ active, unreadCount = 0, selected, q }: ChatFiltersProps) {
  return (
    <nav aria-label="대화 필터" className="shrink-0 border-b border-line bg-surface px-4 pt-4 pb-3">
      <div className="k-segctrl">
        {ITEMS.map((item) => {
          const isActive = item.value === active;
          const qs = new URLSearchParams();
          if (item.value !== 'all') qs.set('filter', item.value);
          if (selected) qs.set('selected', selected);
          if (q) qs.set('q', q);
          const href = `/chat${qs.size ? `?${qs.toString()}` : ''}` as Route;
          const count = item.value === 'unread' ? unreadCount : undefined;
          return (
            <Link
              key={item.value}
              href={href}
              aria-current={isActive ? 'page' : undefined}
              className={cn(isActive && 'on')}
            >
              {item.label}
              {count != null && count > 0 && (
                <span className={cn('tabular-nums', isActive ? 'text-brand' : 'text-ink-dim')}>
                  {count}
                </span>
              )}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
