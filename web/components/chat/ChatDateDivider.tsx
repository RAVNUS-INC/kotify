import { formatChatDate } from '@/lib/chat';

export type ChatDateDividerProps = {
  /** "YYYY-MM-DD" (KST) */
  date: string;
};

// 날짜가 바뀌는 지점 표시 — 말풍선 메타는 "HH:MM" 만 보여서 날짜는 이 줄에서 드러난다.
// 선은 border 로 그린다. 강제 색상(고대비) 모드는 배경색을 지워 bg 로 그린 선이 사라진다.
export function ChatDateDivider({ date }: ChatDateDividerProps) {
  return (
    <div className="flex items-center gap-3 py-2">
      <span aria-hidden className="flex-1 border-t border-line" />
      <time dateTime={date} className="shrink-0 text-[11px] text-ink-muted">
        {formatChatDate(date)}
      </time>
      <span aria-hidden className="flex-1 border-t border-line" />
    </div>
  );
}
