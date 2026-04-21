import { apiFetch, type ApiEnvelope } from './api';
import type { SearchResult } from '@/types/search';

/**
 * Server-side fetch. `/search?q=`로 /search 페이지에서 호출.
 */
export async function fetchSearch(q: string): Promise<SearchResult> {
  return apiFetch<SearchResult>(`/search?q=${encodeURIComponent(q)}`);
}

/**
 * Client-side (Command Palette). Next rewrite `/api/search` 경유.
 */
export async function searchClient(q: string): Promise<SearchResult> {
  const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`, {
    cache: 'no-store',
  });
  const body = (await res.json()) as ApiEnvelope<SearchResult>;
  if (!res.ok || body.error) {
    throw new Error(body.error?.message ?? `HTTP ${res.status}`);
  }
  if (!body.data) throw new Error('API 응답에 data가 없습니다');
  return body.data;
}
