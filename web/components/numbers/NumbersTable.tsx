import type { SenderNumber } from '@/types/number';
import { EmptyState, Pill } from '@/components/ui';
import { Progress } from '@/components/motion';
import { NumberStatusBadge } from './NumberStatusBadge';

export type NumbersTableProps = {
  numbers: ReadonlyArray<SenderNumber>;
};

const KIND_LABEL = {
  rep: '대표번호',
  mobile: '휴대전화',
} as const;

const SUPPORT_LABEL = {
  rcs: 'RCS',
  sms: 'SMS',
  lms: 'LMS',
  mms: 'MMS',
} as const;

export function NumbersTable({ numbers }: NumbersTableProps) {
  if (numbers.length === 0) {
    return (
      <div className="rounded-lg border border-line bg-surface">
        <EmptyState
          icon="phone"
          title="발신번호 없음"
          description="등록된 발신번호가 없습니다."
          size="md"
        />
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface">
      <div className="overflow-x-auto">
        <table className="k-tbl">
          <thead>
            <tr>
              <th>번호</th>
              <th>종류</th>
              <th>지원 채널</th>
              <th>브랜드</th>
              <th>상태</th>
              <th className="num">일 사용량</th>
            </tr>
          </thead>
          <tbody>
            {numbers.map((n) => {
              const usagePct =
                n.dailyLimit && n.dailyLimit > 0
                  ? (n.dailyUsage / n.dailyLimit) * 100
                  : 0;
              const usageWarn = usagePct > 90;
              return (
                <tr key={n.id}>
                  <td className="mono text-ink">{n.number}</td>
                  <td>{KIND_LABEL[n.kind]}</td>
                  <td>
                    <div className="flex flex-wrap gap-1">
                      {n.supports.map((s) => (
                        <Pill
                          key={s}
                          tone={s === 'rcs' ? 'brand' : 'neutral'}
                        >
                          {SUPPORT_LABEL[s]}
                        </Pill>
                      ))}
                    </div>
                  </td>
                  <td className="truncate text-ink-muted">{n.brand}</td>
                  <td>
                    <NumberStatusBadge
                      status={n.status}
                      reason={n.failureReason}
                    />
                  </td>
                  <td className="num">
                    {n.status === 'approved' && n.dailyLimit ? (
                      <div className="flex flex-col items-end gap-1">
                        <div className="font-mono text-[12.5px] tabular-nums">
                          {n.dailyUsage.toLocaleString('ko-KR')} /{' '}
                          {n.dailyLimit.toLocaleString('ko-KR')}
                        </div>
                        <div className="w-24">
                          <Progress
                            value={usagePct}
                            max={100}
                            color={
                              usageWarn ? 'var(--danger)' : 'var(--brand)'
                            }
                            height={3}
                            delay={0}
                            duration={600}
                            ariaLabel="일 사용량"
                          />
                        </div>
                      </div>
                    ) : (
                      <span className="text-ink-dim">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
