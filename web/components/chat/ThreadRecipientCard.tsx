import type { ReactNode } from 'react';
import type { ChatThreadDetail } from '@/types/chat';
import { Badge, Button, Icon } from '@/components/ui';
import { formatPhone, hasDisplayName, threadDisplayName } from '@/lib/phone';

export type ThreadRecipientCardProps = {
  thread: ChatThreadDetail;
  /** 캠페인 아래에 붙는 추가 정보(예: 최근 통화). 서버 페이지가 채운다. */
  extra?: ReactNode;
};

const CHANNEL_BADGE: Record<
  ChatThreadDetail['channel'],
  { label: string; kind: 'brand' | 'neutral' }
> = {
  rcs: { label: 'RCS', kind: 'brand' },
  sms: { label: 'SMS', kind: 'neutral' },
  lms: { label: 'LMS', kind: 'neutral' },
  mms: { label: 'MMS', kind: 'neutral' },
  kakao: { label: '카카오', kind: 'neutral' },
};

export function ThreadRecipientCard({ thread, extra }: ThreadRecipientCardProps) {
  const channel = CHANNEL_BADGE[thread.channel];

  return (
    <aside
      aria-label="수신자 정보"
      className="flex h-full flex-col gap-5 overflow-y-auto rounded-lg border border-line bg-surface p-5"
    >
      <div className="flex items-center gap-3">
        <div
          aria-hidden
          className={
            hasDisplayName(thread)
              ? 'flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-brand-soft text-lg font-bold text-brand'
              : 'flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-surface-hover text-ink-dim'
          }
        >
          {hasDisplayName(thread) ? threadDisplayName(thread).charAt(0) : <Icon name="user" size={20} />}
        </div>
        <div className="min-w-0">
          <div className="truncate text-base font-semibold text-ink">
            {threadDisplayName(thread)}
          </div>
          <div className="truncate tabular-nums text-md text-ink-dim">
            {formatPhone(thread.phone)}
          </div>
        </div>
      </div>

      <div>
        <div className="mb-2 text-xs font-semibold text-ink-muted">
          채널 · 세션
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge kind={channel.kind}>{channel.label}</Badge>
          <Badge kind="neutral" icon={<Icon name="clock" size={10} />}>
            세션 24:00:00
          </Badge>
        </div>
        <p className="mt-1.5 text-xs text-ink-dim">
          RCS 과금 단위. 첫 수신 후 24시간 내 무제한 회신.
        </p>
      </div>

      {thread.lastCampaign && (
        <div>
          <div className="mb-2 text-xs font-semibold text-ink-muted">
            최근 캠페인
          </div>
          <div className="flex items-center gap-2 rounded border border-line bg-gray-1 px-3 py-2 text-sm">
            <Icon name="zap" size={12} />
            <span className="truncate">{thread.lastCampaign}</span>
          </div>
        </div>
      )}

      {extra}

      <div>
        <div className="mb-2 text-xs font-semibold text-ink-muted">
          액션
        </div>
        <div className="flex flex-col gap-1.5">
          <Button variant="secondary" size="sm" icon={<Icon name="check" size={12} />} full>
            읽음 표시
          </Button>
          <Button variant="ghost" size="sm" icon={<Icon name="user" size={12} />} full>
            담당자 지정
          </Button>
          <Button variant="ghost" size="sm" icon={<Icon name="eyeOff" size={12} />} full>
            음소거
          </Button>
        </div>
      </div>
    </aside>
  );
}
