import type { InboxThread } from '@/types/dashboard';
import { Badge, Button, Card, CardBody, CardHeader, EmptyState, Icon } from '@/components/ui';
import { InboxThreadRow } from './InboxThreadRow';

export type InboxCardProps = {
  threads: ReadonlyArray<InboxThread>;
  unread: number;
};

export function InboxCard({ threads, unread }: InboxCardProps) {
  return (
    <Card className="flex h-full flex-col">
      <CardHeader
        eyebrow="미답 대화"
        title={
          <span className="flex items-center gap-2">
            인박스
            {unread > 0 && <Badge kind="brand">{unread}</Badge>}
          </span>
        }
        actions={
          <Button
            variant="ghost"
            size="sm"
            icon={<Icon name="refresh" size={12} />}
          >
            새로고침
          </Button>
        }
      />
      <CardBody padded={false} className="flex-1">
        {threads.length === 0 ? (
          <EmptyState
            icon="inbox"
            title="미답 대화 없음"
            description="오늘의 발송 큐가 곧 표시됩니다."
            size="md"
          />
        ) : (
          <ul className="divide-y divide-line">
            {threads.map((t) => (
              <InboxThreadRow key={t.id} thread={t} />
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
