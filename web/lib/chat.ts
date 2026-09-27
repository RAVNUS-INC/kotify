import { ApiError, apiFetch, apiFetchEnvelope } from './api';
import { apiSend } from './csrf-client';
import type {
  ChatMessage,
  ChatThread,
  ChatThreadDetail,
  ChatThreadPage,
  ChatThreadPageMeta,
  SendChannel,
} from '@/types/chat';

export type FetchThreadsParams = {
  q?: string;
  unread?: boolean;
  limit?: number;
  offset?: number;
};

function threadsPath(params: FetchThreadsParams): string {
  const qs = new URLSearchParams();
  if (params.q) qs.set('q', params.q);
  if (params.unread) qs.set('unread', 'true');
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  if (params.offset !== undefined) qs.set('offset', String(params.offset));
  return `/threads${qs.size ? `?${qs.toString()}` : ''}`;
}

export async function fetchThreads(
  params: FetchThreadsParams = {},
): Promise<ChatThread[]> {
  return apiFetch<ChatThread[]>(threadsPath(params));
}

export async function fetchThreadPage(params: FetchThreadsParams = {}): Promise<ChatThreadPage> {
  const response = await apiFetchEnvelope<ChatThread[], ChatThreadPageMeta>(threadsPath(params));
  if (!response.meta) throw new ApiError(200, 'missing_meta', '대화 목록의 페이지 정보가 없습니다');
  return { data: response.data, meta: response.meta };
}

export async function fetchThread(id: string): Promise<ChatThreadDetail> {
  return apiFetch<ChatThreadDetail>(`/threads/${encodeURIComponent(id)}`);
}

/**
 * 전달 상태 이벤트로 갱신할 발신 메시지 id. 실패에도 요청 타임아웃처럼 실제 접수 여부를
 * 모르는 건이 섞여 있어, 늦은 리포트·재조정으로 대기/전달 상태가 될 수 있다.
 * 현재 API는 확정 실패와 구분하지 않으므로 대기·실패를 함께 감시한다. 이벤트 없이 폴링하지 않는다.
 */
export function getDeliveryRefreshIds(
  thread: ChatThreadDetail | null | undefined,
): string[] {
  if (!thread) return [];
  return thread.messages
    .filter((m) => m.side === 'us' && (m.status === 'pending' || m.status === 'failed'))
    .map((m) => m.id);
}

/**
 * 날짜가 바뀌는 첫 메시지마다 그 앞에 둘 구분선 날짜를 붙인다(대화의 첫 메시지 포함).
 * 날짜를 모르는 메시지(빈 문자열)는 구분선을 만들지 않고 비교 기준 날짜도 바꾸지 않는다.
 */
export function withDateDividers(
  messages: readonly ChatMessage[],
): Array<{ message: ChatMessage; dividerDate: string | null }> {
  let previous = '';
  return messages.map((message) => {
    const { date } = message;
    const dividerDate = date && date !== previous ? date : null;
    if (date) previous = date;
    return { message, dividerDate };
  });
}

const WEEKDAYS = ['일', '월', '화', '수', '목', '금', '토'] as const;
const DAY_MS = 86_400_000;

/**
 * 서버가 KST 로 자른 "YYYY-MM-DD" → 연·월·일, 요일, 1970-01-01 부터 센 날 수. 형식에 맞지
 * 않거나 달력에 없는 날짜는 null. Date.UTC 로만 계산해 브라우저 시간대와 무관하다.
 */
function parseDate(date: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const utc = new Date(Date.UTC(year, month - 1, day));
  if (utc.getUTCMonth() !== month - 1 || utc.getUTCDate() !== day) return null;
  return { year, month, day, weekday: utc.getUTCDay(), dayNumber: utc.getTime() / DAY_MS };
}

/**
 * 구분선 문구 — "2026-09-27" → "2026년 9월 27일 일요일"(카카오톡처럼 항상 절대 날짜).
 * 서버가 KST 로 자른 날짜만 보고 브라우저 시간대·현재 시각은 쓰지 않는다. 그래서 서버 렌더와
 * 브라우저 렌더가 같은 문구를 내고, "오늘·어제" 같은 상대 표현이 없어 자정을 넘겨 열어 둔
 * 화면도 틀린 날짜를 말하지 않는다. 형식에 맞지 않거나 달력에 없는 날짜는 원문 그대로.
 */
export function formatChatDate(date: string): string {
  const parsed = parseDate(date);
  if (!parsed) return date;
  const { year, month, day, weekday } = parsed;
  return `${year}년 ${month}월 ${day}일 ${WEEKDAYS[weekday]}요일`;
}

/**
 * 대화 목록·대시보드 최근 대화의 마지막 메시지 시각(카카오톡 목록 방식) — 오늘 "14:05",
 * 어제 "어제", 올해 "9월 25일", 그 이전 "2025. 9. 25.". today 는 서버가 응답 시각의 KST 날짜로
 * 내려 준 값이라 브라우저 시계·시간대를 쓰지 않고, 서버 렌더와 브라우저 렌더가 같다. 대신 응답
 * 시각 기준이어서 자정을 넘겨 열어 둔 화면은 다시 불러오기 전까지 전날 기준 문구로 남는다.
 * 날짜나 기준일을 모르면 이전처럼 시각만 보인다. 시계 오차로 오늘보다 늦은 날짜는 날짜로 보인다.
 */
export function formatThreadTime(
  { time, date }: Pick<ChatThread, 'time' | 'date'>,
  today: string,
): string {
  const last = parseDate(date);
  const base = parseDate(today);
  if (!last || !base || last.dayNumber === base.dayNumber) return time;
  if (last.dayNumber === base.dayNumber - 1) return '어제';
  if (last.year === base.year) return `${last.month}월 ${last.day}일`;
  return `${last.year}. ${last.month}. ${last.day}.`;
}

/**
 * Client-side fetch. Next rewrite(/api/* → FastAPI)를 경유하므로 상대 경로.
 */
export async function sendMessageClient(
  id: string,
  text: string,
  sendChannel: SendChannel,
): Promise<ChatMessage> {
  const res = await apiSend(
    `/api/threads/${encodeURIComponent(id)}/messages`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text, sendChannel }),
    },
  );
  const body = (await res.json()) as {
    data?: { message: ChatMessage };
    error?: { code: string; message: string; fields?: Record<string, string> };
  };
  if (!res.ok || body.error) {
    throw new ApiError(
      res.status, body.error?.code ?? 'http_error',
      body.error?.message ?? `HTTP ${res.status}`, body.error?.fields,
    );
  }
  if (!body.data) throw new Error('API 응답에 data가 없습니다');
  return body.data.message;
}

export async function markReadClient(id: string, lastReadMessageId: number): Promise<void> {
  const res = await apiSend(`/api/threads/${encodeURIComponent(id)}/read`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ lastReadMessageId }),
  });
  if (!res.ok) throw new Error(`읽음 처리 실패 (HTTP ${res.status})`);
}
