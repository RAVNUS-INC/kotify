import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

export type MessageSide = 'us' | 'them';
// RCS/SMS/LMS/MMS/카카오 세분화. 색상은 발/수신만 구분하고 채널은 텍스트
// 라벨 (`01:38 / RCS`) 로 표시.
export type MessageKind = 'rcs' | 'sms' | 'lms' | 'mms' | 'kakao';

export type MessageBubbleProps = {
  side?: MessageSide;
  kind?: MessageKind;
  timestamp?: string;
  children: ReactNode;
  className?: string;
};

const BASE =
  'max-w-[78%] rounded-2xl px-3 py-2 text-[13px] leading-[1.55] break-words whitespace-pre-wrap';

// 채널(RCS/SMS)은 색이 아니라 타임스탬프 옆 텍스트 라벨로 표시 — 색맹/프린트
// 환경에서도 정보 유실 없도록. 발신/수신만 색으로 구분.
// 카카오 친구톡은 별도 플랫폼 UI 라 브랜드 인지 위해 노랑/올리브 톤 유지.
const STYLES: Record<MessageSide, Record<'default' | 'kakao', string>> = {
  them: {
    default: 'bg-gray-1 border border-gray-3 text-ink',
    kakao: 'bg-[#fee500] text-[#2e2a1d]',
  },
  us: {
    default: 'bg-brand text-white',
    kakao: 'bg-[#2e2a1d] text-white',
  },
};

const KIND_LABEL: Record<MessageKind, string> = {
  rcs: 'RCS',
  sms: 'SMS',
  lms: 'LMS',
  mms: 'MMS',
  kakao: '카카오',
};

export function MessageBubble({
  side = 'them',
  kind = 'sms',
  timestamp,
  children,
  className,
}: MessageBubbleProps) {
  const bubbleStyle = STYLES[side][kind === 'kakao' ? 'kakao' : 'default'];
  // `01:38 / RCS` 형식 — 시간이 없으면 채널만, 채널이 없으면 시간만.
  const meta = timestamp ? `${timestamp} / ${KIND_LABEL[kind]}` : KIND_LABEL[kind];

  return (
    <div
      className={cn(
        'flex w-full items-end gap-1.5',
        side === 'us' ? 'justify-end' : 'justify-start',
        className,
      )}
    >
      {side === 'us' && (
        <span className="whitespace-nowrap font-mono text-[10px] text-ink-dim">
          {meta}
        </span>
      )}
      <div
        className={cn(BASE, bubbleStyle)}
        aria-label={`${side === 'us' ? '보낸' : '받은'} ${KIND_LABEL[kind]} 메시지`}
      >
        {children}
      </div>
      {side === 'them' && (
        <span className="whitespace-nowrap font-mono text-[10px] text-ink-dim">
          {meta}
        </span>
      )}
    </div>
  );
}
