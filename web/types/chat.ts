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
