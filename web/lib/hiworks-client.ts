import { apiSend } from './csrf-client';

/** 하이웍스 CID 조회 결과 한 건. */
export type HiworksContact = {
  name: string;
  grade?: string | null;
  company?: string | null;
  /** "홍길동 부장 (레이븐어스)" 형태 표시명. */
  display: string;
};

/** {정규화번호(숫자만): HiworksContact}. 매칭 없는 번호는 키 없음. */
export type HiworksLookupResult = Record<string, HiworksContact>;

/**
 * 번호 배열 → 하이웍스 주소록 표시명 매핑.
 * 미설정·조회 실패 시 빈 객체(서버가 격리). 호출측은 이름 없으면 번호 그대로.
 */
export async function lookupHiworks(
  phones: string[],
): Promise<HiworksLookupResult> {
  if (phones.length === 0) return {};
  try {
    const res = await apiSend('/api/hiworks/lookup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phones }),
    });
    const body = (await res.json()) as {
      data?: HiworksLookupResult;
      error?: { code: string; message: string };
    };
    if (!res.ok || body.error || !body.data) return {};
    return body.data;
  } catch {
    // 조회 실패는 조용히 무시 — 번호 표시로 fallback.
    return {};
  }
}

/**
 * 하이웍스 MySQL 연결 테스트 (admin). 성공 메시지 또는 throw.
 */
export async function testHiworksConnection(): Promise<{
  ok: true;
  message: string;
}> {
  const res = await apiSend('/api/hiworks/test', { method: 'POST' });
  const body = (await res.json()) as {
    data?: { ok: true; message: string };
    error?: { code: string; message: string };
  };
  if (!res.ok || body.error) {
    throw new Error(body.error?.message ?? `HTTP ${res.status}`);
  }
  if (!body.data) throw new Error('API 응답에 data가 없습니다');
  return body.data;
}

/** 숫자만 추출 (조회 결과 키와 매칭용). */
export function toDigits(raw: string): string {
  return raw.replace(/\D/g, '');
}
