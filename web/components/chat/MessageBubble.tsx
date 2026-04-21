import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

export type MessageSide = 'us' | 'them';
export type MessageKind = 'rcs' | 'sms' | 'kakao';

export type MessageBubbleProps = {
  side?: MessageSide;
  kind?: MessageKind;
  timestamp?: string;
  children: ReactNode;
  className?: string;
};

const BASE =
  'max-w-[78%] rounded-2xl px-3 py-2 text-[13px] leading-[1.55] break-words whitespace-pre-wrap';

const styles: Record<MessageSide, Record<MessageKind, string>> = {
  them: {
    rcs: 'bg-gray-1 border border-gray-3 text-ink',
    sms: 'bg-gray-2 text-ink',
    kakao: 'bg-[#fee500] text-[#2e2a1d]',
  },
  us: {
    rcs: 'bg-brand text-white',
    sms: 'bg-gray-11 text-white',
    kakao: 'bg-[#2e2a1d] text-white',
  },
};

const KIND_LABEL: Record<MessageKind, string> = {
  rcs: 'RCS',
  sms: 'SMS',
  kakao: '카카오',
};

export function MessageBubble({
  side = 'them',
  kind = 'sms',
  timestamp,
  children,
  className,
}: MessageBubbleProps) {
  return (
    <div
      className={cn(
        'flex w-full items-end gap-1.5',
        side === 'us' ? 'justify-end' : 'justify-start',
        className,
      )}
    >
      {side === 'us' && timestamp && (
        <span className="font-mono text-[10px] text-ink-dim">{timestamp}</span>
      )}
      <div
        className={cn(BASE, styles[side][kind])}
        aria-label={`${side === 'us' ? '보낸' : '받은'} ${KIND_LABEL[kind]} 메시지`}
      >
        {children}
      </div>
      {side === 'them' && timestamp && (
        <span className="font-mono text-[10px] text-ink-dim">{timestamp}</span>
      )}
    </div>
  );
}
