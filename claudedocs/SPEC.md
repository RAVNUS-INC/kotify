# kotify — 개발 명세서

> U+ msghub 기반 RCS 우선 단체 공지 발송 시스템
> 작성일: 2026-04-08 / 최종 갱신: 2026-09-18 / 버전: 0.2

---

## 0. 한 페이지 요약 (TL;DR)

- **목적**: 운영자가 웹 UI에서 다수 인원에게 RCS/SMS/LMS/MMS 공지를 발송하고, 발송 이력과 결과를 영구 보관·조회한다.
- **발송 전략**: **RCS 우선**. RCS 실패 시 msghub `fbInfoLst`로 SMS/LMS/MMS 자동 fallback. ⚠️ 단문은 outbound 에서 양방향(8원) 미지원이라 **단방향 RCS(17원)** 로 발송되어 SMS(9원)보다 비쌈(비용 역전). 양방향 8원 전환은 U+ 확인 필요(TODO). 이미지: RCS 템플릿(40원) → MMS(85원, **53% 절감** — 이미지만 RCS 이득).
- **운영 도메인**: `sms.example.com`
- **스택**: Python 3.12+ FastAPI 백엔드 + Node 20+ Next.js 14 프론트엔드 + SQLite + Authlib(Keycloak OIDC).
- **배포**: Proxmox LXC CT (Debian 12/13, 1 vCPU / 1 GB / 8 GB). FastAPI는 내부(8080), Next.js가 외부 대면(3000). NPM이 TLS 종단.
- **규모**: 1회 발송 최대 1,000명.
- **결과 동기화**: **msghub 웹훅**과 지연·불명확한 발송 결과의 주기적 재조정.
- **이력 보관**: 본 시스템 SQLite가 영구 저장소.
- **인증**: 모든 앱 라우트는 Keycloak OIDC 보호 (realm/client = `sms-sys`). 2-tier guard (middleware + layout session).
- **시크릿**: **`.env` 없음.** 마스터 키 1개만 `/var/lib/kotify/master.key` (600 권한, 자동 생성)에 두고, 모든 msghub/Keycloak 설정은 DB에 **Fernet 암호화** 저장. 웹 UI에서 관리.
- **부트스트랩**: 첫 실행 시 `/setup` wizard 자동 활성화 → Keycloak + msghub + RCS 설정 + 첫 admin 등록 → 폐쇄.

### 핵심 설계 원칙

1. **RSC-first**: Next.js App Router의 서버 컴포넌트를 기본으로, `'use client'`는 stateful leaf에만.
2. **URL state > client state**: 필터/선택/검색은 모두 `searchParams`로. 뒤로가기/딥링크/공유가 공짜로 동작.
3. **CORS surface = 0**: 프론트엔드는 FastAPI URL을 모른다. `/api/*`는 Next.js `rewrites()`로 내부 프록시.
4. **모션 1.2s 예산**: 한 페이지의 모든 연출이 1.2초 이내 종료 (`motion-timing.md` 매트릭스로 강제).
5. **Typed routes**: `experimental.typedRoutes: true` — 컴파일 시 잘못된 링크 차단.

---

## 1. 범위와 비범위

### 1.1 범위 (In Scope)

- 웹 UI를 통한 RCS/SMS/LMS/MMS 공지 작성·발송
- 전화번호 다양한 형식(`010-1234-5678`, `01012345678`, `+82-10-1234-5678` 등) 일괄 입력 및 정규화
- 발송 전 byte 길이 검증 및 채널 자동 판정 (RCS/LMS/MMS)
- msghub 웹훅 기반 결과 수신 (`/webhook/msghub/report`) 및 이력 영구 저장
- 발송 이력 조회·검색 (작성자/기간/상태/채널별 필터)
- Keycloak OIDC 로그인
- 역할별 권한 분리 (viewer / sender / admin)
- 발신번호 화이트리스트 관리
- 연락처/그룹/예약 발송 (기본)
- 실시간 채팅(SSE) — RCS 양방향 대화
- 감사 로그 (모든 민감 작업)
- 알림 센터, 통합 검색, 리포트(차트/KPI)

### 1.2 비범위 (Out of Scope)

- 카카오톡 알림톡/친구톡 (msghub는 지원하나 본 시스템은 미사용)
- 광고성(`AD`) 발송 (098 수신거부 운영 필요 — 1차 제외)
- MO(수신 메시지) 기반 자동 응답 플로우 (수신 수신 기록만)
- 사내 직원 명부 자동 연동 (CSV/수동 입력만)
- 다국어 번호 (국내 `01x`만 허용)
- 고가용성/이중화 (단일 CT)
- 외부 노출 (사내망/VPN 운영 전제)

---

## 2. 사용자와 권한

| Role | 권한 |
|---|---|
| **viewer** | 본인이 발송한 이력만 조회 |
| **sender** | 발송 + 본인 이력 조회 |
| **admin** | 전체 이력 조회, 발신번호/사용자/설정 관리 |

권한은 Keycloak의 **realm role** 또는 **client role**로 매핑한다. 검증된 로그인 콜백이
역할·프로필·`last_login_at`을 DB에 저장하며 최초 관리자 이메일 정책도 이때 적용한다.
일반 요청은 세션의 사용자 식별자로 DB를 조회한다. FastAPI 권한 검사와 Next.js가 사용하는
`GET /api/auth/me` 모두 DB의 최신 역할·프로필을 사용하므로 오래된 세션이 이전 권한을 복원하지 않는다.
DB 사용자가 없으면 인증을 거부하며 `/api/auth/me`는 HTTP 401을 반환한다. DB 역할은 문자열 배열만
허용하고 잘못된 형식에는 권한을 부여하지 않는다. Keycloak에서 변경한 역할은 새 검증 로그인 후
DB에 반영된다. 매 요청의 외부 권한 조회나 토큰 재검증은 추가하지 않는다.

---

## 3. 시스템 아키텍처

```
┌─────────────┐    HTTPS     ┌──────────────────────────────────┐
│  사용자     │ ───────────► │  Nginx Proxy Manager (사용자 운영) │
│  브라우저   │              │  - TLS 종단                        │
└─────────────┘              │  - sms.example.com                 │
                             │  - proxy_buffering off (SSE)       │
                             └────────────────┬───────────────────┘
                                              │ HTTP (사설망)
                                              ▼
┌──────────────────────────────────────────────────────────────┐
│ Proxmox LXC CT (Debian 12/13, 1GB / 8GB / 1 vCPU)            │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ kotify-web.service — Next.js 14 (0.0.0.0:3000)          │  │
│  │  - App Router (RSC + Client Components)                 │  │
│  │  - typedRoutes, middleware (Keycloak guard)             │  │
│  │  - rewrites: /api/* → http://127.0.0.1:8080/*           │  │
│  │  - SSE 프록시 (chat)                                    │  │
│  └───────────────────┬─────────────────────────────────────┘  │
│                      │ HTTP (loopback)                          │
│                      ▼                                           │
│  ┌────────────────────────────────────────────────────────┐  │
│  │ kotify.service — FastAPI (127.0.0.1:8080)               │  │
│  │  - REST 라우트 (/api/* 로 노출, 원본은 /*)               │  │
│  │  - Authlib OIDC (Keycloak)                              │  │
│  │  - msghub 클라이언트 (JWT, SHA512 이중 해싱)            │  │
│  │  - /webhook/msghub/report — 결과 수신                   │  │
│  │  - /webhook/msghub/mo — 수신 메시지 (기록만)            │  │
│  │  - SSE 엔드포인트 (chat stream)                         │  │
│  └────────────────────────────────────────────────────────┘  │
│                                                               │
│  /var/lib/kotify/sms.db      (SQLite, WAL 모드)               │
│  /var/lib/kotify/master.key  (600, 자동 생성)                 │
│  systemd: kotify.service + kotify-web.service                 │
└──────────────────────────────────────────────────────────────┘
                                   │ HTTPS outbound
                                   ▼
                  ┌──────────────────────────────┐
                  │ U+ msghub API                │
                  │ api.msghub.uplus.co.kr       │
                  │   (또는 전용선 1.209.4.60/75) │
                  │                              │
                  │ Keycloak (별도 서버)          │
                  │ /realms/sms-sys              │
                  └──────────────────────────────┘
```

### 3.1 프로세스 모델

- FastAPI: **단일 uvicorn 프로세스, 단일 워커** (SQLite 일관성).
- Next.js: **node standalone server** (`output: 'standalone'`). Next.js 내부는 다중 리퀘스트 병렬 처리.
- SQLite: WAL 모드로 동시 read/write 안정성 확보.
- 웹훅 엔드포인트는 단순 upsert라 동시성 이슈 없음 (UNIQUE index + `ON CONFLICT DO UPDATE`).

---

## 4. 데이터 모델 (SQLite)

핵심 테이블 요약 (신규 배포 시 `alembic upgrade head`로 초기 구축):

```sql
-- 사용자 (Keycloak에서 처음 로그인 시 upsert)
CREATE TABLE users (
  sub TEXT PRIMARY KEY, email TEXT, name TEXT, roles TEXT,
  created_at TEXT, last_login_at TEXT
);

-- 발신번호 화이트리스트
CREATE TABLE callers (
  id INTEGER PRIMARY KEY, number TEXT UNIQUE, label TEXT,
  active INTEGER, is_default INTEGER, created_at TEXT
);

-- 시스템 설정 (env 대체) — 시크릿은 Fernet ciphertext
CREATE TABLE settings (
  key TEXT PRIMARY KEY,       -- msghub.api_key, msghub.api_password, msghub.brand_id,
  value TEXT,                  -- keycloak.issuer, keycloak.client_id, ...
  is_secret INTEGER, updated_by TEXT, updated_at TEXT
);

-- 연락처 / 그룹 (Phase 7c 추가)
CREATE TABLE contacts (...);
CREATE TABLE contact_groups (...);

-- 발송 캠페인
CREATE TABLE campaigns (
  id INTEGER PRIMARY KEY, created_by TEXT, caller_number TEXT,
  message_type TEXT,    -- RCS | RCS_LMS | RCS_IMAGE (각각 SMS/LMS/MMS fallback)
  subject TEXT, content TEXT,
  total_count INTEGER, ok_count INTEGER, fail_count INTEGER, pending_count INTEGER,
  state TEXT,           -- DRAFT | DISPATCHING | DISPATCHED | COMPLETED | PARTIAL_FAILED | FAILED | RESERVED | RESERVE_FAILED | RESERVE_CANCELED
  reserve_at TEXT,      -- 예약 발송 시각 (UTC)
  created_at TEXT, completed_at TEXT
);

-- msghub 요청 단위
CREATE TABLE msghub_requests (
  id INTEGER PRIMARY KEY, campaign_id INTEGER, chunk_index INTEGER,
  msg_key TEXT,         -- msghub의 발송 요청 고유 키
  http_status INTEGER, status_code TEXT, error_body TEXT,
  sent_at TEXT
);

-- 개별 메시지 (수신자 단위)
CREATE TABLE messages (
  id INTEGER PRIMARY KEY, campaign_id INTEGER, msghub_request_id INTEGER,
  to_number TEXT, to_number_raw TEXT,
  cli_key TEXT,         -- client-side key: c{campaign}-{chunk}-{idx} — webhook 매칭용
  msg_key TEXT,         -- msghub-side key: 발송 응답에서 받음
  status TEXT,          -- PENDING | REG | ING | FB_PENDING | DONE | FAILED | CANCELED
  result_channel TEXT,  -- RCS | SMS | LMS | MMS (실제 도달된 채널)
  result_code TEXT, result_message TEXT,
  complete_time TEXT, received_at TEXT  -- webhook 수신 시각
);

-- 감사 로그
CREATE TABLE audit_logs (
  id INTEGER PRIMARY KEY, actor_sub TEXT, action TEXT, target TEXT,
  detail TEXT,          -- JSON (단, 시크릿 값 자체는 저장 안 함)
  ip TEXT, created_at TEXT
);
```

### 4.1 Campaign.state 상태 머신

| 단계 | 상태와 전이 |
|---|---|
| 작성·접수 | `DRAFT` → `DISPATCHING`; 즉시 발송 접수 결과는 `DISPATCHED` / `PARTIAL_FAILED` / `FAILED` |
| 예약 접수 | `RESERVED` / `PARTIAL_FAILED` / `RESERVE_FAILED`; 일부 청크 요청 실패여도 접수된 예약은 남을 수 있음 |
| 결과 확정 | 모든 수신자 결과가 정해지면 `COMPLETED` / `PARTIAL_FAILED` / `FAILED`로 재집계 |
| 요청 시간 초과 복구 | 실패 메시지가 공급자 조회에서 `REG`/`ING`으로 확인되면 캠페인도 `DISPATCHING`으로 복구하고 커밋 뒤 변경 이벤트 발행 |
| 예약 취소 | 확인된 청크의 대기 메시지를 `CANCELED`로 변경. 발송될 수 있는 행이 없으면 `RESERVE_CANCELED` |

`completed_at`은 최초 결과 시각을 유지한다. 재조정으로 상태가 바뀌어도 알림 정렬·읽음 기준이
새 시각으로 밀리지 않으며, 알림 내용은 현재 캠페인 상태를 따른다.

`GET /api/campaigns/{id}`의 `canCancelReservation`은 예약 메타데이터·청크 요청 ID·대기 행으로
계산한다. 상세 화면의 취소 버튼도 이 값을 사용하므로 `PARTIAL_FAILED`에서 접수된 예약을 취소할
수 있다. `POST /api/campaigns/{id}/cancel`은 남은 청크만 처리하고 청크별 취소 성공을 저장한다.
요청 시간 초과·5xx·응답 파싱 오류·과거 코드 없는 실패 및 조회의 `INVALID_KEY`/`OVER_DATE`는
명시적인 공급자 거부와 구분하며, 이를 남긴 채 전체 취소로 표시하지 않는다. 확인된 청크를 취소한
뒤에도 불명확한 예약은 `RESERVED`로 남기고 상세의 `failureReason`에 미확정 인원과 msghub 웹 콘솔
확인·취소 안내를 계속 표시한다. 알려진 예약을 모두 취소하면 `canCancelReservation=false`가 되고,
미확정 행만 남은 재취소 요청은 HTTP 409 `unconfirmed_reservation`을 반환한다.

### 4.2 Message.status 상태 머신

| 상태 | 의미 |
|---|---|
| `PENDING` | 예약 등 결과 리포트 대기 |
| `REG` / `ING` | 공급자 접수 / 처리 중 |
| `FB_PENDING` | RCS 실패 뒤 대체 SMS의 결과 대기 |
| `DONE` | 최종 리포트 수신. `result_code`로 전달 성공·실패 판정 |
| `FAILED` | 요청 단계 실패. 명시적인 거부 코드가 없고 요청 결과가 불명확하면 지연 리포트·재조정으로 복구 가능 |
| `CANCELED` | 예약 취소 확인. 성공·실패·대기 카운터에서 제외 |

요청 시간 초과를 전달 실패 확정으로 취급하지 않는다. 재조정이 `FAILED`를 `REG`/`ING`으로 복구한
경우도 변경 이벤트를 발행하지만, 재조정의 반환 건수에는 기존처럼 `DONE` 확정만 포함한다.


### 4.3 팀 공유 읽음 경계 (스키마 0019)

`thread_reads`는 기존 `caller`·`phone`·`read_at`과 `(caller, phone)` 고유 제약을 보존하고,
`last_read_mo_id INTEGER NOT NULL DEFAULT 0` 및 `phone` 인덱스를 추가한다. 읽음 상태는 같은
고객 번호의 모든 행에서 `MAX(last_read_mo_id)`를 사용하며 사용자별·발신번호별로 나누지 않는다.
읽음 요청이 역순으로 완료돼도 원자적인 최댓값 갱신으로 경계가 후퇴하지 않는다.

마이그레이션 `0019_thread_read_mo_cursor.py`는 기존 `read_at` 이전에 서버가 받은 MO의
`received_at`을 사용해 번호별 연속 ID 구간만 이관한다. 공급자 `mo_recv_dt`로 과거의 지연 수신을
읽음으로 추정하지 않는다. 불명확한 시각이나 미관측 ID를 건너뛰지 않으므로 일부 과거 회신이
다시 안읽음으로 보일 수 있다. 기존 `mo_messages`의 재구축·삭제는 수행하지 않는다.

현재 MO 삭제 경로가 없어 수신 ID는 저장 순서대로 증가한다. 향후 삭제·보관을 도입한다면 SQLite
ID 재사용을 막는 별도 순번 또는 `AUTOINCREMENT`를 함께 설계해야 한다. 배포·구 클라이언트
호환 안내는 `deploy/README.md`의 `0019` 절을 따른다.

---

## 5. U+ msghub 연동 상세

> 전체 API 레퍼런스: [`msghub-api-guide.md`](./msghub-api-guide.md)
> 에러 코드 전체: [`msghub-error-codes.md`](./msghub-error-codes.md)
> 구현 기획서: [`msghub-migration-spec.md`](./msghub-migration-spec.md)

### 5.1 인증 (JWT)

- msghub는 **JWT Bearer 인증** 사용.
- API Key / API Password 로 `/auth/token` 호출 → JWT 발급 (만료 시간 있음).
- 구현: `app/msghub/auth.py`의 `TokenManager` 가 자동 갱신 관리.
  - **SHA512 이중 해싱**: API Password를 두 번 SHA512 — 공식 가이드대로.
  - **asyncio.Lock stampede 방지**: 여러 요청이 동시에 만료 토큰을 발견해도 단 하나만 갱신 요청.
  - **Pre-expiry 갱신**: 만료 60초 전에 선제 갱신.

### 5.2 발송 API

- `POST /send/rcs` — RCS (양방향 CHAT / LMS / 이미지 템플릿)
- `fbInfoLst` 파라미터에 fallback 체인 지정 (SMS/LMS/MMS).
- 응답에 `msgKey` 즉시 반환 → messages 테이블에 저장.
- **청크 크기: 10명** (msghub 권장). `cliKey` 패턴: `c{campaign_id}-{chunk}-{idx}`.

### 5.3 웹훅 결과 수신

- **Report**: `POST /api/webhook/msghub/report` — 발송 결과 (DELIVERED / FAILED + 실제 도달 채널).
- **MO**: `POST /api/webhook/msghub/mo` — 수신 메시지 (기록만, 자동 응답 없음).
- **서명 검증**: msghub가 전송하는 서명 헤더를 HMAC으로 검증. 실패 시 403.
- 페이로드의 `cliKey` 또는 `msgKey`로 messages 테이블 매칭 → UPDATE.

### 5.4 에러 처리

| HTTP | 처리 |
|---|---|
| 200 | 정상 |
| 400 | 본문/스키마 오류. 사용자에게 fail 표시. 재시도 불가. |
| 401 | JWT 만료 또는 서명 오류. TokenManager가 1회 재발급 후 재시도. |
| 403 | 권한 없음. API Key / IP 화이트리스트 점검. |
| 429 | Rate limit. Exponential backoff (1초→2초→4초→…), 최대 5회. |
| 5xx | 일시 오류. 30초 후 재시도, 최대 3회. |

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

### 6.3 정책

**잘못된 번호가 섞였을 때**: **(a) 차단** — 전체 발송 거부.
- 미리보기 단계에서 invalid 번호 목록 표시, 하나라도 있으면 "발송하기" 버튼 비활성.
- 서버 측에서 한 번 더 검증 (UI 우회 방지).

구현: `app/util/phone.py` (`normalize_phone`, `parse_phone_list`).

---

## 7. 메시지 본문 검증

### 7.1 채널 자동 판정

현재 앱의 본문 분류는 **EUC-KR 바이트 길이**를 기준으로 한다. 이는 공급자 HTTP 요청의 전송 인코딩과 별개인 앱 검증 정책이다. RCS/SMS/LMS/MMS 판정 기준:

| 채널 | 조건 | 요금 |
|---|---|---|
| RCS 단문 (단방향 SMS형) | 본문 ≤ 90 byte, 이미지 없음 | **17원** (fallback SMS 9원) ⚠️ RCS 가 더 비쌈 |
| RCS LMS | 본문 > 90 byte, 이미지 없음 | 27원 (fallback LMS 27원) |
| RCS 이미지 템플릿 | 이미지 첨부 | 40원 (fallback MMS 85원) |

> ⚠️ **비용 역전 주의**: 양방향 CHAT(8원)은 outbound 브로드캐스트에 사용 불가
> (replyId 미보유 → 29003/404). 단문은 단방향 SMS형(17원)으로 발송되어 SMS
> fallback(9원)보다 비싸다. 양방향 8원 전환은 U+ 지원 확인 필요(TODO).

최초 발송은 본문 > 2000 byte이면 거부한다. 대화방 답장은 RCS·일반 SMS 모두 90바이트 이내 단문만 허용하며 LMS로 자동 전환하지 않는다.

### 7.2 byte 계산

- EUC-KR 인코딩 기준으로 측정한다: `len(text.encode("euc-kr"))`.
- 보통 한글 1자 = 2바이트, ASCII 1자 = 1바이트다. 일부 확장 한글은 더 많은 바이트를 사용하므로 글자 수만으로 판정하지 않는다. 본문 안의 공백·줄바꿈도 포함하며, EUC-KR 미지원 문자(이모지 등)는 발송을 차단한다.
- 대화방 답장은 발송할 본문의 앞뒤 공백을 제거한 뒤 서버에서 검증한다. 예를 들어 `가` 45자(90바이트)는 허용하고 46자(92바이트)는 거부한다. 입력 중 같은 서버 검증 결과로 길이·오류를 안내한다(§8.4).
- 알려진 별도 제약: 최초 발송 화면 `ComposeForm`의 예상 길이 표시는 아직 `TextEncoder`의 UTF-8 계산을 사용해 서버 분류와 다를 수 있다. 이번 서버 기준 사전 검증 적용 범위는 대화방 답장이며, 최초 발송 화면의 계산 통일은 후속 작업이다.

구현: `app/util/text.py`.

---

## 8. 프론트엔드 (Next.js 14)

### 8.1 라우트 구조

Route groups로 인증 경계를 나눔:

```
web/app/
├── (auth)/
│   └── login/page.tsx         — Keycloak 리다이렉트
├── (app)/                      — 모든 앱 라우트 (middleware가 인증 검사)
│   ├── layout.tsx              — getSession 2-tier guard
│   ├── page.tsx                — S1 Dashboard
│   ├── send/new/page.tsx       — S2 발송 작성
│   ├── chat/[id]/page.tsx      — S3 채팅 (SSE)
│   ├── campaigns/page.tsx      — S5 이력 목록
│   ├── campaigns/[id]/page.tsx — S4 캠페인 상세
│   ├── contacts/page.tsx       — S7 주소록 (Drawer 편집)
│   ├── groups/page.tsx         — S9 그룹 목록
│   ├── groups/[id]/page.tsx    — S10 그룹 상세
│   ├── numbers/page.tsx        — S11 발신번호
│   ├── settings/[[...tab]]/    — S12 설정 (catch-all)
│   ├── audit/page.tsx          — S13 감사 로그 + CSV export
│   ├── notifications/page.tsx  — S15 알림 센터
│   ├── reports/page.tsx        — S16 리포트/통계
│   ├── search/page.tsx         — S17 통합 검색
│   └── error/                  — S18 에러 3종 (not-found/error/global-error)
├── offline/page.tsx            — PWA 폴백
├── setup/                      — Setup Wizard (bootstrap 모드만)
└── middleware.ts               — Keycloak 세션 검사 + /setup/login 예외
```

### 8.2 설계 원칙

- **Server Components가 기본**. 데이터 페치는 RSC에서 `fetch(...)` 직접 호출.
- **`'use client'`는 stateful leaf에만**: 폼, 필터 UI, 모션 컴포넌트.
- **URL state**: 필터(`?status=COMPLETED&q=홍길동`), 선택(`?selected=42`), 탭(`?tab=advanced`)은 모두 `searchParams`로.
- **Typed routes**: `experimental.typedRoutes: true`. 동적 조합은 `as Route` 캐스트.
- **`/api/*` rewrite**: `next.config.mjs`에서 FastAPI로 프록시. CORS 설정 불필요.

### 8.3 주요 컴포넌트 프리미티브

| 컴포넌트 | 용도 |
|---|---|
| `Card`, `Field`, `Input`, `Button` | 기본 UI |
| `Drawer` (Radix Dialog) | 편집 오버레이 (contact 등) |
| `CommandPalette` (Radix Dialog) | ⌘K 통합 검색 |
| `ChipField` | 태그 입력 |
| `DataTable` | 정렬/페이지네이션 테이블 |

### 8.4 대화방 API·입력·SSE

- `GET /threads`는 `q`(번호·최근 본문), `unread`, `limit`(기본 200, 1~200), `offset`(기본 0, 0 이상)을 받는다. 전체 대화에 검색·안읽음 조건을 적용한 뒤 최근 활동순으로 페이지를 자른다. 응답은 `{ data: ChatThread[], meta: { total, limit, offset, hasMore, unreadTotal } }`이다. `total`은 검색·안읽음 조건을 적용한 결과 수이며 `unreadTotal`은 `q` 검색 결과 전체의 안읽음 수로 페이지·안읽음 필터와 무관하다. 검색어가 없으면 전체 안읽음 수다. 하이웍스 주소록 이름은 페이지 조회 후 표시용으로 붙이며 검색 대상은 아니다.
- `/chat`는 검색어·필터·선택 대화·offset을 URL에 저장한다. 이전·다음 이동과 대화 선택은 나머지 조건을 유지하고, 검색·필터 변경은 offset을 초기화한다. 전체 건수와 검색 결과 기준 안읽음 수는 API metadata를 사용한다. 대시보드 안읽음 집계도 최신 200개에 제한되지 않는다.
- 최근 발신의 목록 순서·본문 선택은 상세와 같이 `complete_time → report_dt → campaign.created_at` 순서로 보완한다. 따라서 리포트가 없는 신규 `REG`·`FAILED` 답장도 목록에 반영되며, 혼합 시각 포맷은 실제 시각으로 비교한다.
- `GET /threads/{id}`는 실제로 조회한 수신 MO의 최대 ID를 `lastInboundMessageId: number | null`로 반환한다. 이 응답 이후 도착한 MO를 별도 조회해 끼워 넣지 않는다. `POST /threads/{id}/read`는 필수 JSON `{ "lastReadMessageId": 42 }`를 받으며 양의 정수와 해당 고객 번호의 수신 ID인지 확인한다. 누락·다른 번호의 MO는 HTTP 422다. 번호 단위 팀 공유 경계를 최댓값으로 갱신하고 `{ data: { id, unread, lastReadMessageId } }`를 반환한다. ID 이후에 온 회신은 안읽음으로 남고 공급자 발생 시각은 판정에 사용하지 않는다.
- `ThreadView`는 `unread`가 계속 true여도 실제 관측 ID가 바뀌면 읽음을 다시 요청한다. 같은 관측값의 실패를 재렌더마다 반복하지 않으며, 다른 대화로 이동한 뒤 완료된 이전 읽음 응답은 새 화면을 갱신하지 않는다.
- `GET /threads/{id}`의 `messages[]`와 답장 발송 응답은 발신(`side="us"`)에만 `senderName`을 포함한다. 단체 발송·대화 답장 모두 `Campaign.created_by`로 연결한 사용자의 현재 `display_name`, `name` 순으로 표시한다. 빈 값·이메일 형태·계정 식별자는 건너뛰며, 사용자나 표시명이 없으면 `알 수 없음`이다. 발송 시점의 이름 스냅샷은 아니며 현재 로그인한 열람자를 작성자로 추정하지 않는다. 수신 메시지는 이 필드를 생략하고 UI도 이름을 표시하지 않는다.
- 발신 메타는 `12:31 / SMS / 가상 담당자` 형식이고 대기·실패·취소 상태만 뒤에 덧붙인다. 성공 상태는 별도 문구를 붙이지 않으며 긴 이름은 줄바꿈한다.
- 브라우저 `POST /api/threads/validate-reply` → FastAPI `POST /threads/validate-reply`는 `{ "text": "본문" }`을 받아 `{ "data": { "byteLength": 4, "maxBytes": 90, "valid": true, "error": null } }` 형태로 응답한다. 로그인·설정 완료·CSRF 검사를 유지하며 DB 변경이나 공급자 발송 없이 실제 답장의 `validate_reply_content` 정책을 적용한다. 검증에 실패해도 HTTP 200의 `valid=false`와 오류 문구를 반환한다. 빈 입력은 0바이트·오류 문구 없음이며, 인코딩 불가나 입력 상한 4000자 초과로 측정하지 못하면 `byteLength=null`이다.
- 입력이 멈춘 뒤 300ms 후 앞뒤 공백을 제거한 본문을 검증하고 현재 바이트·90바이트 한도·초과 또는 미지원 문자 오류를 표시한다. 확인 중이거나 검증 실패·통신 오류가 있으면 버튼과 발송 단축키를 모두 막는다. 오래된 응답은 무시하고 검증 통신 실패 시 재확인할 수 있다. 최종 발송에서도 서버가 같은 정책을 다시 검사한다.

- `POST /threads/{id}/messages`의 RCS 답장은 유효한 MO `replyId`가 있으면 양방향으로 요청한다. 명시적인 요청 거부 또는 수신자별 거부는 단방향 RCS 대체 경로로 보낸다. 양방향 요청의 시간 초과·5xx·파싱 오류 등 접수 미확정은 실제 요청의 `cliKey`와 단건 메시지를 보존하고 즉시 추가 발송하지 않는다. 지연 리포트·재조정으로 원래 요청 결과를 확인한다. 접수 뒤 실패 리포트에 대한 기존 SMS 대체 경로는 유지한다.
- 최종 요청 거부는 HTTP 502 `send_failed`, 접수 미확정은 HTTP 502 `send_status_unknown`이며 `{ error: { code, message, fields: { campaignId: "42" } } }`로 반환한다. 미확정 메시지는 기존 `FAILED`·`result_code=None`으로 저장되어 나중에 복구될 수 있다. 입력창은 본문을 유지하고 오류 안내와 기록 새로고침만 수행한다. 자동 재발송하지 않으며, 미확정 안내가 있으면 다시 보내기 전에 결과를 확인해야 한다. 대체 발송도 실패할 수 있어 전달 성공을 보장하지 않는다.

- `/chat`와 `/chat/[id]`는 서버 컴포넌트로 데이터를 읽고 `ChatLiveRefresh`가 탭당 SSE 연결 하나를 유지한다.
- 브라우저 `/api/chat/stream` → FastAPI `/chat/stream`은 전역 갱신 신호를 보낸다. `message.new`는 고객 회신, `thread.updated`는 발신 상태 변경이며 메시지 본문을 이벤트에 싣지 않는다.
- 서버는 이벤트 종류별 5초 창으로 묶어 처음과 마지막 변경을 알린다. 클라이언트는 회신에 새로고침하고, 전달 상태는 열린 대화의 `pending`·`failed` 발신 메시지가 있을 때 갱신한다. 실패에는 나중에 복구될 수 있는 요청 시간 초과가 포함된다.
- 전달 갱신 간격은 5초에서 시작해 대상 목록이 같으면 최대 60초까지 늘어난다. 이벤트가 없으면 폴링하지 않는다. 최초 연결·재연결이 열리면 목록·확정된 대화를 포함해 모든 화면을 한 번 갱신해 구독 전·단절 중 회신을 보정한다. 이 갱신은 전달 상태의 긴 대기 간격에 묶지 않고 기존 타이머와 합치며, 닫힌 연결의 늦은 이벤트는 무시한다. 대화 이동 중 받은 최근 15초 이내 전달 상태 이벤트도 감시 대상이 있는 새 화면에 한 번 반영한다.
- 네트워크 단절 시 exponential backoff 재연결 (1s → 2s → 4s → max 30s). 서버는 25초마다 keep-alive를 보내며 이벤트 버스는 단일 uvicorn 워커를 전제로 한다.
- Korean IME 처리: `isComposing` 상태에서는 Enter 무시.

---

## 9. 모션 디자인 시스템

> 상세: [`motion-timing.md`](./motion-timing.md)

### 9.1 1.2초 예산

**"한 페이지 전체 연출은 1.2초 이내"** — 사용자 기다림의 상한.
각 요소의 정지 시각 = `delay + duration`. 페이지 예산 = 가장 늦게 정지하는 요소.

### 9.2 Primitive

| 요소 | default duration | 용도 |
|---|---|---|
| `Counter` | 900 | 숫자 tweening (tabular-nums로 CLS 0) |
| `Sparkline` (useDrawOn) | 1200 | 스트로크 draw-on |
| `AnimatedBars` | 700 (stagger 40 × N) | 세로 바 차트 |
| `Progress` | 900 | 가로 진행률 바 |
| `Rise` / `Stagger` | 400 (baseDelay + step × i) | 리스트 항목 순차 등장 |
| `PulseDot` | 1400 (infinite) | 상태 인디케이터 (reduced-motion 시 CSS로 자동 정지) |

### 9.3 Reduced Motion

`useReducedMotion()` 훅이 `prefers-reduced-motion: reduce` 감지 시 모든 primitive를 즉시 최종값으로 점프시킴.
`PulseDot`은 globals.css 미디어 쿼리로 keyframes 자동 정지.

---

## 10. 보안

### 10.1 인증

- Keycloak OIDC Authorization Code Flow + PKCE
- 세션 쿠키: `HttpOnly`, `Secure`, `SameSite=Lax`
- 2-tier guard: Next.js middleware + `layout.tsx`의 `getSession`. 하나가 뚫려도 다른 층이 차단.

### 10.2 시크릿 관리 (`.env` 없음)

```
[ Master Key ] /var/lib/kotify/master.key (32 byte, 600, kotify:kotify)
               ├─ 첫 실행 시 자동 생성 (cryptography.Fernet.generate_key())
               ├─ 백업 대상에서 제외 (DB와 분리 보관)
               └─ 절대 로그/응답에 노출 금지
        ▼ Fernet (AES-128-CBC + HMAC-SHA256)
[ DB settings 테이블 ]
  msghub.api_key       (encrypted)
  msghub.api_password  (encrypted)
  msghub.brand_id      (encrypted)
  msghub.chatbot_id    (encrypted)
  msghub.webhook_secret (encrypted)
  keycloak.client_secret (encrypted)
  keycloak.issuer      (plain)
  keycloak.client_id   (plain, = "sms-sys")
  session.secret       (encrypted, 자동 생성)
  app.public_url       (plain)
```

### 10.3 CSRF

- Next.js server actions: SameSite 쿠키 + 명시적 토큰 (필요 시).
- FastAPI POST 라우트: Starlette `SessionMiddleware` + 자체 토큰.
- 웹훅: msghub의 서명 헤더 HMAC 검증.

### 10.4 기타

- **CSV formula injection 방어** (CWE-1236): `app/util/csv_safe.py::safe_csv_cell` — `=`, `+`, `-`, `@`, `\t`, `\r` 선두 시 앞에 `'` prefix.
- **Rate limit**: 동일 사용자 1분 내 5회 이상 발송 시 차단 (메모리 카운터).
- **감사**: 모든 발송/설정 변경/권한 변경 → `audit_logs`. 시크릿 값 저장 금지("변경됨" 표기만).
- **Setup 모드**: `bootstrap.completed=true`가 없으면 `/setup`으로 강제 리다이렉트 + 사내망 IP ACL + setup.token 확인.

---

## 11. 배포 (Proxmox CT)

### 11.1 CT 사양

- **OS**: Debian 12 (Bookworm) 또는 13 (Trixie)
- **Resources**: 1 vCPU / 1 GB RAM / 8 GB disk
- **Network**: 사내망 only, 외부 인바운드 차단 (NPM이 프록시)
- **Outbound**: msghub API, Keycloak, NTP, GitHub

### 11.2 디렉토리 구조

```
/opt/kotify/                    # 애플리케이션 (root:root 755)
  ├── app/                      # FastAPI Python 패키지
  ├── web/                      # Next.js 프로젝트 + 빌드 산출물 (.next/)
  ├── pyproject.toml
  ├── .venv/                    # Python 가상환경
  └── alembic/                  # 마이그레이션
/var/lib/kotify/                # 데이터 (kotify:kotify 700)
  ├── sms.db                    # SQLite (600)
  ├── master.key                # 마스터 키 (600, 자동 생성)
  └── setup.token               # 부트스트랩 토큰 (완료 후 삭제)
/var/log/kotify/                # 로그 (700)
/var/backups/kotify/            # 백업 (700)
/etc/systemd/system/kotify.service       # FastAPI
/etc/systemd/system/kotify-web.service   # Next.js
```

### 11.3 systemd 유닛

**`kotify.service`** — FastAPI (127.0.0.1:8080, 내부만):

```ini
[Service]
Type=simple
User=kotify
Group=kotify
WorkingDirectory=/opt/kotify
ExecStartPre=/opt/kotify/.venv/bin/alembic -c /opt/kotify/alembic.ini upgrade head
ExecStart=/opt/kotify/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080 --workers 1 --proxy-headers --forwarded-allow-ips=*
Restart=on-failure
NoNewPrivileges=false  # 웹 UI 원클릭 업데이트용 sudo
ProtectSystem=strict
ReadWritePaths=/var/lib/kotify /var/log/kotify /opt/kotify
```

**`kotify-web.service`** — Next.js (0.0.0.0:3000, 외부 대면):

```ini
[Service]
Type=simple
User=kotify
Group=kotify
WorkingDirectory=/opt/kotify/web
Environment=NODE_ENV=production
Environment=FASTAPI_URL=http://127.0.0.1:8080
Environment=HOSTNAME=0.0.0.0
Environment=PORT=3000
ExecStart=/usr/bin/node /opt/kotify/web/.next/standalone/server.js
Restart=on-failure
```

### 11.4 NPM

외부에서 Next.js(3000)만 보임. FastAPI(8080)는 Next.js `rewrites()`를 통해서만 호출.
`deploy/npm-config.md` 참조.

### 11.5 백업

- **DB**: 매일 0시 SQLite `.backup` → `/var/backups/kotify/kotify-YYYYMMDD.db` (30일 retention)
- **master.key**: 1회 수동, 1Password 등 외부 저장소
- **Next.js 빌드 산출물**은 백업 대상 아님 — 재배포 시 `pnpm build`로 복원

---

## 12. 의존성

```toml
# pyproject.toml
[project]
requires-python = ">=3.12"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "sqlalchemy>=2.0",
  "alembic>=1.14",
  "authlib>=1.4",
  "httpx>=0.28",
  "cryptography>=44.0",
  "pydantic-settings>=2.6",
]

[dependency-groups]
dev = ["pytest>=8.3", "pytest-asyncio>=0.24", "respx>=0.22", "ruff>=0.8"]
```

```json
// web/package.json
{
  "engines": { "node": ">=20.0.0" },
  "dependencies": {
    "next": "^14.2.18",
    "react": "^18.3.1",
    "@radix-ui/react-dialog": "^1.1.15"
  },
  "devDependencies": {
    "@next/bundle-analyzer": "^16.2.4",
    "typescript": "^5.6.3",
    "tailwindcss": "^3.4.14",
    "eslint-config-next": "^14.2.18",
    "prettier-plugin-tailwindcss": "^0.6.8"
  }
}
```

---

## 13. 프로젝트 구조

```
kotify/
├── app/                        # FastAPI 백엔드
│   ├── main.py                 # FastAPI 엔트리, lifespan, 라우터
│   ├── config.py               # pydantic-settings (SMS_* prefix)
│   ├── db.py                   # SQLAlchemy engine/session (WAL)
│   ├── models.py               # ORM 모델
│   ├── auth/
│   ├── msghub/                 # U+ msghub 클라이언트
│   │   ├── auth.py             # TokenManager (JWT)
│   │   ├── client.py           # MsghubClient
│   │   ├── schemas.py          # 요청/응답 데이터클래스
│   │   └── codes.py            # 에러 코드 + 비용 계산
│   ├── services/
│   │   ├── compose.py          # 발송 비즈니스 로직
│   │   ├── report.py           # 웹훅 결과 처리
│   │   ├── chat.py             # SSE 스트림
│   │   └── audit.py
│   ├── util/
│   │   ├── phone.py            # 전화번호 정규화
│   │   ├── text.py             # EUC-KR byte 길이·지원 문자 검증
│   │   └── csv_safe.py         # CSV formula injection 방어
│   └── routes/
│       ├── webhook.py          # msghub 웹훅 수신
│       ├── campaigns.py, ...
├── alembic/                    # 마이그레이션
├── web/                        # Next.js 14 프론트엔드
│   ├── app/                    # App Router
│   ├── components/             # UI + motion primitives
│   ├── lib/                    # fetch helper, cn, etc.
│   ├── types/                  # 공유 타입 (campaign, report, ...)
│   ├── middleware.ts           # Keycloak guard
│   ├── next.config.mjs         # rewrites + bundle analyzer
│   └── package.json
├── tests/                      # pytest (backend)
├── deploy/                     # 배포 자산
│   ├── ct-bootstrap.sh
│   ├── kotify.service, kotify-web.service
│   ├── kotify-sudoers, kotify-update.sh
│   ├── sms-backup.sh, sms-backup.cron
│   └── npm-config.md
├── claudedocs/                 # 본 문서 및 msghub 가이드, 감사 문서
├── pyproject.toml
├── README.md, CHANGELOG.md, CONTRIBUTING.md, SECURITY.md, HANDOFF.md
└── LICENSE
```

---

## 14. 테스트 전략

### 14.1 백엔드 (pytest)

- `app/util/phone.py` — 입력 형식 다양하게
- `app/util/csv_safe.py` — formula injection 방어 케이스
- `app/msghub/auth.py` — TokenManager (JWT 만료/갱신/stampede)
- `app/msghub/client.py` — respx로 msghub API mock (발송 성공/실패/429/웹훅 매칭)
- `app/routes/webhook.py` — 서명 검증 통과/실패

### 14.2 프론트엔드

- `pnpm typecheck` — TS 컴파일
- `pnpm lint` — ESLint + jsx-a11y/strict
- `pnpm build` — Next.js 프로덕션 빌드 (가장 넓은 에러 탐지)

### 14.3 E2E 수동

- [`E2E-CHECKLIST.md`](./E2E-CHECKLIST.md) 참조

---

## 15. 운영 체크리스트 (요약)

### 출시 전

- [ ] msghub 계정 + API Key/Password + RCS 브랜드/챗봇 등록 확인
- [ ] Keycloak realm `sms-sys` + client + 역할 + Redirect URI
- [ ] CT 생성 + NTP 동기화
- [ ] NPM에 `sms.example.com` 호스트 등록 + SSL + SSE 설정
- [ ] ct-bootstrap.sh 실행 → 두 systemd 서비스 기동 확인
- [ ] Setup Wizard 진행 → master.key 백업
- [ ] 본인 번호로 RCS→SMS fallback E2E 테스트
- [ ] 백업 cron 설정

### 정기 운영

- [ ] 주 1회 백업 파일 존재 확인
- [ ] 월 1회 msghub 발신번호/브랜드 유효기간 확인
- [ ] 분기 1회 백업 복구 테스트

---

## 16. 결정사항

| # | 항목 | 결정 |
|---|---|---|
| 1 | 잘못된 번호 정책 | **차단** — 하나라도 invalid면 발송 불가 |
| 2 | Keycloak realm/client | `sms-sys` |
| 3 | 운영 도메인 | `sms.example.com` |
| 4 | 발신번호 관리 | msghub 포털 등록 번호를 admin UI에서 직접 추가 |
| 5 | 광고성(`AD`) 발송 | 1차 제외 |
| 6 | 결과 동기화 | **msghub 웹훅** (폴링 제거) |
| 7 | 시크릿 관리 | 마스터 키(파일 1개) + DB Fernet 암호화 + Setup wizard |
| 8 | 프론트엔드 스택 | Next.js 14 App Router (RSC-first) |
| 9 | 외부 대면 포트 | Next.js 3000만 — FastAPI 8080은 내부 전용 |
| 10 | 모션 예산 | 페이지당 1.2초 이내 (Phase 10c) |

---

## 17. 진행 기록 (Phase)

| Phase | 내용 | 완료 |
|---|---|---|
| NCP→msghub 마이그레이션 | `app/ncp/` 전량 제거, `app/msghub/` 신설 | ✅ |
| 1~4 | Next.js 스캐폴드 + 컴포넌트 프리미티브 + 모션 + 레이아웃/auth | ✅ |
| 5~9 | 18개 화면 포팅 (Dashboard부터 Error 3종까지) | ✅ |
| 10a | jsx-a11y/strict — 14 이슈 해결 | ✅ |
| 10b | `@next/bundle-analyzer` + 번들 스냅샷 문서화 | ✅ |
| 10c | 모션 1.2s 예산 감사 + 6곳 압축, `motion-timing.md` 매트릭스 | ✅ |
| 10d | 실 브라우저 런타임 감사 (Lighthouse/CLS/60fps/axe/reduced-motion) | ⏳ 배포 후 |
| 11 | Proxmox CT 배포 + Keycloak/msghub 실연결 + Setup Wizard E2E | ⏳ 다음 |

---

## 부록 A. 출처

| 주제 | URL |
|---|---|
| msghub 개요 | https://docs2.msghub.uplus.co.kr/api/intro |
| Keycloak OIDC | https://www.keycloak.org/docs/latest/securing_apps/ |
| Next.js App Router | https://nextjs.org/docs/app |
| Radix UI Primitives | https://www.radix-ui.com/primitives/docs |
| WCAG 2.1 AA | https://www.w3.org/TR/WCAG21/ |
| CWE-1236 (CSV Injection) | https://cwe.mitre.org/data/definitions/1236.html |

## 부록 B. 관련 문서

- [`HANDOFF.md`](../HANDOFF.md) — 현재 진행 상황 요약
- [`E2E-CHECKLIST.md`](./E2E-CHECKLIST.md) — 배포/운영 검증
- [`msghub-api-guide.md`](./msghub-api-guide.md) — msghub API 전체
- [`msghub-migration-spec.md`](./msghub-migration-spec.md) — 마이그레이션 기획
- [`msghub-error-codes.md`](./msghub-error-codes.md) — 에러 코드 매핑
- [`motion-timing.md`](./motion-timing.md) — 모션 타이밍 매트릭스
- [`web-bundle-snapshot.md`](./web-bundle-snapshot.md) — 번들 스냅샷
- [`phase-10d-runtime-audit.md`](./phase-10d-runtime-audit.md) — 런타임 감사 체크리스트
