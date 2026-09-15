// RCS/SMS/LMS/MMS 세분화 — 사용자가 어느 채널로 발송/수신했는지 구분.
// kakao 는 친구톡.
export type ChatChannel = 'sms' | 'lms' | 'mms' | 'rcs' | 'kakao';
export type MessageSide = 'us' | 'them';
/** 답장 전송 방식 — 새 발송 화면과 같은 구분: 일반(SMS) / RCS. */
export type SendChannel = 'rcs' | 'sms';
/**
 * 발신 메시지 전달 상태. pending = 결과 리포트 대기(SMS 대체 발송 중 포함),
 * sent = 전달 성공 리포트, failed = msghub 요청 실패 또는 실패 리포트.
 */
export type DeliveryStatus = 'pending' | 'sent' | 'failed';

export type ChatMessage = {
  id: string;
  side: MessageSide;
  kind: ChatChannel;
  text: string;
  /** "HH:MM" */
  time: string;
  /** 발신(us) 전용. 결과를 알 수 없는 과거 발송은 없음. */
  status?: DeliveryStatus;
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
  /** 이 번호로 가장 최근에 전달 성공한 발송의 전송 방식(답장 기본값). 이력 없으면 없음. */
  defaultSendChannel?: SendChannel;
};
