import { PageHeader } from '@/components/shell';
import {
  MarkAllReadButton,
  NotificationFeed,
} from '@/components/notifications';
import { LinkSegmented } from '@/components/ui';
import { fetchNotifications } from '@/lib/notifications';
import type { NotificationKind } from '@/types/notification';

type FilterValue = 'all' | 'unread' | NotificationKind;

const VALID: ReadonlyArray<FilterValue> = [
  'all',
  'unread',
  'send_result',
  'system',
  'security',
  'billing',
];

function normalize(raw: string | string[] | undefined): FilterValue {
  if (typeof raw === 'string' && (VALID as ReadonlyArray<string>).includes(raw)) {
    return raw as FilterValue;
  }
  return 'all';
}

type PageProps = {
  searchParams?: { filter?: string };
};

export default async function NotificationsPage({ searchParams }: PageProps) {
  const filter = normalize(searchParams?.filter);
  const isUnread = filter === 'unread';
  const isKind = filter !== 'all' && filter !== 'unread';

  const { items, meta } = await fetchNotifications({
    unread: isUnread,
    kind: isKind ? filter : undefined,
  });

  return (
    <div className="k-page">
      <PageHeader
        title="알림"
        sub={`${items.length}건${meta.unreadTotal > 0 ? ` · 읽지 않음 ${meta.unreadTotal}` : ''}`}
        actions={<MarkAllReadButton disabled={meta.unreadTotal === 0} />}
      />

      <div className="mb-4">
        <LinkSegmented
          aria-label="알림 필터"
          active={filter}
          basePath="/notifications"
          param="filter"
          options={[
            { value: 'all', label: '전체' },
            { value: 'unread', label: `안읽음${meta.unreadTotal ? ` · ${meta.unreadTotal}` : ''}` },
            { value: 'send_result', label: '발송' },
            { value: 'system', label: '시스템' },
            { value: 'security', label: '보안' },
            { value: 'billing', label: '결제' },
          ]}
        />
      </div>

      <NotificationFeed items={items} />
    </div>
  );
}
