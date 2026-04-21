import { apiFetch } from './api';
import type { AuditEntry } from '@/types/audit';

export type FetchAuditParams = {
  q?: string;
  action?: string;
};

export async function fetchAudit(
  params: FetchAuditParams = {},
): Promise<AuditEntry[]> {
  const qs = new URLSearchParams();
  if (params.q) qs.set('q', params.q);
  if (params.action && params.action !== 'all') qs.set('action', params.action);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<AuditEntry[]>(`/audit${suffix}`);
}

/**
 * CSV export 다운로드 링크. 브라우저가 Content-Disposition attachment로
 * 파일 저장. 서버에서 현재 필터와 동일한 파라미터로 CSV 생성.
 */
export function buildAuditCsvHref(params: FetchAuditParams = {}): string {
  const qs = new URLSearchParams();
  if (params.q) qs.set('q', params.q);
  if (params.action && params.action !== 'all') qs.set('action', params.action);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return `/api/audit/export.csv${suffix}`;
}
