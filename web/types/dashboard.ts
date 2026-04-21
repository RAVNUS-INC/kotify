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
  preview: string;
  /** "HH:MM" */
  time: string;
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
  };
  kpis: DashboardKpis;
};
