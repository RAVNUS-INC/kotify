import Link from 'next/link';
import type { Route } from 'next';
import type { SearchResult, SearchSection } from '@/types/search';
import { Badge, EmptyState, Icon } from '@/components/ui';
import { StatusBadge } from '@/components/campaigns';
import type { CampaignStatus } from '@/types/campaign';
import { AuditActionBadge } from '@/components/audit';
import { HighlightText } from './HighlightText';

export type SearchResultsViewProps = {
  q: string;
  result: SearchResult;
  section: SearchSection;
};

export function SearchResultsView({ q, result, section }: SearchResultsViewProps) {
  if (result.counts.total === 0) {
    return (
      <div className="rounded-lg border border-line bg-surface">
        <EmptyState
          icon="search"
          title="검색 결과 없음"
          description={q ? `'${q}'에 대한 결과가 없습니다.` : '검색어를 입력하세요.'}
          size="md"
        />
      </div>
    );
  }

  const show = (s: SearchSection) => section === 'all' || section === s;

  return (
    <div className="flex flex-col gap-6">
      {show('contacts') && result.contacts.length > 0 && (
        <Section title="주소록" count={result.counts.contacts}>
          <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {result.contacts.map((c) => (
              <li key={c.id}>
                <Link
                  href={`/contacts?selected=${encodeURIComponent(c.id)}` as Route}
                  className="flex items-center gap-3 rounded border border-line bg-surface p-3 transition-colors duration-fast ease-out hover:border-brand/40 hover:bg-brand-soft/20"
                >
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gray-3 font-mono text-[11px] text-gray-9">
                    {c.name.charAt(0)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-ink">
                      <HighlightText text={c.name} q={q} />
                    </div>
                    <div className="truncate font-mono text-[11.5px] text-ink-dim">
                      <HighlightText text={c.phone} q={q} />
                    </div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {show('threads') && result.threads.length > 0 && (
        <Section title="대화" count={result.counts.threads}>
          <ul className="flex flex-col divide-y divide-line rounded-lg border border-line bg-surface">
            {result.threads.map((t) => (
              <li key={t.id}>
                <Link
                  href={`/chat/${encodeURIComponent(t.id)}` as Route}
                  className="flex items-start gap-3 px-4 py-3 transition-colors duration-fast ease-out hover:bg-gray-1"
                >
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gray-3 font-mono text-[11px] text-gray-9">
                    {t.name.charAt(0)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-sm font-medium text-ink">
                        {t.name}
                      </span>
                      <span className="shrink-0 font-mono text-[11px] text-ink-dim">
                        {t.time}
                      </span>
                    </div>
                    {t.campaignName && (
                      <div className="font-mono text-[10.5px] text-ink-dim">
                        {t.campaignName}
                      </div>
                    )}
                    <div className="mt-0.5 truncate text-[12.5px] text-ink-muted">
                      <HighlightText text={t.snippet} q={q} />
                    </div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {show('campaigns') && result.campaigns.length > 0 && (
        <Section title="캠페인" count={result.counts.campaigns}>
          <ul className="flex flex-col divide-y divide-line rounded-lg border border-line bg-surface">
            {result.campaigns.map((c) => (
              <li key={c.id}>
                <Link
                  href={`/campaigns/${encodeURIComponent(c.id)}` as Route}
                  className="flex items-center gap-3 px-4 py-3 transition-colors duration-fast ease-out hover:bg-gray-1"
                >
                  <Icon name="zap" size={14} className="shrink-0 text-ink-dim" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-ink">
                      <HighlightText text={c.name} q={q} />
                    </div>
                    <div className="font-mono text-[11px] text-ink-dim">
                      {c.createdAt}
                    </div>
                  </div>
                  <StatusBadge status={c.status as CampaignStatus} />
                </Link>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {show('audit') && result.auditLogs.length > 0 && (
        <Section title="감사 로그" count={result.counts.auditLogs}>
          <ul className="flex flex-col divide-y divide-line rounded-lg border border-line bg-surface">
            {result.auditLogs.map((a) => (
              <li key={a.id}>
                <Link
                  href={`/audit?q=${encodeURIComponent(q)}` as Route}
                  className="flex items-center gap-3 px-4 py-3 transition-colors duration-fast ease-out hover:bg-gray-1"
                >
                  <span className="shrink-0 font-mono text-[11px] text-ink-dim">
                    {a.time}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium text-ink">
                        <HighlightText text={a.actor} q={q} />
                      </span>
                      <AuditActionBadge action={a.action} />
                    </div>
                    <div className="truncate text-[12.5px] text-ink-muted">
                      <HighlightText text={a.target} q={q} />
                    </div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}

function Section({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <section>
      <header className="mb-2 flex items-baseline gap-2">
        <h2 className="font-mono text-[10.5px] font-medium uppercase tracking-[0.08em] text-ink-dim">
          {title}
        </h2>
        <Badge kind="neutral">{count}</Badge>
      </header>
      {children}
    </section>
  );
}
