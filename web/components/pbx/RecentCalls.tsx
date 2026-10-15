import Link from 'next/link';
import type { Route } from 'next';
import { Icon } from '@/components/ui';
import { DIRECTION_LABEL, dispositionLabel, formatCallTime, formatDuration } from '@/lib/pbx-format';
import type { RecentCallsResult } from '@/lib/pbx';
import { RecordingPlayer } from './RecordingPlayer';

/**
 * 대화방 오른쪽 카드의 "최근 통화". PBX 를 쓸 수 없으면(미설정·장애·권한) 섹션을
 * 통째로 숨긴다 — 대화방은 통화 기록 없이도 그대로 동작해야 한다.
 */
export function RecentCalls({ phone, result }: { phone: string; result: RecentCallsResult }) {
  if (result.status !== 'ok') return null;
  const href = `/calls?phone=${encodeURIComponent(phone)}` as Route;
  return (
    <section aria-label="최근 통화">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-mono text-[10.5px] uppercase tracking-[0.08em] text-ink-dim">최근 통화</span>
        <Link href={href} className="text-[12px] text-ink-muted hover:text-ink">
          전체 보기
        </Link>
      </div>
      {result.calls.length === 0 ? (
        <p className="text-[12px] text-ink-dim">최근 30일 통화가 없습니다.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {result.calls.map((call) => {
            const time = formatCallTime(call.at);
            return (
              <li key={call.id} className="rounded border border-line bg-gray-1 px-3 py-2 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5">
                    <Icon name="phone" size={11} />
                    {DIRECTION_LABEL[call.direction]} · {dispositionLabel(call.disposition)}
                  </span>
                  <span className="font-mono text-[12px] text-ink-muted">{formatDuration(call.billSec)}</span>
                </div>
                <div className="mt-0.5 flex items-center justify-between gap-2">
                  <span className="font-mono text-[11.5px] text-ink-dim">{time}</span>
                  {call.recordingToken ? (
                    <RecordingPlayer token={call.recordingToken} label={`${time} 통화`} />
                  ) : null}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
