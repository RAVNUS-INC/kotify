'use client';

import { useState } from 'react';
import {
  applySystemUpdate,
  checkSystemUpdate,
  fetchCurrentVersion,
  waitForVersion,
  type UpdateCheckResult,
} from '@/lib/settings';
import { Badge, Button, Icon } from '@/components/ui';

type Phase =
  | 'idle'
  | 'checking'
  | 'ready'
  | 'applying'
  | 'restarting'
  | 'done'
  | 'error';

/**
 * 시스템 업데이트 패널 — admin 전용.
 *
 *   Check → Apply → /healthz polling → reload
 *
 * 서버의 `/system/update/check` 가 git fetch 후 원격 main 과 비교해
 * 업데이트 가능 여부 + 커밋 목록을 반환. Apply 는 kotify-update.sh apply
 * 를 실행해 git pull + pip/pnpm 설치 + DB migrate + 서비스 재시작 스케줄.
 * 재시작은 2초 딜레이로 비동기 → 응답이 먼저 도달한 후 클라이언트는
 * /healthz 를 polling 하며 version 변경 감지 시 새로고침.
 */
export function SystemUpdatePanel() {
  const [phase, setPhase] = useState<Phase>('idle');
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<UpdateCheckResult | null>(null);
  const [elapsed, setElapsed] = useState(0);

  const onCheck = async () => {
    setPhase('checking');
    setError(null);
    try {
      const r = await checkSystemUpdate();
      setInfo(r);
      setPhase('ready');
    } catch (err) {
      setError(err instanceof Error ? err.message : '확인 실패');
      setPhase('error');
    }
  };

  const onApply = async () => {
    if (!info?.updateAvailable) return;
    if (
      !confirm(
        `${info.count}건의 업데이트를 설치하시겠습니까?\n\n서비스가 잠시 재시작됩니다.`,
      )
    ) {
      return;
    }
    setPhase('applying');
    setError(null);
    setElapsed(0);

    const prevVersion = await fetchCurrentVersion();
    let target = '?';
    try {
      const r = await applySystemUpdate();
      target = r.version;
    } catch (err) {
      setError(err instanceof Error ? err.message : '업데이트 실패');
      setPhase('error');
      return;
    }

    setPhase('restarting');
    const timer = setInterval(() => setElapsed((s) => s + 1), 1000);
    try {
      await waitForVersion(target, prevVersion, { timeoutMs: 60_000 });
      clearInterval(timer);
      setPhase('done');
      // 짧은 지연 후 새로고침 — 사용자가 "완료" 상태 잠깐 보게.
      setTimeout(() => {
        window.location.reload();
      }, 800);
    } catch (err) {
      clearInterval(timer);
      setError(
        err instanceof Error
          ? `${err.message}. 수동으로 새로고침하세요.`
          : '재시작 대기 시간 초과',
      );
      setPhase('error');
    }
  };

  return (
    <section
      aria-label="시스템 업데이트"
      className="rounded-lg border border-line bg-surface p-5"
    >
      <header className="mb-4">
        <h2 className="text-base font-semibold text-ink">시스템 업데이트</h2>
        <p className="mt-0.5 text-[12.5px] text-ink-muted">
          원격 저장소의 최신 커밋을 CT 에 배포합니다. DB 마이그레이션 + 양
          서비스 재시작까지 자동.
        </p>
      </header>

      {phase === 'idle' || phase === 'checking' ? (
        <Button
          variant="secondary"
          size="md"
          onClick={onCheck}
          loading={phase === 'checking'}
          icon={<Icon name="refresh" size={12} />}
        >
          업데이트 확인
        </Button>
      ) : null}

      {phase === 'ready' && info ? (
        <div className="flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <div className="text-sm">
              {info.updateAvailable ? (
                <>
                  <Badge kind="warning">
                    {info.count}건 대기 중
                  </Badge>
                  <span className="ml-2 font-mono text-[12.5px] text-ink-muted">
                    {info.current} → {info.remote}
                  </span>
                </>
              ) : (
                <>
                  <Badge kind="brand">최신 버전</Badge>
                  <span className="ml-2 font-mono text-[12.5px] text-ink-muted">
                    {info.current}
                  </span>
                </>
              )}
            </div>
            <div className="flex gap-2">
              <Button variant="ghost" size="sm" onClick={onCheck}>
                다시 확인
              </Button>
              {info.updateAvailable ? (
                <Button
                  variant="primary"
                  size="sm"
                  onClick={onApply}
                  icon={<Icon name="download" size={12} />}
                >
                  업데이트 설치
                </Button>
              ) : null}
            </div>
          </div>

          {info.commits.length > 0 ? (
            <ul className="max-h-44 overflow-y-auto rounded border border-line bg-gray-1 p-3 font-mono text-[11.5px] text-ink-muted">
              {info.commits.slice(0, 20).map((c) => (
                <li key={c.hash} className="truncate">
                  <span className="text-ink-dim">{c.hash}</span>{' '}
                  <span className="text-ink">{c.message}</span>
                </li>
              ))}
              {info.count > 20 ? (
                <li className="text-ink-dim">
                  … 외 {info.count - 20}건
                </li>
              ) : null}
            </ul>
          ) : null}
        </div>
      ) : null}

      {phase === 'applying' ? (
        <div className="text-sm text-ink-muted">
          ⏳ 업데이트 다운로드 + 설치 중…
        </div>
      ) : null}

      {phase === 'restarting' ? (
        <div className="text-sm text-ink-muted">
          ⏳ 서비스 재시작 중… ({elapsed}s)
        </div>
      ) : null}

      {phase === 'done' ? (
        <div className="text-sm text-ok">
          ✓ 업데이트 완료. 새로고침 중…
        </div>
      ) : null}

      {phase === 'error' && error ? (
        <div
          role="alert"
          className="rounded border border-danger/30 bg-danger/5 p-3 text-sm text-danger"
        >
          ✗ {error}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setPhase('idle');
              setError(null);
              setInfo(null);
            }}
            className="ml-2"
          >
            재시도
          </Button>
        </div>
      ) : null}
    </section>
  );
}
