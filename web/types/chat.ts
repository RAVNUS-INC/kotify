export type ChatChannel = 'sms' | 'rcs' | 'kakao';
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
