// RCS/SMS/LMS/MMS 세분화 — 사용자가 어느 채널로 발송/수신했는지 구분.
// kakao 는 친구톡.
export type ChatChannel = 'sms' | 'lms' | 'mms' | 'rcs' | 'kakao';
export type MessageSide = 'us' | 'them';

export type ChatMessage = {
  id: string;
  side: MessageSide;
  kind: ChatChannel;
  text: string;
  /** "HH:MM" */
  time: string;
};

export type ChatThread = {
  id: string;
  name: string;
  phone: string;
  /** 하이웍스 CID 주소록 표시명(있으면). 예: "홍길동 부장 (레이븐어스)". */
  contactName?: string;
  preview: string;
  /** "HH:MM" */
  time: string;
  unread?: boolean;
  channel: ChatChannel;
  lastCampaign?: string;
};

export type ChatThreadDetail = ChatThread & {
  messages: ChatMessage[];
};
