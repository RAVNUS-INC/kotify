export type DeltaDirection = 'up' | 'down' | 'flat';

export type ReportKpi = {
  /** 절대값 (숫자 또는 퍼센트 값) */
  value: number;
  /** 표시용 델타 문자열 (예: "+2.1%", "-3.4%") */
  delta: string;
  deltaDir: DeltaDirection;
  spark: number[];
};

export type ReportKpis = {
  totalSent: ReportKpi;
  avgDeliveryRate: ReportKpi;
  replies: ReportKpi;
  cost: ReportKpi;
};

export type ReportDaily = {
  labels: string[];
  sent: number[];
  reply: number[];
};

export type ReportChannelEntry = {
  count: number;
  /** 0-100 */
  rate: number;
};

export type ReportChannels = {
  rcs: ReportChannelEntry;
  sms: ReportChannelEntry;
  lms: ReportChannelEntry;
  kakao: ReportChannelEntry;
};

export type ReportTopCampaign = {
  id: string;
  name: string;
  sent: number;
  /** 0-100 */
  replyRate: number;
};

export type ReportData = {
  kpis: ReportKpis;
  daily: ReportDaily;
  channels: ReportChannels;
  topCampaigns: ReportTopCampaign[];
};
