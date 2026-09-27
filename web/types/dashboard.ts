export type TimelineEventState = 'done' | 'scheduled' | 'failed';

export type TimelineEvent = {
  id: string;
  /** "HH:MM" (24h) */
  time: string;
  label: string;
  state: TimelineEventState;
};

export type InboxThread = {
  id: string;
  name: string;
  phone?: string;
  preview: string;
  /** "HH:MM" (KST) */
  time: string;
  /** "YYYY-MM-DD" (KST). 시각을 해석하지 못하면 빈 문자열. */
  date: string;
  unread?: boolean;
};

export type DashboardKpis = {
  /** 0-100 % */
  rcsRate: number;
  todaySent: number;
  scheduled: number;
  todayCost: number;
  monthCost?: number;
};

export type DashboardData = {
  timeline: {
    events: TimelineEvent[];
    /** "HH:MM" */
    now: string;
  };
  inbox: {
    unread: number;
    threads: InboxThread[];
    /** "YYYY-MM-DD" (KST) — 응답 시각의 오늘. threads[].date 와 비교해 시각 문구를 만든다. */
    today: string;
  };
  kpis: DashboardKpis;
};
