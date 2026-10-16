'use client';

import * as Dialog from '@radix-ui/react-dialog';
import { useEffect, useRef, useState } from 'react';
import { Button, Icon, Pill } from '@/components/ui';
import { formatDateTime } from '@/lib/datetime';
import { formatPhone } from '@/lib/phone';
import {
  counterpart,
  DIRECTION_LABEL,
  dispositionLabel,
  formatCallTime,
  formatDuration,
} from '@/lib/pbx-format';
import type { CallRecord } from '@/types/pbx';

/**
 * 녹음 재생 — 목록에는 "재생" 버튼만 두고, 누르면 가운데 팝업에 통화 정보와 재생기를 띄운다.
 *
 * 예전엔 표 칸 안에서 재생기를 펼쳐 행 높이·폭이 밀렸고, 여러 행을 동시에 펼칠 수 있었다.
 * 팝업은 한 번에 하나만 열리고, 닫으면 `<audio>` 가 사라져 재생도 멈춘다. 목록을 여는 것만으로
 * 녹음을 내려받거나 재생 감사 로그가 남지 않도록 `<audio>` 는 팝업이 열린 뒤에만 만든다.
 * src 는 kotify 서버 경로이며, 서버가 권한을 확인한 뒤 길이·Range 를 직접 응답한다.
 */
export function RecordingPlayer({ call }: { call: CallRecord }) {
  const [open, setOpen] = useState(false);
  if (!call.recordingToken) return null;
  const time = formatDateTime(formatCallTime(call.at));
  const other = counterpart(call);
  const otherLabel = formatPhone(other) || other || '—';
  const ours = call.direction === 'out' ? call.from : call.to;

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          icon={<Icon name="play" size={12} />}
          aria-label={`${time} 통화 녹음 재생`}
        >
          재생
        </Button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-[1050] bg-[rgba(20,18,26,0.45)]" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-[1050] w-[min(92vw,440px)] -translate-x-1/2 -translate-y-1/2 rounded-xl border border-line bg-surface p-6 shadow-pop focus:outline-none"
        >
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <Dialog.Title className="m-0 truncate text-lg font-semibold text-ink">
                {call.name || otherLabel}
              </Dialog.Title>
              <Dialog.Description className="mt-0.5 text-md tabular-nums text-ink-muted">
                {call.name ? `${otherLabel} · ` : ''}
                {time || '시각 모름'} 통화 녹음
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                aria-label="닫기"
                className="inline-flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded text-ink-muted transition-colors duration-fast hover:bg-surface-hover hover:text-ink"
              >
                <Icon name="x" size={14} />
              </button>
            </Dialog.Close>
          </div>

          <dl className="m-0 mt-5 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-md">
            <dt className="text-ink-muted">구분</dt>
            <dd className="m-0">
              <Pill tone={call.direction === 'in' ? 'brand' : 'neutral'}>{DIRECTION_LABEL[call.direction]}</Pill>
            </dd>
            <dt className="text-ink-muted">내선·번호</dt>
            <dd className="m-0 tabular-nums text-ink">{formatPhone(ours) || ours || '—'}</dd>
            <dt className="text-ink-muted">결과</dt>
            <dd className="m-0 text-ink">{dispositionLabel(call.disposition)}</dd>
            <dt className="text-ink-muted">통화 시간</dt>
            <dd className="m-0 tabular-nums text-ink">{formatDuration(call.billSec)}</dd>
          </dl>

          <div className="mt-5 rounded-lg border border-line bg-surface-subtle p-4">
            {/* 팝업이 열려 있을 때만 존재 — 닫으면 재생이 멈춘다 */}
            {open && <Player src={`/api/pbx/recordings/${encodeURIComponent(call.recordingToken)}`} />}
          </div>
          <p className="m-0 mt-3 text-xs text-ink-dim">녹음 재생은 감사 로그에 남습니다.</p>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Player({ src }: { src: string }) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [current, setCurrent] = useState(0);
  const [duration, setDuration] = useState(0);
  const [failed, setFailed] = useState(false);

  // play() 는 브라우저에 따라 Promise 를 돌려주지 않을 수 있다(구형·테스트 환경).
  const start = () => {
    const result = audioRef.current?.play();
    if (result) result.catch(() => setPlaying(false));
  };

  // 재생 버튼을 눌러 팝업을 연 직후 재생한다(사용자 동작에서 이어져 자동재생 제한에 걸리지 않는다).
  useEffect(() => {
    start();
  }, []);

  const toggle = () => {
    const audio = audioRef.current;
    if (!audio) return;
    if (audio.paused) start();
    else audio.pause();
  };

  const known = Number.isFinite(duration) && duration > 0;

  if (failed) {
    return <p className="m-0 text-md text-danger">녹음을 불러오지 못했습니다. 목록을 새로 불러온 뒤 다시 시도하세요.</p>;
  }

  return (
    <div className="flex items-center gap-3">
      {/* eslint-disable-next-line jsx-a11y/media-has-caption -- 통화 녹음에는 자막 트랙이 없다 */}
      <audio
        ref={audioRef}
        src={src}
        preload="metadata"
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onTimeUpdate={(e) => setCurrent(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        onDurationChange={(e) => setDuration(e.currentTarget.duration)}
        onError={() => setFailed(true)}
        className="hidden"
      />
      <button
        type="button"
        onClick={toggle}
        aria-label={playing ? '녹음 멈춤' : '녹음 재생'}
        className="inline-flex h-[40px] w-[40px] shrink-0 items-center justify-center rounded-full bg-brand text-white transition-colors duration-fast hover:bg-brand-hover"
      >
        <Icon name={playing ? 'pause' : 'play'} size={14} />
      </button>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <input
          type="range"
          min={0}
          max={known ? duration : 0}
          step={0.1}
          value={Math.min(current, known ? duration : 0)}
          disabled={!known}
          onChange={(e) => {
            const audio = audioRef.current;
            if (!audio) return;
            audio.currentTime = Number(e.target.value);
            setCurrent(audio.currentTime);
          }}
          aria-label="녹음 재생 위치"
          aria-valuetext={`${formatDuration(Math.floor(current))} / ${known ? formatDuration(Math.floor(duration)) : '알 수 없음'}`}
          className="w-full cursor-pointer accent-[var(--brand)] disabled:cursor-default"
        />
        <div className="flex justify-between text-xs tabular-nums text-ink-muted">
          <span>{formatDuration(Math.floor(current))}</span>
          <span>{known ? formatDuration(Math.floor(duration)) : '--:--'}</span>
        </div>
      </div>
    </div>
  );
}
