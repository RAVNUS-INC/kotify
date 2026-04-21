import type { ReactNode } from 'react';
import { cn } from '@/lib/cn';

export type DeviceMockupProps = {
  frame?: 'ios' | 'android';
  /** 내부 "화면" 가로 폭 (px). 실제 바깥 폭은 베젤 포함 */
  width?: number;
  /** 세로 비율. 기본 2:1 (실제 iPhone/안드는 ~2.1) */
  heightRatio?: number;
  senderName?: string;
  timeLabel?: string;
  children?: ReactNode;
  className?: string;
};

export function DeviceMockup({
  frame = 'ios',
  width = 280,
  heightRatio = 2,
  senderName = '발신자',
  timeLabel = '지금',
  children,
  className,
}: DeviceMockupProps) {
  const isIos = frame === 'ios';
  const height = width * heightRatio;
  const radius = isIos ? 36 : 24;
  const bezel = 10;

  return (
    <div
      className={cn(
        'relative mx-auto overflow-hidden bg-white shadow-[0_12px_40px_rgba(0,0,0,0.18),0_2px_8px_rgba(0,0,0,0.08)]',
        className,
      )}
      style={{
        width: width + bezel * 2,
        height: height + bezel * 2,
        borderRadius: radius + bezel,
        background: '#0a0a0a',
        padding: bezel,
      }}
      role="img"
      aria-label={`${isIos ? 'iOS' : 'Android'} 기기 미리보기`}
    >
      <div
        className="relative h-full w-full overflow-hidden bg-white"
        style={{ borderRadius: radius }}
      >
        {/* 상단 상태바 */}
        <div className="flex items-center justify-between px-5 pt-2 font-mono text-[10px] text-ink">
          <span>9:41</span>
          <span className="flex items-center gap-0.5">
            {isIos ? (
              <>●●●</>
            ) : (
              <>
                <span className="h-1 w-1 rounded-full bg-ink" />
                <span className="h-1 w-1 rounded-full bg-ink" />
                <span className="h-1 w-1 rounded-full bg-ink" />
              </>
            )}
          </span>
        </div>

        {isIos && (
          <div
            aria-hidden
            className="absolute left-1/2 top-1.5 h-4 w-20 -translate-x-1/2 rounded-full bg-[#0a0a0a]"
          />
        )}

        {/* 발신자 헤더 */}
        <div className="mt-2 flex items-center gap-2 border-b border-line px-4 py-2">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gray-3 font-mono text-[11px] text-gray-9">
            {senderName.charAt(0)}
          </div>
          <div className="min-w-0">
            <div className="truncate text-[11px] font-semibold text-ink">
              {senderName}
            </div>
            <div className="font-mono text-[10px] text-ink-dim">{timeLabel}</div>
          </div>
        </div>

        {/* 콘텐츠 (대화 버블 등) */}
        <div className="flex flex-col gap-2 p-4">{children}</div>
      </div>
    </div>
  );
}
