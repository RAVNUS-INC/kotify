import { apiFetch } from './api';
import type { DashboardData } from '@/types/dashboard';

/**
 * 대시보드 데이터 조회. Server Component에서만 호출.
 * Phase 5a: FastAPI mock 데이터. Phase 5b에서 실제 쿼리로 교체.
 */
export async function fetchDashboard(): Promise<DashboardData> {
  return apiFetch<DashboardData>('/dashboard');
}
