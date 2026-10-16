// RCS/SMS/LMS/MMS 세분화 — 사용자가 어느 채널로 발송/수신했는지 구분.
// kakao 는 친구톡.
export type ChatChannel = 'sms' | 'lms' | 'mms' | 'rcs' | 'kakao';
export type MessageSide = 'us' | 'them';
/** 답장 전송 방식 — 새 발송 화면과 같은 구분: 일반(SMS) / RCS. */
export type SendChannel = 'rcs' | 'sms';
/**
 * 발신 메시지 전달 상태. pending = 결과 리포트 대기(SMS 대체 발송 중 포함),
 * sent = 전달 성공 리포트, failed = msghub 요청 실패 또는 실패 리포트,
 * uncertain = 실패 리포트지만 단말에 전달됐을 수 있음(성공 불확실 등, 대체 SMS 없음),
 * cancelled = 예약 취소로 발송되지 않음.
 */
export type DeliveryStatus = 'pending' | 'sent' | 'failed' | 'uncertain' | 'cancelled';

export type ChatMessage = {
  id: string;
  side: MessageSide;
  kind: ChatChannel;
  text: string;
  /** "HH:MM" */
  time: string;
  /** "YYYY-MM-DD" (KST) — 날짜 구분선 기준. 시각을 해석하지 못한 메시지는 빈 문자열. */
  date: string;
  /** 발신(us) 전용. 결과를 알 수 없는 과거 발송은 없음. */
  status?: DeliveryStatus;
  /** 발신(us) 전용. 캠페인 작성자의 현재 표시명. */
  senderName?: string;
  /** 수신(them) 전용. MMS 제목. */
  title?: string;
  /** 수신(them) 전용. 고객이 보낸 파일(RCS fileMessage·MMS 첨부). 없으면 생략. */
  attachment?: MessageAttachment;
};

/**
 * 고객이 보낸 파일. 서버가 받아 보관한다(RCS 는 통신사 주소, MMS 는 msghub 컨텐츠 API).
 * ready 만 url(인증된 `/api/chat/media/{moId}`)이 있다. image 는 화면에 바로, file 은 내려받기만
 * (MMS 첨부만 해당 — RCS 는 사진이 아니면 unsupported). failed 는 만료·소진돼 다시 받을 수 없는 것.
 */
export type MessageAttachment = {
  kind: 'image' | 'file';
  status: 'ready' | 'pending' | 'failed' | 'unsupported';
  url?: string;
};

export type ChatThread = {
  id: string;
  name: string;
  phone: string;
  /** 하이웍스 CID 주소록 표시명(있으면). 예: "홍길동 부장 (레이븐어스)". */
  contactName?: string;
  preview: string;
  /** "HH:MM" (KST) — 마지막 메시지 시각. */
  time: string;
  /** "YYYY-MM-DD" (KST) — 마지막 메시지 날짜. 시각을 해석하지 못하면 빈 문자열. */
  date: string;
  unread?: boolean;
  channel: ChatChannel;
  lastCampaign?: string;
};

export type ChatThreadDetail = ChatThread & {
  messages: ChatMessage[];
  /** 이 상세 응답에 포함된 수신 메시지의 최대 id. 읽음 처리의 상한. */
  lastInboundMessageId: number | null;
  /** 이 번호로 가장 최근에 전달 성공한 발송의 전송 방식(답장 기본값). 이력 없으면 없음. */
  defaultSendChannel?: SendChannel;
};

export type ChatThreadPageMeta = {
  total: number;
  limit: number;
  offset: number;
  hasMore: boolean;
  /** q 검색 결과 전체의 안읽음 수. unread 필터·페이지와는 무관하다. */
  unreadTotal: number;
  /** "YYYY-MM-DD" (KST) — 응답 시각의 오늘. 행 date 와 비교해 목록 시각 문구를 만든다. */
  today: string;
};

export type ChatThreadPage = {
  data: ChatThread[];
  meta: ChatThreadPageMeta;
};
