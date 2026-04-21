import { apiFetch } from './api';
import type { ReportData } from '@/types/report';

export type FetchReportsParams = {
  from?: string;
  to?: string;
  campaignId?: string;
};

export async function fetchReports(
  params: FetchReportsParams = {},
): Promise<ReportData> {
  const qs = new URLSearchParams();
  if (params.from) qs.set('from', params.from);
  if (params.to) qs.set('to', params.to);
  if (params.campaignId) qs.set('campaignId', params.campaignId);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiFetch<ReportData>(`/reports${suffix}`);
}

/**
 * CSV export 다운로드 href. 브라우저 네이티브 <a download>로 저장.
 */
export function buildReportsCsvHref(params: FetchReportsParams = {}): string {
  const qs = new URLSearchParams();
  if (params.from) qs.set('from', params.from);
  if (params.to) qs.set('to', params.to);
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return `/api/reports/export.csv${suffix}`;
}
