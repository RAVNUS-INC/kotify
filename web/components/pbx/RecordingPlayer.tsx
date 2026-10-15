'use client';

import { useEffect, useRef, useState } from 'react';
import { Button, Icon } from '@/components/ui';
import { formatDuration } from '@/lib/pbx-format';

/**
 * 녹음 재생. 처음엔 버튼만 두고 눌렀을 때 `<audio>` 를 만든다 — 목록을 여는 것만으로
 * 녹음을 내려받거나 재생 감사 로그가 남지 않게 한다. src 는 kotify 서버 경로이며
 * 서버가 권한을 확인한 뒤 PBX 녹음을 대신 전달한다(길이·Range 는 서버가 직접 만든다).
 *
 * 브라우저 기본 재생기는 표 칸에 맞춰 높이를 줄이면 막대가 찌그러져 끌 수 없었다 →
 * 재생/멈춤 버튼, 끌 수 있는 막대(range 입력), "지금/전체" 시간을 직접 그린다.
 */
export function RecordingPlayer({ token, label }: { token: string; label: string }) {
  const [open, setOpen] = useState(false);
  if (!open) {
    return (
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={() => setOpen(true)}
        icon={<Icon name="play" size={12} />}
        aria-label={`${label} 녹음 재생`}
      >
        재생
      </Button>
    );
  }
  return <Player src={`/api/pbx/recordings/${encodeURIComponent(token)}`} label={label} />;
}

function Player({ src, label }: { src: string; label: string }) {
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

  // 버튼을 누른 순간 재생을 시작한다(사용자 동작에서 이어진 재생이라 자동재생 제한에 걸리지 않는다).
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
    return <span className="text-sm text-danger">녹음을 불러오지 못했습니다</span>;
  }

  return (
    <div className="inline-flex w-full min-w-[220px] max-w-[300px] items-center gap-2">
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
        aria-label={playing ? `${label} 녹음 멈춤` : `${label} 녹음 재생`}
        className="inline-flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-full bg-brand text-white transition-colors duration-fast hover:bg-brand-hover"
      >
        <Icon name={playing ? 'pause' : 'play'} size={12} />
      </button>
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
        aria-label={`${label} 녹음 재생 위치`}
        aria-valuetext={`${formatDuration(Math.floor(current))} / ${known ? formatDuration(Math.floor(duration)) : '알 수 없음'}`}
        className="h-1.5 min-w-0 flex-1 cursor-pointer accent-[var(--brand)] disabled:cursor-default"
      />
      <span className="shrink-0 text-xs tabular-nums text-ink-muted">
        {formatDuration(Math.floor(current))} / {known ? formatDuration(Math.floor(duration)) : '--:--'}
      </span>
    </div>
  );
}
