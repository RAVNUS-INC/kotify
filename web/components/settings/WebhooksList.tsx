'use client';

import { useState } from 'react';
import type { Webhook, WebhookListMeta } from '@/types/settings';
import { Badge, Button, EmptyState, Icon } from '@/components/ui';

export type WebhooksListProps = {
  webhooks: ReadonlyArray<Webhook>;
  meta?: WebhookListMeta;
};

const STATUS_LABEL: Record<Webhook['status'], string> = {
  ok: '정상 수신 중',
  stale: '24시간 이상 미수신',
  never_received: '한 번도 수신 못 함',
  not_configured: '설정 미완료',
};

const STATUS_TONE: Record<
  Webhook['status'],
  'brand' | 'neutral' | 'warning' | 'danger'
> = {
  ok: 'brand',
  stale: 'warning',
  never_received: 'danger',
  not_configured: 'neutral',
};

function CopyButton({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);
  const onCopy = async () => {
    if (!url) return;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard API 실패 시 조용히 무시 (브라우저 권한 등)
    }
  };
  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      icon={<Icon name={copied ? 'check' : 'copy'} size={12} />}
      onClick={onCopy}
      disabled={!url}
      aria-label="URL 복사"
    >
      {copied ? '복사됨' : '복사'}
    </Button>
  );
}

export function WebhooksList({ webhooks, meta }: WebhooksListProps) {
  if (webhooks.length === 0) {
    return (
      <EmptyState
        icon="zap"
        title="웹훅 없음"
        description="msghub 인바운드 웹훅 설정이 비어있습니다."
        size="sm"
      />
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {meta?.hint ? (
        <div
          role="alert"
          className="rounded-lg border border-warning/30 bg-warning/5 p-3 text-[12.5px] text-warning"
        >
          ⚠ {meta.hint}
        </div>
      ) : null}

      <ul className="flex flex-col divide-y divide-line">
        {webhooks.map((w) => {
          const tone = STATUS_TONE[w.status];
          return (
            <li key={w.id} className="flex flex-col gap-2 py-3">
              <div className="flex items-baseline justify-between gap-2">
                <div>
                  <div className="text-sm font-semibold text-ink">{w.name}</div>
                  <div className="mt-0.5 text-[12px] text-ink-muted">
                    {w.description}
                  </div>
                </div>
                <Badge kind={tone}>{STATUS_LABEL[w.status]}</Badge>
              </div>

              <div className="flex items-center gap-2 rounded border border-line bg-gray-1 px-2.5 py-1.5">
                <span
                  className="min-w-0 flex-1 truncate font-mono text-[12px] text-ink"
                  title={w.url || '설정 미완료 — URL 없음'}
                >
                  {w.url || '(URL 없음 — 토큰/공개URL 설정 필요)'}
                </span>
                <CopyButton url={w.url} />
              </div>

              {w.lastReceivedAt ? (
                <div className="font-mono text-[11px] text-ink-dim">
                  마지막 수신 · {w.lastReceivedAt}
                </div>
              ) : w.configured ? (
                <div className="font-mono text-[11px] text-danger">
                  여태 한 번도 수신 못 함 — msghub 콘솔에 이 URL 을 등록했는지
                  확인하세요.
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>

      {meta?.outbound?.featurePending ? (
        <div className="rounded border border-dashed border-line bg-gray-1 p-3 text-[12.5px] text-ink-muted">
          <div className="font-semibold text-ink">아웃바운드 웹훅 구독</div>
          <div className="mt-1">{meta.outbound.note}</div>
        </div>
      ) : null}
    </div>
  );
}
