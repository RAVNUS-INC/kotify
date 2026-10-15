/** PBX 화면 표시용 순수 함수 — 서버·브라우저 렌더 결과가 같도록 시간대·현재 시각을 쓰지 않는다. */
import type { CallDirection, CallRecord, FaxStatus } from '@/types/pbx';

export const FAX_STATUS_LABEL: Record<FaxStatus, string> = {
  QUEUED: '준비 중',
  SUBMITTED: '보내는 중',
  SENT: '전송 완료',
  FAILED: '실패',
  UNKNOWN: '확인 필요',
};

export const FAX_STATUS_KIND: Record<FaxStatus, 'success' | 'danger' | 'warning' | 'neutral' | 'info'> = {
  QUEUED: 'neutral',
  SUBMITTED: 'info',
  SENT: 'success',
  FAILED: 'danger',
  UNKNOWN: 'warning',
};

/** 결과를 기다리는 작업이 있으면 화면을 주기적으로 새로 고친다. */
export function hasOpenFax(jobs: ReadonlyArray<{ status: FaxStatus }>): boolean {
  return jobs.some((j) => j.status === 'QUEUED' || j.status === 'SUBMITTED');
}

export const DIRECTION_LABEL: Record<CallDirection, string> = {
  in: '수신',
  out: '발신',
  internal: '내선',
  transit: '경유',
  unknown: '—',
};

/** 고객 쪽 번호 — 수신은 건 사람, 발신은 받은 사람. */
export function counterpart(call: Pick<CallRecord, 'direction' | 'from' | 'to'>): string {
  return call.direction === 'out' ? call.to : call.from;
}

/** 통화 시간 `m:ss` (1시간 이상은 `h:mm:ss`). */
export function formatDuration(totalSec: number): string {
  const sec = Math.max(0, Math.floor(totalSec));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const ss = String(s).padStart(2, '0');
  return h > 0 ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
}

/** `2026-10-15T12:34:56+09:00` → `2026-10-15 12:34` (서버가 KST 로 내려 준다). */
export function formatCallTime(iso: string): string {
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(iso);
  return m ? `${m[1]} ${m[2]}` : '';
}

const DISPOSITION_LABEL: Record<string, string> = {
  ANSWERED: '통화',
  'NO ANSWER': '부재',
  // 상대가 통화 중이라 연결되지 않음 — '통화'(연결됨)와 헷갈리지 않게
  BUSY: '상대 통화 중',
  FAILED: '실패',
  CONGESTION: '회선 혼잡',
  'ANSWERED ELSEWHERE': '다른 곳에서 받음',
};

export function dispositionLabel(raw: string): string {
  return DISPOSITION_LABEL[raw.trim().toUpperCase()] ?? (raw || '—');
}

/** 받는 팩스 번호 — 숫자 9~11자리, 0 으로 시작(국내 번호). 서버도 같은 규칙으로 검사한다. */
export function isValidFaxNumber(raw: string): boolean {
  let digits = raw.replace(/\D/g, '');
  if (digits.startsWith('82') && digits.length >= 11) digits = `0${digits.slice(2)}`;
  return /^0\d{8,10}$/.test(digits);
}

export const MAX_FAX_PDF_BYTES = 10 * 1024 * 1024;

/**
 * UTC ISO → `YYYY-MM-DD HH:MM` (KST). 한국은 서머타임이 없어 +9시간 고정 계산이라
 * 브라우저 시간대와 무관하게 서버 렌더와 같다. 해석 못 하면 빈 문자열.
 */
export function fmtKstDateTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) return '';
  const d = new Date(ms + 9 * 60 * 60 * 1000);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(
    d.getUTCHours(),
  )}:${pad(d.getUTCMinutes())}`;
}

/** 받은 팩스 상태 문구 — 수신 실패, PDF 가져오기 대기·실패를 구분한다. */
export function inboxStatusLabel(item: {
  status: 'RECEIVED' | 'FAILED';
  fetchStatus: 'PENDING' | 'FETCHED' | 'FETCH_FAILED' | 'NONE';
}): { label: string; kind: 'success' | 'danger' | 'warning' | 'neutral' } {
  if (item.status === 'FAILED') return { label: '수신 실패', kind: 'danger' };
  if (item.fetchStatus === 'FETCHED') return { label: '받음', kind: 'success' };
  if (item.fetchStatus === 'PENDING') return { label: 'PDF 가져오는 중', kind: 'neutral' };
  if (item.fetchStatus === 'FETCH_FAILED') return { label: 'PDF 못 가져옴', kind: 'warning' };
  return { label: 'PBX 에서 삭제됨', kind: 'neutral' };
}
