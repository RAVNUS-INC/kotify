import Link from 'next/link';
import type { InboxThread } from '@/types/dashboard';
import { Badge, Card, CardBody, CardHeader, EmptyState } from '@/components/ui';
import { InboxThreadRow } from './InboxThreadRow';

export type InboxCardProps = {
  threads: ReadonlyArray<InboxThread>;
  unread: number;
  /** "YYYY-MM-DD" (KST) — 대시보드 응답의 inbox.today. */
  today: string;
};

export function InboxCard({ threads, unread, today }: InboxCardProps) {
  return (
    <Card className="flex h-full flex-col">
      {/* 예전 "새로고침" 버튼은 동작이 연결돼 있지 않았다 — 헤더의 새로고침이 화면 전체를 다시 불러온다 */}
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            답장 대기
            {unread > 0 && <Badge kind="brand">{unread}</Badge>}
          </span>
        }
        actions={
          <Link href="/chat" className="k-link text-md">
            대화방에서 보기
          </Link>
        }
      />
      <CardBody padded={false} className="flex-1">
        {threads.length === 0 ? (
          <EmptyState
            icon="inbox"
            title="기다리는 답장이 없습니다"
            description="고객이 답장을 보내면 여기에 표시됩니다."
            size="md"
          />
        ) : (
          <ul className="divide-y divide-line">
            {threads.map((t) => (
              <InboxThreadRow key={t.id} thread={t} today={today} />
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
