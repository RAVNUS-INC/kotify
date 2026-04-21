import { PageHeader } from '@/components/shell';
import { SearchResultsView } from '@/components/search';
import { LinkSegmented, ListSearchInput } from '@/components/ui';
import { fetchSearch } from '@/lib/search';
import type { SearchSection } from '@/types/search';

const VALID: ReadonlyArray<SearchSection> = [
  'all',
  'contacts',
  'threads',
  'campaigns',
  'audit',
];

function normalize(raw: string | string[] | undefined): SearchSection {
  if (typeof raw === 'string' && (VALID as ReadonlyArray<string>).includes(raw)) {
    return raw as SearchSection;
  }
  return 'all';
}

type PageProps = {
  searchParams?: {
    q?: string;
    section?: string;
  };
};

export default async function SearchPage({ searchParams }: PageProps) {
  const q = (searchParams?.q ?? '').trim();
  const section = normalize(searchParams?.section);
  const result = q ? await fetchSearch(q) : null;

  return (
    <div className="k-page">
      <PageHeader
        title="검색"
        sub={
          q
            ? `'${q}' 검색 결과 · 총 ${result?.counts.total ?? 0}건`
            : '검색어를 입력하세요'
        }
      />

      <div className="mb-4 flex flex-col gap-3">
        <div className="max-w-xl">
          <ListSearchInput placeholder="통합 검색 (주소록·대화·캠페인·감사)" />
        </div>
        {q && result && (
          <LinkSegmented
            aria-label="섹션 필터"
            active={section}
            basePath="/search"
            param="section"
            extraParams={{ q }}
            options={[
              { value: 'all', label: `전체 · ${result.counts.total}` },
              { value: 'contacts', label: `주소록 · ${result.counts.contacts}` },
              { value: 'threads', label: `대화 · ${result.counts.threads}` },
              { value: 'campaigns', label: `캠페인 · ${result.counts.campaigns}` },
              { value: 'audit', label: `감사 · ${result.counts.auditLogs}` },
            ]}
          />
        )}
      </div>

      {result && <SearchResultsView q={q} result={result} section={section} />}

      {!q && (
        <div className="rounded-lg border border-dashed border-line bg-gray-1 p-10 text-center text-sm text-ink-muted">
          <p>위 검색창에 입력하거나</p>
          <p className="mt-1">상단 Topbar의 ⌘K 버튼으로 커맨드 팔레트를 여세요.</p>
        </div>
      )}
    </div>
  );
}
