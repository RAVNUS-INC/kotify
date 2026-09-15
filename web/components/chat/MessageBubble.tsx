import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

export type MessageSide = 'us' | 'them';
// RCS/SMS/LMS/MMS/카카오 세분화. 색상은 발/수신만 구분하고 채널은 텍스트
// 라벨 (`01:38 / RCS`) 로 표시.
export type MessageKind = 'rcs' | 'sms' | 'lms' | 'mms' | 'kakao';
// 발신 전달 상태 — web/types/chat.ts 의 DeliveryStatus 와 같은 값.
export type MessageStatus = 'pending' | 'sent' | 'failed' | 'cancelled';

export type MessageBubbleProps = {
  side?: MessageSide;
  kind?: MessageKind;
  /** 발신(us) 전용 — 수신(them) 말풍선에서는 무시한다. */
  status?: MessageStatus;
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

// 상태도 채널처럼 텍스트로 붙인다 (`01:38 / RCS · 실패`). 발신 대부분인 전달 성공(sent)은
// 라벨을 늘리지 않고, 실패는 놓치지 않게 메타 라벨을 danger 색으로 — 색은 보조일 뿐.
// 예약 취소(cancelled)는 사용자가 멈춘 것이라 실패가 아니다 — 대기처럼 기본 색.
const STATUS_LABEL: Record<MessageStatus, string | null> = {
  pending: '대기',
  sent: null,
  failed: '실패',
  cancelled: '취소',
};

export function MessageBubble({
  side = 'them',
  kind = 'sms',
  status,
  timestamp,
  children,
  className,
}: MessageBubbleProps) {
  const bubbleStyle = STYLES[side][kind === 'kakao' ? 'kakao' : 'default'];
  // 수신 말풍선은 status 가 와도 기존 표시 그대로.
  const outStatus = side === 'us' ? status : undefined;
  const statusLabel = outStatus ? STATUS_LABEL[outStatus] : null;
  // `01:38 / RCS` 형식 — 시간이 없으면 채널만, 채널이 없으면 시간만.
  const channelMeta = timestamp ? `${timestamp} / ${KIND_LABEL[kind]}` : KIND_LABEL[kind];
  const meta = statusLabel ? `${channelMeta} · ${statusLabel}` : channelMeta;
  const metaClass = cn(
    'whitespace-nowrap font-mono text-[10px]',
    outStatus === 'failed' ? 'text-danger' : 'text-ink-dim',
  );

  return (
    <div
      className={cn(
        'flex w-full items-end gap-1.5',
        side === 'us' ? 'justify-end' : 'justify-start',
        className,
      )}
    >
      {side === 'us' && <span className={metaClass}>{meta}</span>}
      <div
        className={cn(BASE, bubbleStyle)}
        aria-label={`${side === 'us' ? '보낸' : '받은'} ${KIND_LABEL[kind]} 메시지${
          statusLabel ? `, 전송 ${statusLabel}` : ''
        }`}
      >
        {children}
      </div>
      {side === 'them' && <span className={metaClass}>{meta}</span>}
    </div>
  );
}
