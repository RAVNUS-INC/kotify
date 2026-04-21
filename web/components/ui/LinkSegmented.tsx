import Link from 'next/link';
import type { Route } from 'next';
import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

export type LinkSegmentedOption = {
  value: string;
  label: ReactNode;
  count?: number;
};

export type LinkSegmentedProps = {
  active: string;
  options: ReadonlyArray<LinkSegmentedOption>;
  /** 쿼리 파라미터 이름 (기본 'filter') */
  param?: string;
  /** 현재 경로 (예: '/campaigns') */
  basePath: string;
  /** 추가로 보존할 쿼리 파라미터 */
  extraParams?: Record<string, string | undefined>;
  'aria-label'?: string;
};

export function LinkSegmented({
  active,
  options,
  param = 'filter',
  basePath,
  extraParams,
  'aria-label': ariaLabel,
}: LinkSegmentedProps) {
  const buildHref = (value: string): Route => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(extraParams ?? {})) {
      if (v) qs.set(k, v);
    }
    if (value !== 'all') qs.set(param, value);
    const str = qs.toString();
    return (str ? `${basePath}?${str}` : basePath) as Route;
  };

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className="k-segctrl"
    >
      {options.map((o) => {
        const isActive = active === o.value;
        return (
          <Link
            key={o.value}
            role="tab"
            aria-selected={isActive}
            href={buildHref(o.value)}
            className={cn(isActive && 'on')}
          >
            <span>{o.label}</span>
            {o.count != null && (
              <span className="ml-1 font-mono text-[10.5px] opacity-70">
                {o.count}
              </span>
            )}
          </Link>
        );
      })}
    </div>
  );
}
