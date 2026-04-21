import { PageHeader } from '@/components/shell';
import { NumbersTable } from '@/components/numbers';
import { Button, Icon, LinkSegmented } from '@/components/ui';
import { fetchNumbers } from '@/lib/numbers';
import type { NumberStatus } from '@/types/number';

type FilterValue = 'all' | NumberStatus;

const VALID: ReadonlyArray<FilterValue> = [
  'all',
  'approved',
  'pending',
  'rejected',
  'expired',
];

function normalize(raw: string | string[] | undefined): FilterValue {
  if (typeof raw === 'string' && (VALID as ReadonlyArray<string>).includes(raw)) {
    return raw as FilterValue;
  }
  return 'all';
}

type PageProps = {
  searchParams?: { status?: string };
};

export default async function NumbersPage({ searchParams }: PageProps) {
  const status = normalize(searchParams?.status);
  // PageHeader sub의 집계는 필터 무관 전체값이 정확.
  // 필터 적용 시 해당 탭만 들어있어서 "승인 N / 대기 0" 식 오표시 발생을 방지.
  const [numbers, allNumbers] = await Promise.all([
    fetchNumbers({ status }),
    status === 'all' ? Promise.resolve(null) : fetchNumbers({}),
  ]);
  const totals = allNumbers ?? numbers;
  const approvedCount = totals.filter((n) => n.status === 'approved').length;
  const pendingCount = totals.filter((n) => n.status === 'pending').length;
  const totalCount = totals.length;

  return (
    <div className="k-page">
      <PageHeader
        title="발신번호"
        sub={`총 ${totalCount}개 · 승인 ${approvedCount} · 대기 ${pendingCount}`}
        actions={
          <Button variant="primary" size="sm" icon={<Icon name="plus" size={12} />}>
            번호 등록
          </Button>
        }
      />

      <div className="mb-4">
        <LinkSegmented
          aria-label="상태 필터"
          active={status}
          basePath="/numbers"
          param="status"
          options={[
            { value: 'all', label: '전체' },
            { value: 'approved', label: '승인' },
            { value: 'pending', label: '대기' },
            { value: 'rejected', label: '반려' },
            { value: 'expired', label: '만료' },
          ]}
        />
      </div>

      <NumbersTable numbers={numbers} />
    </div>
  );
}
