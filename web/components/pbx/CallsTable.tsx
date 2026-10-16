import { EmptyState, Pill } from '@/components/ui';
import { formatDateTime } from '@/lib/datetime';
import { formatPhone } from '@/lib/phone';
import {
  counterpart,
  DIRECTION_LABEL,
  dispositionLabel,
  formatCallTime,
  formatDuration,
} from '@/lib/pbx-format';
import type { CallRecord } from '@/types/pbx';
import { RecordingPlayer } from './RecordingPlayer';

export function CallsTable({ calls }: { calls: ReadonlyArray<CallRecord> }) {
  if (calls.length === 0) {
    return (
      <div className="rounded-lg border border-line bg-surface">
        <EmptyState icon="phone" title="통화 기록 없음" description="조건에 맞는 통화가 없습니다." size="md" />
      </div>
    );
  }
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-surface">
      <div className="overflow-x-auto">
        <table className="k-tbl">
          <thead>
            <tr>
              <th>시각</th>
              <th>구분</th>
              <th>상대 번호</th>
              <th>내선·번호</th>
              <th>결과</th>
              <th className="num">통화 시간</th>
              <th className="num">녹음</th>
            </tr>
          </thead>
          <tbody>
            {calls.map((call) => {
              const other = counterpart(call);
              const ours = call.direction === 'out' ? call.from : call.to;
              const time = formatDateTime(formatCallTime(call.at));
              return (
                <tr key={call.id}>
                  <td className="whitespace-nowrap tabular-nums">{time || '—'}</td>
                  <td>
                    <Pill tone={call.direction === 'in' ? 'brand' : 'neutral'}>
                      {DIRECTION_LABEL[call.direction]}
                    </Pill>
                  </td>
                  <td>
                    {call.name ? (
                      <div className="flex flex-col">
                        <span className="truncate text-ink">{call.name}</span>
                        <span className="tabular-nums text-sm text-ink-muted">{formatPhone(other) || other}</span>
                      </div>
                    ) : (
                      <span className="tabular-nums text-ink">{formatPhone(other) || other || '—'}</span>
                    )}
                  </td>
                  <td className="tabular-nums text-ink-muted">{formatPhone(ours) || ours || '—'}</td>
                  <td className={call.disposition.trim().toUpperCase() === 'ANSWERED' ? 'text-ink' : 'text-ink-muted'}>
                    {dispositionLabel(call.disposition)}
                  </td>
                  <td className="num tabular-nums">{formatDuration(call.billSec)}</td>
                  <td className="num">
                    {call.recordingToken ? (
                      <RecordingPlayer call={call} />
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
