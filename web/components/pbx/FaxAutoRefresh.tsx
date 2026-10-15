'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

/** 결과를 기다리는 팩스가 있을 때만 15초마다 서버 컴포넌트를 다시 불러온다 (UI 없음). */
export function FaxAutoRefresh({ active, intervalMs = 15_000 }: { active: boolean; intervalMs?: number }) {
  const router = useRouter();
  useEffect(() => {
    if (!active) return undefined;
    const timer = window.setInterval(() => {
      if (document.visibilityState === 'visible') router.refresh();
    }, intervalMs);
    return () => window.clearInterval(timer);
  }, [active, intervalMs, router]);
  return null;
}
