/** 사내 PBX 연동 — 팩스 작업, 통화 기록. 백엔드 app/routes/pbx.py 응답과 같은 모양. */

export type FaxStatus = 'QUEUED' | 'SUBMITTED' | 'SENT' | 'FAILED' | 'UNKNOWN';

export type FaxResolution = 'standard' | 'medium' | 'high';

export type FaxJob = {
  id: number;
  /** 숫자만 */
  recipient: string;
  filename: string;
  sizeBytes: number;
  resolution: FaxResolution;
  status: FaxStatus;
  error: string | null;
  /** UTC ISO */
  createdAt: string;
  submittedAt: string | null;
  completedAt: string | null;
  createdBy: string | null;
};

export type FaxListMeta = { limit: number; offset: number; hasMore: boolean };

export type CallDirection = 'in' | 'out' | 'internal' | 'transit' | 'unknown';

export type CallRecord = {
  id: number;
  /** KST ISO (+09:00). 해석 못 하면 빈 문자열 */
  at: string;
  direction: CallDirection;
  from: string;
  to: string;
  durationSec: number;
  billSec: number;
  /** ANSWERED | NO ANSWER | BUSY | FAILED | Answered Elsewhere … (PBX 원문) */
  disposition: string;
  /** 녹음이 있으면 재생용 불투명 토큰(30분 유효), 없으면 null */
  recordingToken: string | null;
  /** 고객 번호의 이름 — 하이웍스 CID 주소록, 없으면 kotify 주소록. 모르면 null */
  name?: string | null;
};

export type CallListMeta = {
  limit: number;
  hasMore: boolean;
  /** 다음 페이지 커서(PBX 가 offset 을 지원하지 않아 시각 기준), 없으면 null */
  nextCursor: string | null;
  /** 실제 조회 기간 (YYYY-MM-DD, KST) */
  from: string;
  to: string;
};

export type FaxInboxStatus = 'RECEIVED' | 'FAILED';
export type FaxInboxFetchStatus = 'PENDING' | 'FETCHED' | 'FETCH_FAILED' | 'NONE';

/** 받은 팩스 1건. PBX 파일 이름·경로는 내려오지 않는다. */
export type FaxInboxItem = {
  id: number;
  /** UTC ISO */
  receivedAt: string;
  /** 숫자만, 모르면 빈 문자열 */
  senderNumber: string;
  /** 하이웍스 CID·kotify 주소록 이름, 없으면 null */
  senderName: string | null;
  status: FaxInboxStatus;
  error: string | null;
  fetchStatus: FaxInboxFetchStatus;
  sizeBytes: number | null;
  firstViewedAt: string | null;
  firstViewedBy: string | null;
};

export type FaxInboxMeta = { limit: number; offset: number; hasMore: boolean; unread: number };
