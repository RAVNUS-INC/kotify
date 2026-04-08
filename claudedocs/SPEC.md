# 사내 SMS 공지 시스템 — 개발 명세서

> NCP SENS SMS v2 API 기반 사내 문자 공지 발송 시스템
> 작성일: 2026-04-08 / 버전: 0.1 (초안)

---

## 0. 한 페이지 요약 (TL;DR)

- **목적**: 사내 운영자가 웹 UI에서 다수 인원에게 SMS/LMS 공지를 발송하고, 발송 이력과 NCP 측 결과를 영구 보관·조회한다.
- **운영 도메인**: `sms.example.com`
- **스택**: Python 3.12 + FastAPI + Jinja2 + HTMX + SQLite + Authlib(Keycloak OIDC).
- **배포**: Proxmox LXC CT (Debian 12, 1GB RAM, 8GB disk). 앞단 NPM(Nginx Proxy Manager)이 TLS 종단.
- **규모**: 1회 발송 최대 1,000명. NCP 제약상 **100명씩 10개 청크로 분할 호출**.
- **결과 동기화**: NCP v2는 webhook 미지원 → **백그라운드 폴링 워커**가 `GET /messages?requestId=...`로 상태 갱신.
- **이력 보관**: NCP는 90일까지만 조회 가능 → 본 시스템 SQLite가 영구 저장소.
- **인증**: 모든 라우트는 Keycloak OIDC 보호 (realm/client = `sms-sys`). 발신은 별도 권한 그룹만.
- **시크릿 관리**: **`.env` 파일 없음.** 마스터 키 1개만 `/var/lib/sms/master.key` (자동 생성, 600 권한)에 두고, 모든 NCP/Keycloak 설정은 DB에 **Fernet 암호화** 저장. 웹 UI에서 관리.
- **부트스트랩**: 첫 실행 시 `/setup` wizard 자동 활성화 → Keycloak/NCP 설정 + 첫 admin 등록 → 폐쇄.

### 리서치에서 드러난 핵심 사실 (반드시 반영)
1. **`messages` 배열은 1회 호출당 최대 100건** (1000 아님). → 청크 분할 필수.
2. **NCP SMS v2에 webhook/callback 없음.** 결과 동기화는 폴링이 유일.
3. **Send 응답에 `messageId`가 없음.** 발송 직후 `requestId`로 list API 1회 호출해서 `messageId` 수집해야 함.
4. **`status=COMPLETED` ≠ 성공.** `status`는 발송 서버 처리 단계, 단말 수신 결과는 `statusName`(`success`/`fail`)으로 판단.
5. **시간 윈도우 비대칭**: requestTime 30일 / completeTime 24시간. 백필 로직 설계 시 주의.
6. **이력 보관**: API 90일 / 콘솔 30일. 본 시스템이 영구 보존 책임.
7. **EUC-KR 기반**: 이모지 발송 시 실패 가능. 본문 사전 정제 필요.
8. **본문 길이는 byte**: SMS 90B (한글 ~45자), LMS/MMS 2000B (한글 ~1000자).
9. **발신번호 사전 등록 필수** (영업일 3-4일). 미등록 시 수신결과코드 `3023`.
10. **5분 timestamp drift**: NTP 동기화 필수.

---

## 1. 범위와 비범위

### 1.1 범위 (In Scope)
- 웹 UI를 통한 SMS/LMS 공지 작성·발송
- 다양한 형식(`010-1234-5678`, `01012345678`, `+82-10-1234-5678` 등)의 전화번호 일괄 입력 및 정규화
- 발송 전 byte 길이 검증 및 SMS↔LMS 자동 판정
- 청크 분할(100명/호출) 자동 처리
- NCP 발송 결과 폴링·동기화 (성공/실패/실패사유 영구 저장)
- 발송 이력 조회·검색 (작성자/기간/상태별 필터)
- Keycloak OIDC 로그인
- 발신자 권한 분리 (viewer / sender / admin)
- 발신번호 화이트리스트 관리

### 1.2 비범위 (Out of Scope)
- LMS/MMS 첨부파일 발송 (1차 버전 제외, MMS는 추후)
- 예약 발송 (1차 버전 제외, 추후 옵션)
- 알림톡(KakaoTalk) 연동
- 광고성(`AD`) 발송 (098 수신거부 운영 필요 — 1차 제외)
- 사내 직원 명부 자동 연동 (수동 입력만)
- 다국어 번호 (국내 `01x`만 허용)
- 고가용성/이중화 (단일 CT)
- 외부 노출 (사내망/VPN only)

---

## 2. 사용자와 권한

| Role | 권한 |
|---|---|
| **viewer** | 본인이 발송한 이력만 조회 |
| **sender** | 발송 + 본인 이력 조회 |
| **admin** | 전체 이력 조회, 발신번호 관리, 사용자 권한 관리 |

권한은 Keycloak의 **realm role** 또는 **client role**로 매핑. ID 토큰 claim에서 읽어 FastAPI 의존성으로 검사.

---

## 3. 시스템 아키텍처

```
┌─────────────┐    HTTPS     ┌──────────────────────────────────┐
│  사용자     │ ───────────► │  Nginx Proxy Manager (사용자 운영) │
│  브라우저   │              │  - TLS 종단                        │
└─────────────┘              │  - sms.internal.example.com        │
                             └────────────────┬───────────────────┘
                                              │ HTTP (사설망)
                                              ▼
┌──────────────────────────────────────────────────────────────┐
│ Proxmox LXC CT (Debian 12, 1GB / 8GB / 1 vCPU)                │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ uvicorn (단일 프로세스)                                 │  │
│  │  ┌──────────────────────────────────────────────────┐  │  │
│  │  │ FastAPI app                                       │  │  │
│  │  │  - Jinja2 + HTMX 라우트 (UI)                      │  │  │
│  │  │  - REST 라우트 (HTMX fragment 응답)               │  │  │
│  │  │  - Authlib OIDC 미들웨어 (Keycloak)               │  │  │
│  │  │  - NCP SENS 클라이언트                            │  │  │
│  │  │  - asyncio 폴링 워커 (lifespan task)              │  │  │
│  │  └──────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  /var/lib/sms/sms.db   (SQLite, WAL 모드)                     │
│  /etc/sms/.env         (시크릿)                                │
│  systemd: sms.service                                         │
└──────────────────────────────────────────────────────────────┘
                                   │ HTTPS outbound
                                   ▼
                  ┌──────────────────────────────┐
                  │ NCP SENS API                 │
                  │ sens.apigw.ntruss.com        │
                  │ ┌──────────────────────────┐ │
                  │ │ Keycloak (별도 서버)      │ │
                  │ │ /realms/internal         │ │
                  │ └──────────────────────────┘ │
                  └──────────────────────────────┘
```

### 3.1 프로세스 모델
- **단일 uvicorn 프로세스, 단일 워커**. SQLite + 단일 인메모리 폴링 큐 일관성 보장을 위해.
- 폴링 워커는 `FastAPI lifespan`에서 `asyncio.create_task`로 띄움.
- WAL 모드로 SQLite 동시 read/write 안정성 확보.

---

## 4. 데이터 모델 (SQLite)

```sql
-- 사용자 (Keycloak에서 처음 로그인 시 upsert)
CREATE TABLE users (
  sub          TEXT PRIMARY KEY,        -- Keycloak sub
  email        TEXT NOT NULL,
  name         TEXT NOT NULL,
  roles        TEXT NOT NULL,           -- JSON array
  created_at   TEXT NOT NULL,
  last_login_at TEXT NOT NULL
);

-- 등록된 발신번호 (admin이 관리)
CREATE TABLE callers (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  number       TEXT NOT NULL UNIQUE,    -- 숫자만 (NCP 등록 형식과 동일)
  label        TEXT NOT NULL,
  active       INTEGER NOT NULL DEFAULT 1,
  is_default   INTEGER NOT NULL DEFAULT 0,  -- compose 화면 기본 선택 (1개만 1)
  created_at   TEXT NOT NULL
);
-- 초기 시드: 02-1234-5678(default), 02-1234-5678, 02-1234-5678

-- 시스템 설정 (env 대체) — 시크릿은 Fernet 암호화 후 저장
CREATE TABLE settings (
  key          TEXT PRIMARY KEY,         -- ncp.access_key, ncp.secret_key, ncp.service_id,
                                         -- keycloak.issuer, keycloak.client_id, keycloak.client_secret,
                                         -- session.secret, app.public_url 등
  value        TEXT NOT NULL,            -- 시크릿이면 Fernet ciphertext, 아니면 평문
  is_secret    INTEGER NOT NULL DEFAULT 0,
  updated_by   TEXT,                     -- users.sub
  updated_at   TEXT NOT NULL
);

-- 발송 캠페인 (사용자가 한 번 "보내기" 누른 단위)
CREATE TABLE campaigns (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  created_by    TEXT NOT NULL,                -- users.sub
  caller_number TEXT NOT NULL,
  message_type  TEXT NOT NULL,                -- SMS | LMS
  subject       TEXT,                         -- LMS 전용
  content       TEXT NOT NULL,
  total_count   INTEGER NOT NULL,
  ok_count      INTEGER NOT NULL DEFAULT 0,
  fail_count    INTEGER NOT NULL DEFAULT 0,
  pending_count INTEGER NOT NULL DEFAULT 0,
  state         TEXT NOT NULL,                -- DRAFT | DISPATCHING | DISPATCHED | COMPLETED | PARTIAL_FAILED | FAILED
  created_at    TEXT NOT NULL,
  completed_at  TEXT,
  FOREIGN KEY (created_by) REFERENCES users(sub)
);
CREATE INDEX idx_campaigns_created_by ON campaigns(created_by);
CREATE INDEX idx_campaigns_created_at ON campaigns(created_at);

-- NCP 청크 (campaign 1개 = ncp_request N개)
CREATE TABLE ncp_requests (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id     INTEGER NOT NULL,
  chunk_index     INTEGER NOT NULL,             -- 0..N-1
  request_id      TEXT,                         -- NCP requestId
  request_time    TEXT,                         -- NCP requestTime
  http_status     INTEGER,
  status_code     TEXT,                         -- NCP statusCode (e.g. "202")
  status_name     TEXT,                         -- success | fail
  error_body      TEXT,                         -- 실패 시 응답 raw
  sent_at         TEXT NOT NULL,
  FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
  UNIQUE (campaign_id, chunk_index)
);
CREATE INDEX idx_ncp_requests_request_id ON ncp_requests(request_id);

-- 개별 메시지 (수신자 단위)
CREATE TABLE messages (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  campaign_id     INTEGER NOT NULL,
  ncp_request_id  INTEGER NOT NULL,             -- ncp_requests.id (FK, NOT request_id 문자열)
  to_number       TEXT NOT NULL,                -- 정규화 후 (숫자만)
  to_number_raw   TEXT NOT NULL,                -- 사용자 원본 입력
  message_id      TEXT,                         -- NCP messageId (list API에서 수집)
  status          TEXT NOT NULL DEFAULT 'PENDING',
                  -- PENDING | READY | PROCESSING | COMPLETED | TIMEOUT | UNKNOWN
  result_status   TEXT,                         -- success | fail (NCP statusName)
  result_code     TEXT,                         -- NCP statusCode (e.g. "0", "3001", "3023")
  result_message  TEXT,                         -- NCP statusMessage
  telco_code      TEXT,
  complete_time   TEXT,
  last_polled_at  TEXT,
  poll_count      INTEGER NOT NULL DEFAULT 0,
  FOREIGN KEY (campaign_id) REFERENCES campaigns(id),
  FOREIGN KEY (ncp_request_id) REFERENCES ncp_requests(id)
);
CREATE INDEX idx_messages_campaign_id ON messages(campaign_id);
CREATE INDEX idx_messages_status ON messages(status);
CREATE INDEX idx_messages_message_id ON messages(message_id);

-- 감사 로그
CREATE TABLE audit_logs (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  actor_sub   TEXT,
  action      TEXT NOT NULL,            -- LOGIN | SEND | CALLER_CREATE | CALLER_DELETE | ...
  target      TEXT,
  detail      TEXT,                     -- JSON
  ip          TEXT,
  created_at  TEXT NOT NULL
);
```

### 4.1 상태 머신

#### Campaign.state
```
       ┌──────────┐
       │  DRAFT   │ (UI 미리보기 단계, 실제 INSERT는 발송 직전이라 보통 안 거침)
       └────┬─────┘
            ▼ (사용자 확정 → 발송 시작)
       ┌──────────────┐
       │ DISPATCHING  │ (청크들을 NCP에 전송 중)
       └────┬─────────┘
            ▼ (모든 청크 전송 완료)
       ┌──────────────┐
       │ DISPATCHED   │ (NCP는 받았음, 결과 폴링 대기)
       └────┬─────────┘
            ▼ (모든 messages가 final state 도달)
   ┌───────────────────────┐
   │ COMPLETED (전부 success) │
   │ PARTIAL_FAILED (일부 실패) │
   │ FAILED (전부 실패 / 청크 자체 실패) │
   └───────────────────────┘
```

#### Message.status
```
PENDING ──(NCP send 응답 200/202)──► READY/PROCESSING ──(폴링)──► COMPLETED
   │                                                                  │
   │                                                                  └─► result_status: success | fail
   └─(NCP send 응답 실패)─► (record 자체가 ncp_request 실패에 묶임 → status='UNKNOWN')

* 1시간 폴링해도 COMPLETED 안 되면 → status='TIMEOUT'
* result_status가 미설정 → status='UNKNOWN'
```

---

## 5. NCP SENS 연동 상세

### 5.1 인증 (HMAC-SHA256)

**필수 헤더 4종**:
- `x-ncp-apigw-timestamp`: epoch milliseconds (string)
- `x-ncp-iam-access-key`
- `x-ncp-apigw-signature-v2`
- `Content-Type: application/json`

**Signing string** (정확한 포맷):
```
{METHOD} {URI_WITH_QUERY}\n{TIMESTAMP}\n{ACCESS_KEY}
```
- METHOD/URI 사이는 공백 1개, 그 외는 LF.
- URI는 host 제외, querystring 포함.
- HMAC-SHA256 with secret_key, then Base64.

**파이썬 참조 구현** (`app/ncp/signature.py` — 사용자가 직접 작성하실 영역):
```python
def make_headers(method: str, uri: str, access_key: str, secret_key: str) -> dict:
    """
    NCP API Gateway 시그니처 헤더 4종을 만든다.

    중요:
    - timestamp는 단 한 번만 생성해서 헤더와 signing string 둘 다에 사용
    - NTP 동기화 필수 (5분 drift 시 401)
    - URI에 querystring 포함 (예약 발송 등에서 발생)
    """
    # TODO: 직접 구현
```

**함정 (반드시 회피)**:
- timestamp를 두 번 생성하면 401 (드물게라도)
- 시스템 시계 drift > 5분 → 401
- URI에 host 포함 시 401

### 5.2 발송 API

```
POST https://sens.apigw.ntruss.com/sms/v2/services/{serviceId}/messages
```

**Request Body**:
```json
{
  "type": "SMS",
  "contentType": "COMM",
  "countryCode": "82",
  "from": "0212345678",
  "content": "공지: 4월 9일 사옥 정전 점검이 있습니다.",
  "messages": [
    { "to": "01012345678" },
    { "to": "01087654321" }
  ]
}
```

**Response (성공, HTTP 202)**:
```json
{
  "requestId": "RSLA-...",
  "requestTime": "2026-04-08T14:23:11.535",
  "statusCode": "202",
  "statusName": "success"
}
```

**중요**: `messageId`가 응답에 없음. 직후 5.3 list 호출로 수집.

### 5.3 messageId 수집 (발송 직후 1회)

```
GET https://sens.apigw.ntruss.com/sms/v2/services/{serviceId}/messages?requestId={requestId}
```

`pageSize`가 `requestId` 입력 시 자동 1000이라 한 번에 100건 다 들어옴.

응답의 `messages[]` 각 항목에서 `messageId`, `to`, `status` 추출 → `messages` 테이블에 매칭 UPDATE (`to_number` 기준).

### 5.4 결과 폴링 (백그라운드 워커)

**알고리즘**:
```
loop every TICK seconds (예: 5초):
  미완료 메시지가 있는 ncp_requests 목록 조회
  for each ncp_request:
    if last_polled_at < now - backoff_interval(poll_count):
      GET /messages?requestId={request_id}
      for each message in response:
        UPDATE messages SET
          status = ?, result_status = ?, result_code = ?,
          result_message = ?, complete_time = ?, telco_code = ?,
          last_polled_at = now, poll_count = poll_count + 1
        WHERE message_id = ?
      campaign 카운터 재계산 + state 업데이트

  타임아웃: send 후 1시간 경과 시 status='TIMEOUT' 처리
```

**Backoff 스케줄** (poll_count 기준):
| poll_count | 다음 폴링까지 |
|---|---|
| 0 | 5초 |
| 1 | 10초 |
| 2 | 30초 |
| 3 | 1분 |
| 4-9 | 5분 |
| 10+ | 15분 |

**중지 조건**: 모든 messages가 `COMPLETED` 또는 발송 후 1시간 경과 (`TIMEOUT`).

### 5.5 에러 처리

| HTTP | 처리 |
|---|---|
| 202 | 정상 (Send 성공) |
| 200 | 정상 (List/Get 성공) |
| 400 | 본문/스키마 오류. 사용자에게 400 fail 표시. 재시도 불가. |
| 401 | 시그니처/시간 오류. 알람 + 관리자 점검 필요. |
| 403 | 권한 없음. serviceId 점검. |
| 404 | 리소스 없음. |
| 429 | Rate limit. Exponential backoff (1초→2초→4초→...) 후 재시도, 최대 5회. |
| 5xx | 일시 오류. 30초 후 재시도, 최대 3회. |

### 5.6 수신결과 코드 매핑 (주요)

| code | 분류 | 설명 |
|---|---|---|
| `0` | success | 성공 |
| `2000-2007` | 통신망 실패 | 일시적 (전원 OFF, 음영지역, 버퍼 풀 등) |
| `3001` | invalid | 결번 |
| `3003` | invalid | 수신번호 형식 오류 |
| `3018` | invalid | 발신번호 스푸핑 방지 가입 번호 |
| `3023` | **invalid** | **사전 등록 안 된 발신번호** ← 발신번호 화이트리스트로 차단 |

DB의 `result_code`는 raw 값으로 저장하고, UI에서 위 매핑 테이블로 한글 사유 표시.

---

## 6. 전화번호 정규화

### 6.1 입력 형식 (전부 허용)
```
01012345678
010-1234-5678
010 1234 5678
010.1234.5678
+82-10-1234-5678
+821012345678
8210-1234-5678
```

### 6.2 정규화 규칙
1. 모든 공백/`-`/`.`/`(`/`)` 제거
2. 선두 `+82` → `0` 치환
3. 선두 `82` (10자리 이상) → `0` 치환
4. 결과가 한국 휴대폰 패턴 `^01[016789]\d{7,8}$` 매치 확인
5. 미매치 시 invalid

### 6.3 정책 (확정)
**잘못된 번호가 섞였을 때**: **(a) 차단** — 전체 발송 거부.
- 미리보기 단계에서 잘못된 번호 목록을 표시하고, 하나라도 invalid가 있으면 "발송하기" 버튼 비활성화.
- 사용자는 잘못된 번호를 수정/삭제한 뒤에야 발송 가능.
- 발송 직전 서버 측에서 한 번 더 검증 (UI 우회 방지).

### 6.4 명세 (`app/util/phone.py` — 사용자가 직접 작성하실 영역)
```python
def normalize_phone(raw: str) -> str | None:
    """
    한국 휴대폰 번호를 정규화한다.
    성공: '01012345678' 형태 반환
    실패: None
    """
    # TODO: 직접 구현

def parse_phone_list(text: str) -> tuple[list[str], list[str]]:
    """
    멀티라인/콤마 구분 텍스트에서 번호를 추출하고 정규화한다.
    반환: (valid_normalized, invalid_originals)
    """
    # TODO: 직접 구현
```

---

## 7. 메시지 본문 검증

### 7.1 SMS/LMS 자동 판정
- byte 길이 ≤ 90 → SMS
- byte 길이 ≤ 2000 → LMS
- byte 길이 > 2000 → 거부

### 7.2 byte 계산
- **EUC-KR 인코딩 기준**으로 길이 측정 (NCP가 EUC-KR 기반).
- 한글 1자 = 2 byte, ASCII 1자 = 1 byte.
- 이모지/EUC-KR 미지원 문자 포함 시 **사전 차단** (NCP 발송 실패 방지).

### 7.3 명세 (`app/util/text.py`)
```python
def measure_bytes(text: str) -> int:
    return len(text.encode("euc-kr"))

def has_unsupported_chars(text: str) -> bool:
    try:
        text.encode("euc-kr")
        return False
    except UnicodeEncodeError:
        return True
```

---

## 8. 화면(UI) 명세

모든 화면은 Jinja2 + HTMX. SPA 아님. 부분 갱신만 HTMX 사용.

### 8.1 라우트 목록
| Method | Path | 권한 | 설명 |
|---|---|---|---|
| GET | `/setup` | setup-mode only | 부트스트랩 wizard (Keycloak/NCP 미설정 시만 활성) |
| POST | `/setup` | setup-mode only | wizard 저장 + 첫 admin 등록 + setup 폐쇄 |
| GET | `/` | viewer+ | 대시보드 (최근 캠페인 10건 + 통계) |
| GET | `/auth/login` | - | Keycloak 리다이렉트 |
| GET | `/auth/callback` | - | OIDC 콜백 |
| POST | `/auth/logout` | viewer+ | 로그아웃 |
| GET | `/compose` | sender+ | 신규 발송 작성 화면 |
| POST | `/compose/preview` | sender+ | 미리보기 (전화번호 검증, byte 길이, SMS/LMS 판정) |
| POST | `/compose/send` | sender+ | 실제 발송 (campaign INSERT + dispatch) |
| GET | `/campaigns` | viewer+ | 이력 목록 (필터: 기간, 상태, 작성자[admin만]) |
| GET | `/campaigns/{id}` | viewer+(본인) / admin | 상세 (수신자별 결과) |
| GET | `/campaigns/{id}/recipients` | viewer+(본인) / admin | 수신자 테이블 (HTMX, 페이지네이션) |
| GET | `/campaigns/{id}/refresh` | viewer+(본인) / admin | 폴링 강제 트리거 (HTMX 부분 갱신) |
| GET | `/admin/settings` | admin | 시스템 설정 (NCP 키, Keycloak, 도메인 등) |
| POST | `/admin/settings` | admin | 설정 저장 (시크릿은 Fernet 암호화 후 DB) |
| POST | `/admin/settings/test-ncp` | admin | NCP 인증 테스트 (현재 키로 발신번호 조회 등) |
| GET | `/admin/callers` | admin | 발신번호 관리 |
| POST | `/admin/callers` | admin | 발신번호 추가 |
| POST | `/admin/callers/{id}/toggle` | admin | 활성/비활성 |
| POST | `/admin/callers/{id}/default` | admin | 기본 발신번호 지정 |
| GET | `/admin/audit` | admin | 감사 로그 |
| GET | `/healthz` | - | 헬스체크 (인증 없음, NPM용) |

### 8.2 핵심 화면 와이어프레임 (텍스트)

**`/compose`**:
```
┌──────────────────────────────────────────────────────┐
│ 신규 공지 발송                                        │
├──────────────────────────────────────────────────────┤
│ 발신번호: [02-1234-5678 ▼]                           │
│                                                       │
│ 수신자 (한 줄에 한 번호 또는 콤마 구분):              │
│ ┌────────────────────────────────────────────────┐  │
│ │ 010-1234-5678                                   │  │
│ │ 01087654321                                     │  │
│ │ +82-10-9999-8888                                │  │
│ │ ...                                             │  │
│ └────────────────────────────────────────────────┘  │
│ → [번호 검증]                                         │
│                                                       │
│ ✓ 유효: 998명  ✗ 잘못된 번호: 2개 [보기]              │
│                                                       │
│ 본문:                                                 │
│ ┌────────────────────────────────────────────────┐  │
│ │ 4월 9일 22:00~24:00 사옥 정전 점검이 있습니다. │  │
│ └────────────────────────────────────────────────┘  │
│ 길이: 64 byte / 90 byte (SMS)                         │
│                                                       │
│         [미리보기]   [발송하기]                       │
└──────────────────────────────────────────────────────┘
```

**`/campaigns/{id}`**:
```
┌──────────────────────────────────────────────────────┐
│ 캠페인 #1234                                          │
├──────────────────────────────────────────────────────┤
│ 작성자: 홍길동 / 2026-04-08 14:23                    │
│ 발신번호: 02-1234-5678                                │
│ 상태: DISPATCHED → 폴링 중 (5초마다 갱신)             │
│                                                       │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 본문                                             │ │
│ │ 4월 9일 22:00~24:00 사옥 정전 점검이 있습니다.  │ │
│ └─────────────────────────────────────────────────┘ │
│                                                       │
│ 진행: 850 / 1000   ✓ 820  ✗ 30  ⏳ 150               │
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░ 85%                              │
│                                                       │
│ 수신자 결과 (HTMX 자동 갱신)                          │
│ ┌──────────────┬──────────┬───────────────────────┐ │
│ │ 번호          │ 상태     │ 사유                  │ │
│ ├──────────────┼──────────┼───────────────────────┤ │
│ │ 010-1234-5678│ ✓ 성공   │                       │ │
│ │ 010-9999-8888│ ✗ 실패   │ 결번 (3001)           │ │
│ │ ...          │ ⏳ 대기  │                       │ │
│ └──────────────┴──────────┴───────────────────────┘ │
└──────────────────────────────────────────────────────┘
```

---

## 9. 보안

### 9.1 인증
- Keycloak OIDC Authorization Code Flow + PKCE
- 세션 쿠키: `HttpOnly`, `Secure`, `SameSite=Lax`
- ID 토큰 검증 (서명, exp, iss, aud)
- 액세스 토큰은 서버 세션에 보관, 클라이언트에 노출 X

### 9.2 시크릿 관리 (`.env` 없음)

**원칙**: env 파일 없이 모든 설정은 웹 UI에서 관리. 시크릿은 DB에 Fernet 암호화 저장.

**계층 구조**:
```
[ Master Key ]  ──── 파일 1개만 존재
  /var/lib/sms/master.key  (32 byte, 600, sms:sms)
  ├─ 첫 실행 시 자동 생성 (cryptography.Fernet.generate_key())
  ├─ 백업 대상에서 제외 (DB와 분리 보관)
  └─ 절대 로그/응답에 노출 금지
        │
        ▼ Fernet (AES-128-CBC + HMAC-SHA256)
[ DB settings 테이블 ]
  ncp.access_key       (encrypted)
  ncp.secret_key       (encrypted)
  ncp.service_id       (encrypted, ID지만 권한 식별자라 보호)
  keycloak.client_secret (encrypted)
  keycloak.issuer       (plain)
  keycloak.client_id    (plain, = "sms-sys")
  session.secret        (encrypted, 자동 생성)
  app.public_url        (plain, = "https://sms.example.com")
```

**키 회전**:
- master.key는 회전하지 않는 것을 기본으로 함 (회전 시 모든 settings 재암호화 필요)
- 회전이 필요하면 admin UI에서 트리거 → 모든 시크릿 복호화 → 새 키 생성 → 재암호화 → 원자적 교체

**보안 트레이드오프 (명시)**:
- DB 백업 파일이 외부 유출되어도 master.key 없이는 시크릿 복호화 불가 → DB와 master.key를 **반드시 다른 위치에 백업**
- master.key 유출 + DB 유출 동시 발생 시 시크릿 노출됨 → 두 자산 모두 600 권한, root만 접근

**금지 사항**:
- 시크릿을 로그에 출력 금지 (NCP 응답 디버그 로그도 마스킹)
- 시크릿을 HTML 응답에 표시 금지 (UI에서는 `***` 마스킹, 마지막 4자리만 노출)
- 시크릿 컬럼 변경 시 audit log 기록 (단 새/구 값은 저장 안 함, "변경됨" 표기만)

### 9.3 CSRF
- 모든 POST 요청에 CSRF 토큰 (Starlette `SessionMiddleware` + 자체 토큰 또는 `fastapi-csrf-protect`)

### 9.4 Rate limit (사용자 측)
- 동일 사용자가 1분 내 5회 이상 발송 시 차단 (메모리 카운터로 충분)

### 9.5 감사
- 모든 발송, 발신번호 변경, 권한 변경, 설정 변경 → `audit_logs` 테이블
- 시크릿 변경 시 새/구 값 저장 금지, "변경됨" 사실만 기록

### 9.6 부트스트랩 (Setup 모드)

**문제**: Keycloak 설정이 DB에 있는데, 첫 실행 시 비어있으면 admin이 어떻게 로그인하나?

**해법**: setup 모드 — `settings` 테이블에 `bootstrap.completed=true`가 없으면 활성화.

**setup 모드 동작**:
1. **모든 일반 라우트가 `/setup`으로 강제 리다이렉트** (인증 우회 차단)
2. `/setup`은 인증 없이 접근 가능 (대신 `127.0.0.1` 또는 사내망 IP만 허용 — NPM 측 ACL로 1차 차단 권장)
3. **Setup 토큰**: 서비스 첫 시작 시 `master.key`와 함께 `/var/lib/sms/setup.token` 자동 생성 (16 byte hex). 사용자가 CT 콘솔/SSH로 이 파일을 읽어 wizard 화면에 입력해야 진행 가능 (네트워크만 뚫린 공격자 차단).
4. Wizard 단계:
   - Step 1: setup 토큰 입력
   - Step 2: Keycloak 정보 입력 (issuer, client_id=sms-sys, client_secret) + 연결 테스트
   - Step 3: NCP 정보 입력 (access_key, secret_key, service_id) + 발신번호 조회 테스트
   - Step 4: 발신번호 시드 데이터 확인/수정 (02-1234-5678 default)
   - Step 5: Keycloak으로 본인 로그인 → 첫 사용자가 자동 admin으로 등록
5. 완료 시 `bootstrap.completed=true` 저장 + `setup.token` 파일 삭제 + `/setup` 라우트 영구 비활성

**재설정 필요 시**: admin이 `/admin/settings`에서 변경 (setup 다시 안 띄움). master.key 분실 시에만 DB 초기화 후 setup 재실행.

---

## 10. 배포 (Proxmox CT)

### 10.1 CT 사양
- **OS**: Debian 12
- **Resources**: 1 vCPU / 1 GB RAM / 8 GB disk
- **Network**: 사내망 only, 외부 인바운드 차단 (NPM이 프록시)
- **Outbound**: `sens.apigw.ntruss.com:443`, Keycloak 서버, NTP

### 10.2 디렉토리 구조
```
/opt/sms/                       # 애플리케이션 (코드, 600 root:root)
  ├── app/                      # Python 패키지
  ├── pyproject.toml
  ├── .venv/                    # uv가 만든 가상환경
  └── alembic/                  # 마이그레이션
/var/lib/sms/                   # 데이터 (700 sms:sms)
  ├── sms.db                    # SQLite (600 sms:sms)
  ├── master.key                # 시크릿 마스터 키 (600 sms:sms, 자동 생성)
  └── setup.token               # 부트스트랩 토큰 (600, 완료 후 삭제)
/var/log/sms/                   # 로그 (700 sms:sms)
/etc/systemd/system/sms.service # systemd unit
```

**`.env` 파일 없음.** 모든 설정은 `/var/lib/sms/sms.db`의 `settings` 테이블 + `master.key`로 관리.

### 10.3 systemd unit
```ini
[Unit]
Description=Internal SMS Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=sms
Group=sms
WorkingDirectory=/opt/sms
ExecStart=/opt/sms/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1
Restart=on-failure
RestartSec=5

# 보안 강화
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/sms /var/log/sms
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### 10.4 백업

**중요: master.key와 sms.db는 반드시 분리 보관**.

- **DB 백업**: 매일 0시 SQLite `.backup` → `/var/backups/sms/sms-YYYYMMDD.db` (30일 retention)
- **master.key 백업**: 별도 안전한 위치(예: 1Password, 사내 비밀 저장소)에 1회 수동 백업. 자동 백업 위치에 함께 두지 않음.
- **CT 스냅샷**: Proxmox에서 주 1회. 스냅샷은 master.key와 DB가 함께 들어가지만 이는 디스크 복구용 — 외부 유출 시나리오와 분리.
- **복구 테스트**: 분기 1회 별도 CT에 스냅샷 복구 → 로그인 → 발송 가능 여부 검증.

### 10.5 NPM 설정 (사용자 영역)
- Domain: `sms.internal.example.com`
- Forward to: `<CT IP>:8080`
- SSL: Let's Encrypt 또는 사내 CA
- Custom location `/healthz`로 헬스체크

---

## 11. 의존성

```toml
# pyproject.toml
[project]
name = "ncp-sms-system"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "jinja2>=3.1",
  "python-multipart>=0.0.20",
  "sqlalchemy>=2.0",
  "alembic>=1.14",
  "authlib>=1.4",
  "httpx>=0.28",
  "itsdangerous>=2.2",
  "cryptography>=44.0",
  "pydantic-settings>=2.6",
]

[dependency-groups]
dev = [
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "respx>=0.22",
  "ruff>=0.8",
]
```

추론: 단일 패키지 매니저로 `uv` 사용 권장 (Debian CT에서 단일 바이너리, 빠름).

---

## 12. 프로젝트 구조

```
ncp-sms-system/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI 엔트리, lifespan, 라우터 등록
│   ├── config.py                # pydantic-settings
│   ├── db.py                    # SQLAlchemy engine/session
│   ├── models.py                # ORM 모델
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── oidc.py              # Authlib OIDC client
│   │   ├── deps.py              # require_user, require_role
│   │   └── session.py
│   ├── ncp/
│   │   ├── __init__.py
│   │   ├── signature.py         # ★ 사용자가 직접 작성
│   │   ├── client.py            # send / list_by_request_id
│   │   └── codes.py             # 수신결과 코드 → 한글 매핑
│   ├── services/
│   │   ├── compose.py           # 발송 비즈니스 로직 (검증/청크/dispatch)
│   │   ├── poller.py            # 백그라운드 폴링 워커
│   │   └── audit.py
│   ├── util/
│   │   ├── phone.py             # ★ 사용자가 직접 작성
│   │   └── text.py              # byte 길이, EUC-KR 검증
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── dashboard.py
│   │   ├── compose.py
│   │   ├── campaigns.py
│   │   ├── admin.py
│   │   └── health.py
│   └── templates/
│       ├── base.html
│       ├── dashboard.html
│       ├── compose.html
│       ├── campaigns/
│       │   ├── list.html
│       │   ├── detail.html
│       │   └── _recipients.html  # HTMX fragment
│       └── admin/
│           ├── callers.html
│           └── audit.html
├── alembic/
│   └── versions/
├── tests/
│   ├── test_phone.py
│   ├── test_signature.py
│   ├── test_text.py
│   ├── test_ncp_client.py       # respx로 mock
│   └── test_compose_flow.py
├── deploy/
│   ├── ct-bootstrap.sh           # Debian CT 초기 셋업
│   ├── sms.service               # systemd unit
│   └── npm-config.md             # NPM 설정 가이드
├── claudedocs/
│   ├── SPEC.md                   # 본 문서
│   └── ncp-research.md           # 리서치 결과 (분리 저장)
├── .env.example
├── .gitignore
├── pyproject.toml
└── README.md
```

---

## 13. 사용자가 직접 작성하실 영역 (Learning 포인트)

각 함수 위치/시그니처/명세는 위에 명시. 직접 작성하시면 좋은 이유:

| 파일 | 함수 | 왜 직접? |
|---|---|---|
| `app/ncp/signature.py` | `make_headers()` | NCP HMAC 시그니처 규칙(헤더 순서, timestamp 일관성, URI 포맷)을 한 번 직접 구현하면 401 디버깅이 훨씬 빨라짐 |
| `app/util/phone.py` | `normalize_phone()`, `parse_phone_list()` | 정규화 규칙은 비즈니스 정책. 어떤 형식까지 허용할지가 운영 결정 |
| `app/services/compose.py` (일부) | "잘못된 번호 발견 시 정책" | 6.3에서 결정한 (a)/(b)/(c) 정책을 코드에 반영 |

나머지는 제가 작성합니다.

---

## 14. 테스트 전략

### 14.1 단위 테스트
- `phone.py`: 다양한 입력 형식 (정상/비정상) 골고루
- `signature.py`: NCP 공식 문서 예시 그대로 입력 → 알려진 정답과 일치
- `text.py`: byte 길이, 이모지 검출

### 14.2 통합 테스트
- `respx`로 NCP API mock
  - 발송 성공/실패/429/타임아웃
  - 폴링 응답 (READY → PROCESSING → COMPLETED)
- SQLite in-memory로 DB 통합

### 14.3 수동 검증 (NCP 실호출)
- 본인 번호 1개로 SMS 1회 발송 → DB에 결과까지 정상 기록되는지 end-to-end 확인
- 발송번호 미등록 케이스 의도적 발생 → `3023` 처리 검증

---

## 15. 운영 체크리스트

### 출시 전
- [ ] NCP 콘솔에서 Project 생성, `serviceId` 확보
- [ ] 발신번호 등록 (02-1234-5678 / 5678 / 5678 — 영업일 3-4일 소요, 가장 먼저!)
- [ ] Access Key / Secret Key 발급 (Sub Account 권장)
- [ ] Keycloak에 realm/client `sms-sys` 생성 + 권한 그룹(viewer/sender/admin) 생성
- [ ] Keycloak Redirect URI: `https://sms.example.com/auth/callback`
- [ ] CT 생성 + 네트워크 설정
- [ ] NTP 동기화 확인 (`timedatectl`)
- [ ] NPM에 `sms.example.com` 호스트 등록 + TLS 발급
- [ ] systemd 서비스 등록 + 첫 시작 (master.key 자동 생성됨)
- [ ] CT 콘솔에서 `cat /var/lib/sms/setup.token` 확인
- [ ] `https://sms.example.com/setup` 접속 → wizard 진행
- [ ] master.key 별도 안전 위치에 백업 (1Password 등)
- [ ] 본인 번호로 end-to-end 테스트
- [ ] 백업 cron 설정

### 정기 운영
- [ ] 주 1회 SQLite 백업 검증 (복구 테스트)
- [ ] 월 1회 발신번호 만료 확인
- [ ] 분기 1회 NCP 사용량 점검 (월 한도 10,000건)

---

## 16. 결정사항 (확정)

| # | 항목 | 결정 |
|---|---|---|
| 1 | 잘못된 번호 정책 | **(a) 차단** — 하나라도 invalid면 발송 불가 |
| 2 | Keycloak realm/client | `sms-sys` |
| 3 | 운영 도메인 | `sms.example.com` |
| 4 | 발신번호 (3개) | `02-1234-5678` (default), `02-1234-5678`, `02-1234-5678` |
| 5 | 광고성(`AD`) 발송 | 1차 제외 |
| 6 | 폴링 타임아웃 | **1시간** (5/10/30/60/300/900초 backoff). 근거: NCP SMS는 통상 수 초~수십 초 내 COMPLETED. 1시간이면 통신망 일시 장애도 흡수. 더 길게 가면 폴링 큐에 좀비 row가 쌓임. |
| 7 | 직접 작성 함수 3개 | OK (signature, normalize_phone, parse_phone_list) |
| 8 | **`.env` 폐기, 웹 설정** | **마스터 키(파일 1개) + DB Fernet 암호화 + Setup wizard** 방식 채택 (§9.2, §9.6) |

---

## 17. 다음 단계

본 명세서 승인 후:

1. `pyproject.toml`, 디렉토리 스켈레톤, `.env.example`, alembic init
2. DB 모델 + 첫 마이그레이션
3. NCP 클라이언트 (단, `signature.py`는 함수 시그니처만 두고 비움)
4. 전화번호/텍스트 유틸 (단, `phone.py`는 함수 시그니처만 두고 비움)
5. → **사용자가 두 파일 작성**
6. Keycloak OIDC 미들웨어
7. 라우트 + 템플릿
8. 폴링 워커
9. 단위/통합 테스트
10. CT 부트스트랩 스크립트 + systemd
11. 본인 번호로 E2E 테스트

---

## 부록 A. 출처

| 주제 | URL |
|---|---|
| SENS overview | https://api.ncloud-docs.com/docs/en/sens-overview |
| Send message | https://api.ncloud-docs.com/docs/en/sens-sms-send |
| Get message list | https://api.ncloud-docs.com/docs/en/sens-sms-list |
| Get message result | https://api.ncloud-docs.com/docs/en/sens-sms-get |
| Reservation status | https://api.ncloud-docs.com/docs/en/sens-sms-reservation-status-get |
| Cancel reservation | https://api.ncloud-docs.com/docs/en/sens-sms-reservation-delete |
| 공통 API (시그니처) | https://api.ncloud-docs.com/docs/en/common-ncpapi |
| 발신번호 가이드 | https://guide.ncloud-docs.com/docs/sens-callingno |
| SMS 사용 가이드 | https://guide.ncloud-docs.com/docs/sens-smsmessage |
