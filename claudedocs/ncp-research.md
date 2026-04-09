# NCP SENS SMS v2 — 공식 문서 기반 통합 조사 보고서

> 모든 인용은 `api.ncloud-docs.com`(API 가이드) 및 `guide.ncloud-docs.com`(사용 가이드)의 공식 문서에서 가져왔으며, 비공식 블로그는 인용하지 않았습니다.
> 작성일: 2026-04-08

---

## 0. 가장 중요한 사실 (먼저 읽기)

1. **`messages` 배열은 한 번에 최대 1,000명이 아니라 100명입니다.** 1,000명에게 발송하려면 클라이언트에서 100건씩 청크 분할 필수.
2. **이력 보관 기간**: 콘솔 30일 / API 90일.
3. **v2에는 webhook/callback이 존재하지 않습니다.** 결과 동기화는 GET 폴링이 유일.

---

## 1. 인증 (HMAC-SHA256)

### 1.1 필수 헤더
| Header | 값 | 비고 |
|---|---|---|
| `x-ncp-apigw-timestamp` | epoch milliseconds (string) | 5분 이상 drift 시 invalid |
| `x-ncp-iam-access-key` | Access Key ID | |
| `x-ncp-apigw-signature-v2` | Base64(HMAC-SHA256) | |
| `Content-Type` | `application/json` | |

### 1.2 시그니처 알고리즘
```
{METHOD} {URI_WITH_QUERY}\n{TIMESTAMP}\n{ACCESS_KEY}
```
- METHOD/URI 사이는 공백 1개, 그 외는 LF.
- URI는 host 제외, querystring 포함.
- secret_key (UTF-8) 로 HMAC-SHA256 → Base64.

### 1.3 함정
- **timestamp는 한 번만 생성**해서 헤더와 signing string에 동일하게 사용.
- URI에는 querystring 포함 필수.
- NTP 동기화 필수.

출처: https://api.ncloud-docs.com/docs/en/common-ncpapi

---

## 2. 사전 준비

### 2.1 SENS / Project / Service ID
- 콘솔: Services → Application Services → SENS
- `useSms: true`로 Project 생성 → `smsService.serviceId` (예: `ncp:sms:kr:5051:sens`) 확보

### 2.2 발신번호 등록 (필수)
- 콘솔: SMS → Calling Number → 발신번호 등록
- 서류 인증: 통신서비스 이용증명원 등 PDF/JPG/PNG (총 10MB 이내)
- **승인 소요: 영업일 3-4일**
- 미등록 번호 사용 시 수신결과코드 `3023`

### 2.3 SMS / LMS / MMS 글자수 제한 (byte 단위)
| 타입 | content | subject | 첨부 |
|---|---|---|---|
| SMS | 0-90 byte | 사용 불가 | 불가 |
| LMS | 0-2,000 byte | 0-40 byte | 불가 |
| MMS | 0-2,000 byte | 0-40 byte | 가능 |

- **EUC-KR 인코딩 기준**. 이모지 발송 시 실패 가능.
- 한글 1자 = 2 byte → SMS 한글 약 45자, LMS 약 1,000자.

---

## 3. 발송 API

```
POST https://sens.apigw.ntruss.com/sms/v2/services/{serviceId}/messages
```

### 3.1 Request Body
| Field | Type | Required | Description |
|---|---|---|---|
| `type` | String | Required | SMS / LMS / MMS |
| `contentType` | String | Optional | COMM (기본) / AD |
| `countryCode` | String | Optional | 기본 82 |
| `from` | String | Required | **등록된 발신번호만** |
| `subject` | String | Optional | LMS/MMS 전용 |
| `content` | String | Required | 기본 본문 |
| `messages` | Array | Required | **최대 100건** |
| `files` | Array | Optional | MMS 전용 |
| `reserveTime` | String | Optional | `YYYY-MM-DD HH:mm` |
| `reserveTimeZone` | String | Optional | 기본 Asia/Seoul |

### 3.2 messages[] 서브 스키마
| Field | Required | 비고 |
|---|---|---|
| `to` | Required | 숫자만 |
| `subject` | Optional | 개별 제목 (LMS/MMS) |
| `content` | Optional | 개별 본문, 기본값보다 우선 |

**치환변수 없음**. 수신자별 다른 본문은 클라이언트에서 미리 렌더링한 문자열을 직접 넣어야 함.

### 3.3 Response (성공 HTTP 202)
```json
{
  "requestId": "RSLA-...",
  "requestTime": "2025-11-25T09:39:40.535",
  "statusCode": "202",
  "statusName": "success"
}
```

**중요: Send 응답에 `messageId`가 포함되지 않음.** `requestId`로 list API를 호출해야 messageId 확보 가능.

출처: https://api.ncloud-docs.com/docs/en/sens-sms-send

---

## 4. 발송 결과 조회 API

### 4.1 단건 조회 (messageId)
```
GET /sms/v2/services/{serviceId}/messages/{messageId}
```

### 4.2 목록 조회 (requestId 기반 — 폴링용 핵심)
```
GET /sms/v2/services/{serviceId}/messages?requestId={requestId}
```

`pageSize`가 `requestId` 입력 시 자동 1000으로 설정되어 단일 페이지에 100건 모두 들어옴.

### 4.3 최상위 응답 필드 (단건 조회 기준)
| Field | Type | Required | 설명 |
|---|---|---|---|
| `statusCode` | String | Required | HTTP 상태 코드 (`200` 성공, 그 외 실패) |
| `statusName` | String | Required | `success` / `reserved` / `fail` |
| `messages` | Array | Required | 메시지 정보 배열 |

> ⚠️ **주의:** 최상위 `statusCode`/`statusName`(API 호출 성공 여부)과 `messages[].statusCode`/`statusName`(단말 수신 결과)은 **완전히 다른 의미**다. 이름이 같아서 혼동되기 쉬움.

### 4.4 messages[] 응답 필드 (단건/목록 공통)
| Field | Type | Required | 설명 |
|---|---|---|---|
| `requestId` | String | Required | 요청 아이디 |
| `messageId` | String | Required | 메시지 아이디 |
| `requestTime` | String | Required | `YYYY-MM-dd HH:mm:ss` |
| `contentType` | String | Required | `COMM`(일반) / `AD`(광고) |
| `type` | String | Required | `SMS` / `LMS` / `MMS` |
| `subject` | String | Required | 메시지 제목 |
| `content` | String | Required | 메시지 내용 |
| `countryCode` | String | Required | 국가 코드 |
| `from` | String | Required | 발신 번호 |
| `to` | String | Required | 수신 번호 |
| `completeTime` | String | Optional | `YYYY-MM-dd HH:mm:ss` |
| `telcoCode` | String | Optional | 통신사 코드 (ETC 등) |
| `files` | Array | Optional | 첨부 파일 목록 (`fileId`, `name`) |
| `status` | String | Required | **`READY` / `PROCESSING` / `COMPLETED`** (발송 서버 처리 단계) |
| `statusCode` | String | Optional | **수신 결과 코드** (아래 4.7 참조) |
| `statusName` | String | Optional | `success` / `fail` (단말 수신 결과) |
| `statusMessage` | String | Optional | 사람이 읽을 수 있는 사유 |

### 4.5 status vs statusName 구분 (매우 중요)
- `messages[].status`: 발송 서버 처리 단계 (READY → PROCESSING → COMPLETED)
- `messages[].statusName`: 단말 수신 성공/실패 (`status=COMPLETED` 후 채워짐)
- **`status=COMPLETED` ≠ 성공.** 진짜 성공은 `statusName=success` AND `statusCode=0`.
- 최상위 `statusName`에는 `reserved` 값이 존재 → 예약 발송 건 구분용 (messages[] 레벨에는 없음).

### 4.6 시간 윈도우 제약
- `requestStartTime` ~ `requestEndTime`: 최대 30일
- `completeStartTime` ~ `completeEndTime`: 최대 24시간
- 이력 보관: API 90일 / 콘솔 30일

### 4.7 수신 결과 코드 (EMMA v3.5.1+)

공식 문서는 수신 결과 코드를 **3개 계층**으로 분리한다:
1. **IB G/W Report Code**: 이통사에 메시지를 전송한 후 반환되는 결과 코드 (최종 단말 결과)
2. **IB G/W Response Code**: 중계사 게이트웨이가 메시지를 수신한 후 반환하는 결과 코드
3. **IB EMMA Code**: EMMA가 메시지 전송 요청을 처리하는 과정에서 발생한 오류 코드

#### 4.7.1 IB G/W Report Code (이통사 → 단말 최종 결과)

| Code | 분류 | 설명 |
|---|---|---|
| `0` | success | 성공 |
| `2000` | failure | 전송 시간 초과 |
| `2001` | failure | 전송 실패 (무선망단) |
| `2002` | failure | 전송 실패 (무선망 → 단말기단) |
| `2003` | failure | 단말기 전원 꺼짐 |
| `2004` | failure | 단말기 메시지 버퍼 풀 |
| `2005` | failure | 음영지역 |
| `2006` | failure | 메시지 삭제됨 |
| `2007` | failure | 일시적인 단말 문제 |
| `3000` | Invalid | 전송할 수 없음 |
| `3001` | Invalid | **가입자 없음 (결번)** |
| `3002` | Invalid | 성인 인증 실패 |
| `3003` | Invalid | **수신 번호 형식 오류** |
| `3004` | Invalid | 단말기 서비스 일시 정지 |
| `3005` | Invalid | 단말기 호 처리 상태 |
| `3006` | Invalid | 착신 거절 |
| `3007` | Invalid | Callback URL을 받을 수 없는 폰 |
| `3008` | Invalid | 기타 단말기 문제 |
| `3009` | Invalid | 메시지 형식 오류 |
| `3010` | Invalid | MMS 미지원 단말 |
| `3011` | Invalid | 서버 오류 |
| `3012` | Invalid | 스팸 |
| `3013` | Invalid | 서비스 거부 |
| `3014` | Invalid | 기타 |
| `3015` | Invalid | 전송 경로 없음 |
| `3016` | Invalid | 첨부 파일 사이즈 제한 실패 |
| `3017` | Invalid | 발신 번호 변작 방지 세칙 위반 |
| `3018` | Invalid | 발신 번호 변작 방지 서비스에 가입된 휴대폰 개인가입자 번호 |
| `3019` | Invalid | KISA/미래부 차단 요청 발신 번호 |
| `3022` | Invalid | Charset Conversion Error |
| `3023` | Invalid | **발신 번호 사전등록제를 통해 등록되지 않은 번호** |

#### 4.7.2 IB G/W Response Code (중계사 게이트웨이)

| Code | 설명 |
|---|---|
| `1001` | Server Busy (RS 내부 저장 Queue Full) |
| `1002` | 수신 번호 형식 오류 |
| `1003` | 회신번호 형식 오류 |
| `1004` | 스팸 |
| `1005` | 사용 건수 초과 |
| `1006` | 첨부 파일 없음 |
| `1007` | 첨부 파일 있음 |
| `1008` | 첨부 파일 저장 실패 |
| `1009` | CLIENT_MSG_KEY 없음 |
| `1010` | CONTENT 없음 |
| `1011` | CALLBACK 없음 |
| `1012` | RECIPIENT_INFO 없음 |
| `1013` | SUBJECT 없음 |
| `1014` | 첨부 파일 키 없음 |
| `1015` | 첨부 파일 이름 없음 |
| `1016` | 첨부 파일 크기 없음 |
| `1017` | 첨부 파일 Content 없음 |
| `1018` | 전송 권한 없음 |
| `1019` | TTL 초과 |
| `1020` | charset conversion error |
| `S000` | 중계사 요청 실패 (서버 오류) |
| `S001` | 중계사 요청 실패 (서버 오류) |
| `S002` | 중계사 요청 실패 (잘못된 요청) |
| `S003` | 중계사 요청 실패 (스팸 처리) |
| `S004` | 쿼터 초과 |
| `S005` | 잘못된 MMS 파일 |
| `S006` | MMS 파일을 찾을 수 없음 |
| `S007` | MMS 파일 만료 |
| `S008` | MMS 파일 크기 초과 |
| `S009` | MMS 파일 해상도 초과 |
| `S010` | MMS 파일 업로드 쿼터 초과 |
| `S011` | MMS 파일 업로드 실패 |
| `S012` | 발신 번호 세칙 오류 |
| `S998` | 예기치 못한 서버 오류 |
| `S999` | 기타 오류 |

#### 4.7.3 IB EMMA Code (NCP EMMA 내부 검증)

| Code | 설명 |
|---|---|
| `E900` | Invalid - IB 전송키가 없는 경우 |
| `E901` | 수신 번호가 없는 경우 |
| `E902` | 동보인 경우, 수신 번호 순번이 없는 경우 |
| `E903` | 제목이 없는 경우 |
| `E904` | 메시지가 없는 경우 |
| `E905` | 회신번호가 없는 경우 |
| `E906` | 메시지 키가 없는 경우 |
| `E907` | 동보 여부가 없는 경우 |
| `E908` | 서비스 타입이 없는 경우 |
| `E909` | 전송 요청 시각이 없는 경우 |
| `E910` | TTL 타임이 없는 경우 |
| `E911` | MMS MT인데 첨부 파일 확장자가 없는 경우 |
| `E912` | MMS MT인데 attach_file 폴더에 첨부 파일이 없는 경우 |
| `E913` | MMS MT인데 첨부 파일 사이즈가 0인 경우 |
| `E914` | MMS MT인데 파일 그룹 키는 있으나 파일 테이블에 데이터가 없는 경우 |
| `E915` | **중복 메시지** |
| `E916` | **인증 서버 차단 번호** |
| `E917` | **고객 DB 차단 번호** |
| `E918` | USER CALLBACK FAIL |
| `E919` | 발송 제한 시간인 경우, 메시지 재발송 처리 금지 |
| `E920` | LMS MT인데 메시지 테이블에 파일 그룹 키가 있는 경우 |
| `E921` | MMS MT인데 메시지 테이블에 파일 그룹 키가 없는 경우 |
| `E922` | 동보 단어 제약 문자 사용 오류 |
| `E999` | 기타 오류 |

#### 4.7.4 재시도 분류 권장

| 계층 | 분류 | 재시도 가능성 |
|---|---|---|
| Report `0` | success | — (종결) |
| Report `2xxx` | 일시적 네트워크/단말 장애 | ✅ 재시도 유효 |
| Report `3xxx` | 영구적 번호/메시지/정책 오류 | ❌ 재시도 무의미 |
| Response `1xxx` | 요청 형식/쿼터/권한 오류 | ❌ 수정 후 재전송 |
| Response `S0xx` | 중계사 서버 오류 | ⚠️ backoff 후 재시도 |
| Response `S9xx` | 알 수 없는 서버 오류 | ⚠️ backoff 후 재시도 |
| EMMA `E9xx` | 전송 요청 데이터 누락/검증 실패 | ❌ 수정 후 재전송 |
| EMMA `E915` | 중복 | ❌ 재시도 금지 (동일 key 거부됨) |
| EMMA `E916/E917` | 차단 번호 | ❌ 재시도 금지 (차단 해제 필요) |

출처:
- https://api.ncloud-docs.com/docs/en/sens-sms-get (메시지 발송 결과 조회, 단건)
- https://api.ncloud-docs.com/docs/en/sens-sms-list (메시지 발송 목록 조회)

---

## 5. 예약 발송

### 5.1 예약 발송
- 발송 시 `reserveTime` (`YYYY-MM-DD HH:mm`) + `reserveTimeZone` 지정.
- 예약 ID = 발송 응답의 `requestId`.

### 5.2 예약 상태 조회
```
GET /sms/v2/services/{serviceId}/reservations/{reserveId}/reserve-status
```

`reserveStatus`: `READY / PROCESSING / CANCELED / FAIL / DONE / STALE / SKIP`

### 5.3 예약 취소
```
DELETE /sms/v2/services/{serviceId}/reservations/{reserveId}
```
성공: `204 No Content`

---

## 6. 에러 코드

### 6.1 NCP 공통 HTTP 코드
| HTTP | Code | 의미 |
|---|---|---|
| 200 | - | OK |
| 202 | - | Accepted (Send 성공) |
| 204 | - | No Content (취소 성공) |
| 400 | 100 | Bad Request (스키마/발신번호 미등록 등) |
| 401 | 200 | 인증 실패 (서명/timestamp) |
| 401 | 210 | Permission Denied |
| 403 | - | Forbidden (serviceId 권한) |
| 404 | 300 | Not Found |
| 413 | 430 | Request Entity Too Large |
| 429 | 400/410/420 | Rate/Throttle/Quota |
| 500 | 900 | Unexpected |
| 503 | 500 | Endpoint Error |
| 504 | 510 | Endpoint Timeout |

### 6.2 에러 응답 예시
```json
{ "status": 403, "error": "Forbidden", "message": "Do not have access to this 'serviceId'" }
```

---

## 7. Webhook/Callback — 없음 (재확인)

SENS v2 SMS API의 모든 엔드포인트:
- Send message
- Get message delivery list
- Get message delivery result
- Get message reservation status
- Cancel message reservation
- Register/Get/Delete call block number
- Upload Attachment

**콜백 URL 등록 / 이벤트 구독 엔드포인트가 존재하지 않음.** 결과 동기화는 GET 폴링이 유일.

### 권장 폴링 패턴
1. 발송 후 즉시 `GET /messages?requestId=...` 1회 → 100건의 messageId 수집
2. Backoff: 5초 → 15초 → 30초 → 1분 → 5분 → 30분
3. 모든 row의 `status=COMPLETED` 도달 시 종료
4. 1시간 경과 시 미완료는 TIMEOUT 처리
5. 백필 필요 시 `requestStartTime`/`requestEndTime` 범위 조회 (30일 이내)

---

## 8. Rate Limit / 청크 분할 / 사용 한도

### 8.1 Rate Limit
- 공식 문서에 RPS/QPS 숫자 명시 없음
- `429` 응답 정의됨 → exponential backoff

### 8.2 청크 분할 (구현 가이드)
- **한 호출당 messages ≤ 100건**
- 1,000명 발송 = 100건 × 10회
- 호출 간 100-300ms 간격
- 429 시 backoff

### 8.3 SMS 사용 한도 (콘솔 정책)
- 국내 SMS: 기본 **월 최대 10,000건** (SMS/LMS/MMS 합산)
- 국제 SMS: 기본 **월 최대 500건**
- 초과 필요 시 고객지원 문의

### 8.4 단가
- 공식 페이지에 숫자 미공개. 콘솔 요금 계산기 또는 영업 문의 필요.

---

## 9. 한국 전화번호 형식

### 9.1 NCP 입력 포맷
- `from`, `to`: **숫자만** (`-` 등 구분자 없이)
- 예: `01012345678`

### 9.2 국가코드
- `countryCode` 필드와 `to`가 분리됨
- 한국: `countryCode: "82"` + `to: "01012345678"` (국가코드를 to에 붙이지 않음)

### 9.3 잘못된 번호 처리
- 공식 문서에 명시 없음
- 결과 조회 응답이 번호별로 별도 statusCode를 갖는 구조 → 부분 성공/실패 처리되는 것으로 추정
- 클라이언트 사전 검증 권장: `^01[016789]\d{7,8}$`

---

## 10. 알려진 함정 (공식 문서로 확인된 것만)

1. **Timestamp 일관성**: 헤더와 시그니처 계산이 동일 변수여야 함
2. **5분 timestamp drift** → NTP 필수
3. **EUC-KR 기반** → 이모지 실패
4. **MMS인데 첨부 없음 → 자동 LMS 전환**
5. **subject/content는 byte 단위**
6. **발신번호 사전 등록 (3-4영업일)** 필수
7. **messages 100건 한도** (1,000 아님)
8. **콘솔 30일 vs API 90일** 보관
9. **status=COMPLETED ≠ 성공**
10. **Send 응답에 messageId 없음** → list 호출 필수
11. **시간 윈도우 비대칭**: requestTime 30일 / completeTime 24시간
12. **광고용 AD**: 080 수신거부 + 본문 끝 안내 (정보통신망법 50조)

---

## 11. 명시적 미확인 항목

공식 문서에서 답을 찾지 못한 사항 (운영 전 NCP 영업/지원 확인 권장):

1. 국내 SMS/LMS/MMS 정확한 원화 단가
2. API 호출의 구체적 RPS/QPS 한도 숫자
3. 발송 요청 1건에 잘못된 번호 포함 시 전체 거부 vs 부분 처리 동작
4. `scheduleCode` 필드의 SMS v2 사용 여부 (스키마에 없음)
5. 광고용 AD 발송 시 080 수신거부 자동 부착 여부

---

## 12. 출처 (전체)

| 주제 | URL |
|---|---|
| SENS overview | https://api.ncloud-docs.com/docs/en/sens-overview |
| Send message | https://api.ncloud-docs.com/docs/en/sens-sms-send |
| Get message list | https://api.ncloud-docs.com/docs/en/sens-sms-list |
| Get message result | https://api.ncloud-docs.com/docs/en/sens-sms-get |
| Reservation status | https://api.ncloud-docs.com/docs/en/sens-sms-reservation-status-get |
| Cancel reservation | https://api.ncloud-docs.com/docs/en/sens-sms-reservation-delete |
| 공통 API (시그니처) | https://api.ncloud-docs.com/docs/en/common-ncpapi |
| Project create | https://api.ncloud-docs.com/docs/en/sens-project-create |
| 발신번호 가이드 | https://guide.ncloud-docs.com/docs/sens-callingno |
| SMS 사용 가이드 | https://guide.ncloud-docs.com/docs/sens-smsmessage |
| 상품 페이지 | https://www.ncloud.com/product/applicationService/sens |
