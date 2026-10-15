'use client';

import { useState } from 'react';
import { Button, Icon } from '@/components/ui';

/**
 * 녹음 재생. 처음엔 버튼만 두고 눌렀을 때 `<audio>` 를 만든다 — 목록을 여는 것만으로
 * 녹음을 내려받거나 재생 감사 로그가 남지 않게 한다. src 는 kotify 서버 경로이며
 * 서버가 권한을 확인한 뒤 PBX 녹음을 대신 전달한다.
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
  return (
    // eslint-disable-next-line jsx-a11y/media-has-caption -- 통화 녹음에는 자막 트랙이 없다
    <audio
      controls
      autoPlay
      preload="none"
      src={`/api/pbx/recordings/${encodeURIComponent(token)}`}
      aria-label={`${label} 녹음`}
      className="h-8 w-[220px]"
    />
  );
}
