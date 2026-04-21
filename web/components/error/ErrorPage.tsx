import { Fragment, type ReactNode } from 'react';
import { Icon, type IconName } from '@/components/ui';
import { PulseDot } from '@/components/motion';
import { cn } from '@/lib/cn';

export type ErrorPageTone = 'neutral' | 'danger' | 'warning' | 'brand';

export type ErrorPageDiagnostic = {
  label: string;
  value: string;
};

export type ErrorPageProps = {
  /** "404" "500" "OFFLINE" 등 */
  code: string;
  icon: IconName;
  tone?: ErrorPageTone;
  title: string;
  description?: ReactNode;
  diagnostics?: ReadonlyArray<ErrorPageDiagnostic>;
  /** offline 전용 — 아이콘 오른쪽 상단에 PulseDot 표시 */
  pulseDot?: boolean;
  actions?: ReactNode;
};

const TONE_MAP: Record<ErrorPageTone, string> = {
  neutral: 'bg-gray-1 text-ink-muted',
  danger: 'bg-danger-bg text-danger',
  warning: 'bg-warning-bg text-warning',
  brand: 'bg-brand-soft text-brand',
};

export function ErrorPage({
  code,
  icon,
  tone = 'neutral',
  title,
  description,
  diagnostics,
  pulseDot = false,
  actions,
}: ErrorPageProps) {
  return (
    <div className="flex min-h-[70vh] items-center justify-center p-6">
      <div
        role="alert"
        aria-live="assertive"
        className="flex max-w-md flex-col items-center gap-4 text-center"
      >
        <div className="relative">
          <div
            className={cn(
              'flex h-20 w-20 items-center justify-center rounded-full',
              TONE_MAP[tone],
            )}
          >
            <Icon name={icon} size={32} strokeWidth={1.6} aria-hidden />
          </div>
          {pulseDot && (
            <span className="absolute right-0 top-0 -translate-y-1/4 translate-x-1/4">
              <PulseDot size={10} color="var(--brand)" title="실시간 연결 대기" />
            </span>
          )}
        </div>

        <div className="font-mono text-[11px] font-medium uppercase tracking-[0.12em] text-ink-dim">
          Error {code}
        </div>

        <h1 className="m-0 text-2xl font-semibold tracking-tight text-ink">
          {title}
        </h1>

        {description && (
          <div className="text-sm leading-relaxed text-ink-muted">
            {description}
          </div>
        )}

        {diagnostics && diagnostics.length > 0 && (
          <div className="w-full rounded border border-line bg-gray-1 p-3 text-left">
            <div className="mb-1.5 font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-ink-dim">
              진단 정보
            </div>
            <dl className="grid grid-cols-[88px_1fr] gap-x-3 gap-y-1 font-mono text-[11.5px]">
              {diagnostics.map((d) => (
                <Fragment key={d.label}>
                  <dt className="text-ink-dim">{d.label}</dt>
                  <dd className="min-w-0 truncate text-ink">{d.value}</dd>
                </Fragment>
              ))}
            </dl>
          </div>
        )}

        {actions && (
          <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
            {actions}
          </div>
        )}
      </div>
    </div>
  );
}
