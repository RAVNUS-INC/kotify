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

### 4.3 messages[] 응답 필드
| Field | 설명 |
|---|---|
| `requestId` | |
| `messageId` | |
| `requestTime` | |
| `to` | 수신번호 |
| `from` | 발신번호 |
| `completeTime` | 완료 시각 |
| `telcoCode` | 통신사 |
| `status` | **READY / PROCESSING / COMPLETED** (발송 서버 처리 단계) |
| `statusCode` | 수신 결과 코드 (`0`, `3001`, `3023` 등) |
| `statusName` | success / fail (단말 수신) |
| `statusMessage` | 사람이 읽을 수 있는 사유 |

### 4.4 status vs statusName 구분 (매우 중요)
- `status`: 발송 서버 처리 단계 (READY → PROCESSING → COMPLETED)
- `statusName`: 단말 수신 성공/실패 (`status=COMPLETED` 후 채워짐)
- **`status=COMPLETED` ≠ 성공.** 진짜 성공은 `statusName=success` AND `statusCode=0`.

### 4.5 시간 윈도우 제약
- `requestStartTime` ~ `requestEndTime`: 최대 30일
- `completeStartTime` ~ `completeEndTime`: 최대 24시간
- 이력 보관: API 90일 / 콘솔 30일

### 4.6 수신결과 코드 (주요)
| Code | 분류 | 설명 |
|---|---|---|
| `0` | success | 성공 |
| `2000` | failure | Delivery timeout |
| `2001-2002` | failure | 통신망 실패 |
| `2003` | failure | 단말 전원 OFF |
| `2004` | failure | 단말 버퍼 풀 |
| `2005` | failure | 음영지역 |
| `3000` | invalid | Delivery unavailable |
| `3001` | invalid | **결번** |
| `3002` | invalid | 성인 인증 실패 |
| `3003` | invalid | **수신번호 형식 오류** |
| `3008` | invalid | 단말 문제 |
| `3009` | invalid | 메시지 형식 오류 |
| `3012` | invalid | 스팸 분류 |
| `3017` | invalid | 발신번호 스푸핑 방지 위반 |
| `3018` | invalid | 발신번호 스푸핑 방지 가입 번호 |
| `3019` | invalid | KISA 차단 발신번호 |
| `3022` | invalid | Charset 변환 오류 |
| `3023` | invalid | **사전 등록 안 된 발신번호** |

EMMA 코드: `E901` 수신번호 없음, `E904` 본문 없음, `E915` 중복 메시지, `E916/E917` 차단 번호.

출처: https://api.ncloud-docs.com/docs/en/sens-sms-list, https://api.ncloud-docs.com/docs/en/sens-sms-get

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
