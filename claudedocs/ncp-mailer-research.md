# NCP Cloud Outbound Mailer 통합 조사 보고서

**조사일**: 2026-04-08
**대상 서비스**: NAVER Cloud Platform — Cloud Outbound Mailer (API v1)
**목적**: `kotify` 프로젝트의 이메일 발송 모듈(`app/ncp/mailer.py`, `app/services/sender/email.py`) 설계 근거 수집
**참고 기준**: 기존 SENS SMS v2 통합(`app/ncp/client.py`, `app/ncp/signature.py`)과의 재사용 가능성 검증

> 본 문서는 NAVER Cloud 공식 API 가이드 및 사용 가이드만을 근거로 작성되었습니다.
> v2 API 문서는 현 시점(2026-04)에 공식 페이지에 존재하지 않으며, **모든 엔드포인트는 `api/v1` 기준입니다.**

---

## 결론 요약 (TL;DR)

| 항목 | 결론 |
|---|---|
| **HMAC-SHA256 시그니처 알고리즘** | **SMS(SENS)와 100% 동일**. `signing string = "{METHOD} {URI}\n{TIMESTAMP}\n{ACCESS_KEY}"`, HMAC-SHA256 + Base64. |
| **호스트** | `https://mail.apigw.ntruss.com` (sens.apigw.ntruss.com과 **다른 호스트**) |
| **베이스 경로** | `/api/v1` (KR), `/api/v1-sgn`, `/api/v1-jpn` |
| **필수 헤더** | `x-ncp-apigw-timestamp`, `x-ncp-iam-access-key`, `x-ncp-apigw-signature-v2`, `Content-Type: application/json` — **SMS와 동일한 4종** |
| **발송 엔드포인트** | `POST /api/v1/mails` |
| **1회 호출 최대 수신자** | **100,000명** (`recipientGroupFilter` 사용 시 초과 가능) |
| **성공 응답 코드** | HTTP **201** (SMS는 202) — `raise_for_status` 재사용 시 주의 |
| **수신자별 본문 치환** | `recipients[].parameters` 로 개별 지정 가능 (`individual: true` 필요) |
| **첨부파일** | `POST /api/v1/files` 로 선(先) 업로드 → `attachFileIds` 배열에 `fileId` 전달 (총 20 MB 이하, 개별 10 MB 이하) |
| **예약 발송** | `reservationUtc` (Long, epoch ms) 또는 `reservationDateTime` (yyyy-MM-dd HH:mm, KST) |
| **발신 이메일 사전 등록** | 자유 도메인 허용. **단, 콘솔에서 도메인 등록 + SPF/DKIM/DMARC 인증 필수 권장**. 미인증 도메인은 수신측에서 스팸 처리 가능. 일부 도메인(naver.com, navercorp.com, ncloud.com)은 발신 도메인으로 사용 불가. |
| **Webhook/Callback** | **공식 문서에서 확인되지 않음** (SMS와 동일하게 폴링 기반으로 추정) |
| **이력 보관 기간** | 콘솔 기준 **최근 2개월** 조회 가능 (사용 가이드 기준) |
| **기본 발송 한도** | 월 **1,000,000건** (고객 지원 통해 상향 가능) |
| **발송 요청 한도 계산** | 수신자 수 기준 (100명 발송 = 100건 차감) |

---

## 1. 인증 (Authentication)

### 1.1 핵심 사실

- **시그니처 알고리즘은 SENS SMS와 완전히 동일**합니다. 공식 문서의 샘플 코드(Java/PHP)가 SMS v2 가이드의 샘플과 글자 단위로 일치하며, 차이점은 `url` 변수값이 `/sms/v2/services/.../messages` 대신 `/api/v1/mails`인 것뿐입니다.
- `signing string` 포맷:
  ```
  {HTTP_METHOD}{SPACE}{URI}\n{TIMESTAMP}\n{ACCESS_KEY}
  ```
  - `URI`: 도메인 제외, querystring 포함 전체 경로
  - `TIMESTAMP`: epoch milliseconds (string)
  - Encoding: UTF-8 → HmacSHA256 → Base64
- **필수 헤더 (4종, SMS와 동일)**

  | Header | Description |
  |---|---|
  | `x-ncp-apigw-timestamp` | epoch ms. 현재 시각과 5분 이상 차이 나면 invalid |
  | `x-ncp-iam-access-key` | NCP Portal/Sub Account에서 발급받은 Access Key ID |
  | `x-ncp-apigw-signature-v2` | 위에서 생성한 Base64 signature |
  | `Content-Type` | `application/json` (multipart/form-data는 `/files` 업로드에만 사용) |

- **선택 헤더**: `x-ncp-lang` (응답 메시지 다국어 처리용, `ko-KR` | `en-US` | `zh-CN`, 기본값 `en-US`)

### 1.2 기존 `app/ncp/signature.py` 재사용 결론

**그대로 재사용 가능합니다.** `make_headers(method, uri, access_key, secret_key)` 함수는 호스트/경로에 종속되지 않으므로 변경 없이 Mailer 호출에 그대로 사용할 수 있습니다. 주의할 점은 `uri`에 `/api/v1/mails`처럼 서비스 종류가 다른 경로를 넣어야 한다는 것뿐입니다.

### 1.3 호스트

| Region | Endpoint |
|---|---|
| **Korea (KR)** | `https://mail.apigw.ntruss.com/api/v1` |
| Singapore (SGN) | `https://mail.apigw.ntruss.com/api/v1-sgn/` |
| Japan (JPN) | `https://mail.apigw.ntruss.com/api/v1-jpn/` |

> 기존 SMS 호스트는 `sens.apigw.ntruss.com`이므로 **별도의 `httpx.AsyncClient` 인스턴스가 필요**합니다.

**출처**:
- https://api.ncloud-docs.com/docs/en/ai-application-service-cloudoutboundmailer
- https://api.ncloud-docs.com/docs/ko/ai-application-service-cloudoutboundmailer

---

## 2. 사전 준비 (Prerequisites)

### 2.1 콘솔 활성화

1. NAVER Cloud Platform 콘솔 → **Services > Application Services > Cloud Outbound Mailer**
2. 서비스 이용 신청 (`77202 No subscription` 에러 방지)
3. 기본 프로젝트 생성 확인 (`77301 Default project does not exist` 에러 방지)
4. **Sub Account 권한 관리**를 통해 `NCP_CLOUD_OUTBOUND_MAILER_MANAGER` 권한 부여 가능

### 2.2 발신 이메일 주소 사전 등록 — SMS의 발신번호 등록과 다름

- **SMS**: 발신번호 사전 등록 필수 (법정 의무)
- **Mailer**: `senderAddress`에 **임의의 도메인 사용 가능**. 단, 공식 문서는 다음과 같이 경고합니다:
  - "발신자가 실제로 소유하는 도메인 사용 권고"
  - "DMARC가 적용된 `id@naver.com`과 같은 포털 웹 메일 계정 사용 시 DMARC 검사에 실패하여 수신측 정책에 따라 스팸 처리될 수 있음"
  - **금지 도메인**: `naver.com`, `navercorp.com`, `ncloud.com` 등은 `senderAddress`로 사용 불가

### 2.3 도메인 인증 (SPF / DKIM / DMARC)

콘솔의 **Domain management** 메뉴에서 도메인을 등록하고 DNS TXT 레코드 기반으로 3단계 인증을 수행합니다.

#### 도메인 등록 단계
1. **Register domain** → 도메인 주소 입력 → **Generate authentication token** → DNS TXT에 토큰 등록 → **Authenticate** 클릭 (소유권 확인)

#### SPF
- 콘솔에서 SPF 서명값 확인 후 DNS TXT에 등록
- **주의**: SPF 레코드는 한 도메인당 **1개만** 존재해야 함. 이미 있으면 기존 레코드에 `include:email.ncloud.com` 추가
- 예: `v=spf1 ip4:192.168.0.1 include:spf.example.com include:email.ncloud.com ~all`

#### DKIM
- **2,048-bit** 서명만 지원 (392자, DNS TXT 255자 제한 초과 → 다중 문자열 분할 필수)
- Selector 값은 환경/리전별로 다름 (Private/KR: `ncpcompubkr`, 금융: `ncpcomfin`, 공공: `ncpcomgov`, 2024-11-07 이전 등록분: `mailer`)
- 형식:
  ```
  <selector>._domainkey.<domain> IN TXT "<DKIM signature value>"
  ```

#### DMARC
- SPF/DKIM 인증 이후 설정 권장
- DNS 레코드명: `_dmarc.<domain>`
- 예: `v=DMARC1; p=none; aspf=r; adkim=r; rua=mailto:report@example.com`
- 주요 태그: `v`(필수, `DMARC1`), `p`(필수, `none`|`quarantine`|`reject`), `sp`, `aspf`, `adkim`, `rua`

> **Caution (공식 문서 인용)**: "If all 3 authentication processes — SPF, DKIM, and DMARC — are not completed for specific domains among the recipient email addresses, email delivery to those domains may fail."

**출처**:
- https://guide.ncloud-docs.com/docs/en/cloudoutboundmailer-use-domain
- https://guide.ncloud-docs.com/docs/en/cloudoutboundmailer-start

---

## 3. 발송 API — `createMailRequest`

### 3.1 엔드포인트

| Method | URI | Success |
|---|---|---|
| `POST` | `/api/v1/mails` | **HTTP 201** |

전체 URL (KR): `https://mail.apigw.ntruss.com/api/v1/mails`

> SENS SMS는 HTTP **202 Accepted**로 성공을 반환하지만 Mailer는 **HTTP 201 Created**입니다. `NCPClient._raise_for_status`가 `(200, 202)`만 성공으로 취급하므로 **Mailer용 클라이언트에서는 `(200, 201)`로 수정 필요**합니다.

### 3.2 Request Body 전체 스키마

| Field | Type | Required | Description |
|---|---|---|---|
| `senderAddress` | String | Conditional | 발신자 이메일 주소. `templateSid` 미설정 시 필수. `naver.com/navercorp.com/ncloud.com` 도메인 불가 |
| `senderName` | String | Optional | 발신자 이름 (0~69 Byte) |
| `templateSid` | Integer | Optional | 템플릿 SID. 설정 시 `senderAddress/title/body`는 템플릿에서 계승 |
| `title` | String | Conditional | 이메일 제목 (0~500 Byte). `templateSid` 미설정 시 필수. **치환 태그 `${var}` 사용 가능** |
| `body` | String | Conditional | 이메일 본문 HTML (0~500 KB). `templateSid` 미설정 시 필수. 광고 메일은 수신거부 메시지 포함 계산 |
| `individual` | Boolean | Optional | **`true` (기본값)** \| `false`. `true`: 개인별 발송 (수신자마다 별도 메일 + 개별 `parameters` 치환). `false`: 일반 발송 (한 메일에 여러 수신자) |
| `confirmAndSend` | Boolean | Optional | `true`: 확인 후 발송 (콘솔에서 수동 승인). `false` (권장): 바로 발송 |
| `advertising` | Boolean | Optional | `true`: 광고 메일 (수신 거부 메시지 필수). `false`: 일반 메일 |
| `parameters` | Object (Map) | Optional | **전체 수신자 공통** 치환 파라미터. Key=치환 ID, Value=치환값 |
| `referencesHeader` | String | Optional | `<unique_id@domain.com>` 형식. NAVER Mail 스레드 그룹핑용 |
| `reservationUtc` | Long | Optional | 예약 발송 시각 (epoch ms). 최대 현재+30일. `reservationDateTime`보다 우선 |
| `reservationDateTime` | String | Optional | 예약 발송 시각 (`yyyy-MM-dd HH:mm`, **UTC+9 KST 기준**). 최대 현재+30일 |
| `attachFileIds` | List<String> | Optional | 첨부 파일 ID 배열. `POST /files`로 선 업로드하여 획득. 총용량 20 MB 이하 |
| `recipients` | List<RecipientForRequest> | Conditional | 수신자 목록. `recipientGroupFilter` 미설정 시 필수 |
| `recipientGroupFilter` | RecipientGroupFilter | Optional | 주소록 그룹 기반 발송 필터 (AND/OR 조합) |
| `useBasicUnsubscribeMsg` | Boolean | Optional | `true`(기본): 기본 수신거부 메시지 사용. `false`: `unsubscribeMessage` 필수 |
| `unsubscribeMessage` | String | Conditional | 사용자 정의 수신거부 메시지. `useBasicUnsubscribeMsg=false` 시 필수. 본문에 `#{UNSUBSCRIBE_MESSAGE}` 태그로 위치 지정 가능. `body`와 합산 500 KB 이하 |

#### RecipientForRequest 스키마

| Field | Type | Required | Description |
|---|---|---|---|
| `address` | String | **Required** | 수신자 이메일 (RFC 형식) |
| `name` | String | Optional | 수신자 이름 (최대 69자) |
| `type` | String | **Required** | **`R`**(수신자, 기본값) \| `C`(참조 CC) \| `B`(숨은 참조 BCC) |
| `parameters` | Object (Map) | Optional | **수신자별 치환 파라미터** (개인별 본문 치환 핵심) |

> **중요**: `individual: true` 일 때만 `recipients[].parameters`가 수신자별로 적용됩니다. `individual: false`면 `C/B` 타입도 허용되지만 개별 치환은 작동하지 않습니다.

### 3.3 제약 사항 (공식 문서 직접 인용)

- 한 번에 최대 **100,000명**에게 발송 가능. 내부적으로 **30건씩 나누어 비동기 처리**
- `recipientGroupFilter` 사용 시 100,000명 초과 가능
- **참조(CC)/숨은참조(BCC)는 각각 최대 30명**
- 이메일 본문 최대 **500 KB**
- **기본 월 발송 한도 1,000,000건** (상향 가능)
- 발송 요청 한도는 **수신자 수 기준** (100명 = 100건 차감)

### 3.4 Request 예시 (템플릿 없이, 개인별 치환)

```bash
curl --location --request POST 'https://mail.apigw.ntruss.com/api/v1/mails' \
  --header 'x-ncp-apigw-timestamp: {Timestamp}' \
  --header 'x-ncp-iam-access-key: {Access Key}' \
  --header 'x-ncp-apigw-signature-v2: {Signature}' \
  --header 'Content-Type: application/json' \
  --data-raw '{
    "senderAddress": "no_reply@company.com",
    "senderName": "Kotify",
    "title": "${customer_name}님 반갑습니다.",
    "body": "<p>귀하의 등급이 ${BEFORE_GRADE}에서 ${AFTER_GRADE}로 변경되었습니다.</p>",
    "recipients": [
      {
        "address": "hongildong@example.com",
        "name": "홍길동",
        "type": "R",
        "parameters": {
          "customer_name": "홍길동",
          "BEFORE_GRADE": "SILVER",
          "AFTER_GRADE": "GOLD"
        }
      },
      {
        "address": "chulsoo@example.net",
        "name": null,
        "type": "R",
        "parameters": {
          "customer_name": "철수",
          "BEFORE_GRADE": "BRONZE",
          "AFTER_GRADE": "SILVER"
        }
      }
    ],
    "individual": true,
    "advertising": false
  }'
```

### 3.5 Response Body 스키마

| Field | Type | Required | Description |
|---|---|---|---|
| `requestId` | String | **Required** | 발송 요청 ID. 여러 `mailId`를 포함할 수 있음. 폴링 및 상세 조회의 기준 키 |
| `count` | Integer | **Required** | 이메일 발송 요청 건수 (= 수신자 수) |

#### Response 예시

```json
{
  "requestId": "20181203000000000201",
  "count": 10000
}
```

> **주의**: SMS v2와 달리 Mailer의 발송 응답에는 `statusCode/statusName/requestTime`이 **없습니다**. `requestId` + `count`만 반환됩니다. 발송 상세 상태는 별도 조회 API를 사용해야 합니다.

**출처**:
- https://api.ncloud-docs.com/docs/ko/ai-application-service-cloudoutboundmailer-createmailrequest
- https://api.ncloud-docs.com/docs/common-vapidatatype-nesrecipientrequest

---

## 4. 발송 결과 조회 API

Mailer는 SMS와 달리 **4개의 독립 조회 엔드포인트**를 제공합니다.

### 4.1 요청 단위 상태 조회 — `getMailRequestStatus` (가장 권장되는 폴링 대상)

| Method | URI |
|---|---|
| `GET` | `/api/v1/mails/requests/{requestId}/status` |

#### Response Body

| Field | Type | Description |
|---|---|---|
| `requestId` | String | 발송 요청 ID |
| `readyCompleted` | Boolean | DB 적재 완료 여부. `true`면 모든 요청이 발송 준비 완료 (발송 완료 포함) |
| `allSentSuccess` | Boolean | 모든 발송 성공 여부 |
| `requestCount` | Integer | 요청 총 건수 |
| `sentCount` | Integer | 성공 건수 |
| `finishCount` | Integer | 처리 완료 건수 (성공 + 실패 + 거부 + 취소) |
| `readyCount` | Integer | DB 적재된 건수 |
| `reservationDate` | NesDateTime | 예약 일시 |
| `countsByStatus` | List<CountByStatus> | 상태별 건수 배열 |

#### Response 예시

```json
{
  "requestId": "20181126000000246001",
  "readyCompleted": true,
  "allSentSuccess": false,
  "requestCount": 35179,
  "sentCount": 33502,
  "finishCount": 35179,
  "readyCount": 35179,
  "reservationDate": null,
  "countsByStatus": [
    {"status": {"label": "Failed to send", "code": "F"}, "count": 1415},
    {"status": {"label": "Sent successfully", "code": "S"}, "count": 33502},
    {"status": {"label": "Unsubscribe", "code": "U"}, "count": 262}
  ]
}
```

> **폴링 전략**: `readyCompleted === true && finishCount === requestCount` 이면 종결 판정. 부분 실패(`allSentSuccess === false`)는 `getMailList`로 수신자별 실패 사유 수집.

### 4.2 요청 내 메일 목록 조회 — `getMailList`

| Method | URI |
|---|---|
| `GET` | `/api/v1/mails/requests/{requestId}/mails` |

#### Query Parameters

| Field | Type | Description |
|---|---|---|
| `mailId` | String | 특정 메일 ID 필터 |
| `recipientAddress` | String | 수신자 이메일 주소 필터 |
| `title` | String | 제목 LIKE 검색 |
| `sendStatus` | List<String> | 상태 필터 — `R`\|`I`\|`S`\|`F`\|`U`\|`C`\|`PF` (배열 중복 지정 가능) |
| `size` | Integer | 페이지 크기 (기본 10) |
| `page` | Integer | 페이지 인덱스 (0부터) |
| `sort` | String | `id`\|`createUtc`\|`statusCode` + `,asc\|desc` |

### 4.3 단건 상세 조회 — `getMail`

| Method | URI |
|---|---|
| `GET` | `/api/v1/mails/{mailId}` |

#### Response (핵심 필드만)

| Field | Type | Description |
|---|---|---|
| `requestId` | String | |
| `mailId` | String | |
| `title` | String | |
| `emailStatus` | EmailStatus | `{label, code}` 형태 |
| `senderAddress` | String | |
| `sendDate` | NesDateTime | |
| `body` | String | |
| `attachFiles` | List<AttachFile> | 첨부 목록 |
| `recipients` | List<Recipient> | 수신자별 결과 (address, name, type, received, status, sendResultMessage, sendResultCode) |
| `advertising` | Boolean | |

**수신자별 상태 필드**: `received`, `status.code` (`S`/`F`/`U`/`C`/...), `sendResultCode` (예: `MAIL_SENT`, `RECIPIENT_ADDRESS_ERROR`), `sendResultMessage`, `retryCount`

### 4.4 요청 목록 조회 (기간 기반) — `getMailRequestList`

| Method | URI |
|---|---|
| `GET` | `/api/v1/mails/requests` |

#### Query Parameters

| Field | Type | Required | Description |
|---|---|---|---|
| `startUtc` / `startDateTime` | Long / String | Conditional | 둘 중 하나 필수. `startUtc` 우선 |
| `endUtc` / `endDateTime` | Long / String | Conditional | 둘 중 하나 필수. `endUtc` 우선 |
| `requestId`, `mailId`, `dispatchType` (`CONSOLE`\|`API`), `title`, `templateSid`, `senderAddress`, `recipientAddress` | - | Optional | 필터 |
| `sendStatus` | List<String> | Optional | `P`\|`R`\|`I`\|`S`\|`F`\|`U`\|`C`\|`PF` |
| `size`, `page`, `sort` | - | Optional | 페이지네이션 |

> 날짜 포맷: `yyyy-MM-dd`, `yyyy-MM-dd HH:mm`, `yyyy-MM-dd HH:mm:ss.SSS`, `yyyy-MM-dd HH:mm:ss SSS` (모두 KST 기준). `sort`: `createUtc`, `recipientCount`, `reservationUtc`, `sendUtc`, `statusCode`

### 4.5 발송 상태 코드 (전체)

| Code | Label | 의미 |
|---|---|---|
| `P` | Preparing delivery | 발송 준비 중 (getMailRequestList에만 등장) |
| `R` | Preparing/Ready | 발송 준비됨 |
| `I` | Sending | 발송 중 |
| `S` | Sent successfully | 성공 |
| `F` | Failed to send | 실패 |
| `U` | Unsubscribe / Rejected | 수신 거부됨 |
| `C` | Canceled | 취소 |
| `PF` | Partially failed | 부분 실패 (요청 레벨에서) |

### 4.6 이력 보관 기간

사용 가이드(`email-email-1-1`)에서 공식 인용:
> "View sent history: you can search up to **2 months** of sent emails."

즉 콘솔/API 상 조회 가능 기간은 **최근 2개월**이며, 그 이상은 자체 DB에 보관해야 합니다.

### 4.7 페이지네이션

Spring-Data-Pageable 스타일 응답:
```json
{
  "content": [...],
  "last": false, "first": true,
  "totalElements": 21, "totalPages": 5,
  "numberOfElements": 5,
  "size": 5, "number": 0,
  "sort": [{"direction": "DESC", "property": "createUtc", ...}]
}
```

**출처**:
- https://api.ncloud-docs.com/docs/en/ai-application-service-cloudoutboundmailer-getmailrequeststatus
- https://api.ncloud-docs.com/docs/en/ai-application-service-cloudoutboundmailer-getmail
- https://api.ncloud-docs.com/docs/en/ai-application-service-cloudoutboundmailer-getmaillist
- https://api.ncloud-docs.com/docs/en/ai-application-service-cloudoutboundmailer-getmailrequestlist

---

## 5. 에러 코드

Mailer는 Cloud Outbound Mailer 전용 에러 코드 **77xxx 시리즈**를 사용합니다.

| HTTP | Code | 의미 | 재시도? |
|---|---|---|---|
| 200 | - | 일반 성공 | - |
| **201** | - | **리소스 생성 성공 (POST /mails, /files 정상 응답)** | - |
| 400 | - | 인증 실패 또는 잘못된 요청 | ❌ |
| 400 | `77101` | 로그인 정보 오류 (Access Key/시그니처/시간 오류) | ❌ (설정 점검) |
| 400 | `77102` | BAD_REQUEST — 요청 본문 스키마 오류 | ❌ |
| 400 | `77103` | 요청한 리소스가 존재하지 않음 | ❌ |
| 403 | `77201` | 권한 없음 — Sub Account 권한 점검 | ❌ |
| 403 | `77202` | 이메일 서비스 미구독 — 콘솔에서 서비스 이용 신청 | ❌ |
| 405 | `77001` | METHOD_NOT_ALLOWED | ❌ |
| 415 | `77002` | UNSUPPORTED_MEDIA_TYPE (Content-Type 오류) | ❌ |
| 500 | `77301` | 기본 프로젝트가 존재하지 않음 | ❌ (콘솔 설정) |
| 500 | `77302` | 외부 시스템 API 연동 오류 | ✅ (지수 백오프) |
| 500 | `77303` | 기타 내부 서버 오류 | ✅ (지수 백오프) |

> SENS SMS의 에러 코드(`SENS_xxxx`)와는 다릅니다. `app/ncp/codes.py`를 확장하여 Mailer 전용 매핑 테이블을 별도로 두는 것을 권장합니다.

> **Rate limit(429) 코드에 대한 명시적 언급은 공식 문서에서 확인되지 않았습니다.** API Gateway 레벨에서 적용될 가능성은 있으나, 문서화되지 않았습니다.

**출처**:
- https://api.ncloud-docs.com/docs/en/ai-application-service-cloudoutboundmailer

---

## 6. Webhook / Callback

**공식 문서에서 Cloud Outbound Mailer의 Webhook/Callback 기능이 확인되지 않습니다.**

- 사용 가이드의 "features" 섹션에도 webhook 관련 항목 없음
- API 가이드의 operations 목록 전체에 callback/subscription 관련 엔드포인트 없음:
  - Send Email: `createMailRequest`, `getMail`, `getMailList`, `getMailRequestList`, `getMailRequestStatus`, `createFile`, `getFile`, `deleteFile`
  - Template management: create/get/update/delete/import/export
  - Manage recipient groups: `createAddressBook` 등
  - Manage send block/unsubscriber: `getSendBlockList`, `registerUnsubscribers`, `deleteUnsubscribers`

**결론**: **폴링이 유일한 방법**입니다. SMS와 동일하게 `getMailRequestStatus` + `getMailList` 조합으로 상태를 주기적으로 수집하는 구조가 필요합니다.

권장 폴링 전략:
1. 발송 직후 `requestId` 저장
2. `getMailRequestStatus` 를 exponential backoff (예: 5s → 10s → 30s → 1m → 5m)
3. `readyCompleted && finishCount == requestCount` 시점에 `getMailList`로 수신자별 결과 수집 (실패 경우만)
4. 수집 완료 후 폴링 종료

**출처**:
- https://guide.ncloud-docs.com/docs/en/email-email-1-1
- https://api.ncloud-docs.com/docs/en/ai-application-service-cloudoutboundmailer (operations 섹션)

---

## 7. 비용 / Rate Limit

### 7.1 발송 단가

공식 가이드 인용:
> "Cloud Outbound Mailer is a paid service, and charges are applied based on the number of mails sent beyond the free tier."

- 공식 API/사용 가이드는 **구체적 요금 수치를 기재하지 않고** 포털의 제품 페이지로 안내합니다.
- 참조: https://www.ncloud.com/product/applicationService/cloudOutboundMailer (포털 페이지, 요금제는 수시 변경 가능하므로 **프로젝트 시점에 직접 확인 필요**)

**구체 단가는 공식 문서(api/guide)에서 확인되지 않음** — 포털 pricing 페이지를 사용 시점에 확인해야 합니다.

### 7.2 발송 한도

| 항목 | 값 | 출처 |
|---|---|---|
| 기본 월 발송 한도 | **1,000,000건** | createMailRequest (ko) |
| 1회 호출 수신자 | **100,000명** (recipientGroupFilter 시 초과) | createMailRequest (ko) |
| 참조 / 숨은참조 | **30명 / 30명** | createMailRequest (ko) |
| 이메일 본문 크기 | **500 KB** (수신거부 메시지 포함) | createMailRequest (ko) |
| 첨부 파일 총 크기 | **20 MB** | createMailRequest (ko) |
| 개별 첨부 파일 | **10 MB** | createFile (en) |
| 한도 상향 | 고객 지원 문의 | createMailRequest (ko) |

### 7.3 API Rate Limit

**공식 문서에서 초당/분당 API 호출 수 제한은 확인되지 않습니다.** 발송 한도는 **월별 건수** 기반입니다. 실무에서는 API Gateway 레벨의 암묵적 제한을 고려하여 호출 측에서 자체 throttle(예: 초당 10~20 req)을 두는 것이 안전합니다.

---

## 8. 첨부 파일

### 8.1 선 업로드 엔드포인트 — `createFile`

SMS의 `attachment-create`와 유사한 별도의 파일 업로드 엔드포인트가 존재합니다.

| Method | URI | Content-Type |
|---|---|---|
| `POST` | `/api/v1/files` | `multipart/form-data` |

#### Request Body

| Field | Type | Required | Description |
|---|---|---|---|
| `fileList` | File | Required | 업로드할 파일 (multipart field) |

#### 요청 예시

```bash
curl --location --request POST 'https://mail.apigw.ntruss.com/api/v1/files' \
  --header 'x-ncp-apigw-timestamp: {Timestamp}' \
  --header 'x-ncp-iam-access-key: {Access Key}' \
  --header 'x-ncp-apigw-signature-v2: {Signature}' \
  --form 'fileList=@"/path/to/file.pdf"'
```

> **주의**: multipart 요청이지만 시그니처의 URI는 `/api/v1/files` (querystring 없음). `Content-Type` 헤더는 `httpx`가 multipart 자동 생성하도록 두고, 시그니처 생성 시에는 `Content-Type`을 `application/json` 대신 **별도로 세팅하지 않아도 무방** (시그니처는 Content-Type을 포함하지 않음).

#### Response Body (HTTP **201**)

| Field | Type | Description |
|---|---|---|
| `tempRequestId` | String | 업로드 세션 임시 ID. 조회/삭제에 사용 |
| `files` | List<AttachFile> | 업로드된 파일 목록 |

AttachFile 필드 (응답 예시로부터): `fileName`, `fileSize`, `fileId`

#### Response 예시

```json
{
  "tempRequestId": "f355aac1-7776-4c0b-8484-20eaa065cb65-99",
  "files": [
    {
      "fileName": "test.txt",
      "fileSize": 16,
      "fileId": "40fe58bd-91fe-4f89-a62e-705a7c17d65e-99"
    }
  ]
}
```

### 8.2 메일 발송 시 연결

`createMailRequest` 호출 시 `attachFileIds: ["40fe58bd-...", ...]`로 전달. 업로드된 파일의 `fileId`를 그대로 사용.

### 8.3 관련 엔드포인트

- `GET /api/v1/files/{tempRequestId}` — `getFile` (업로드 세션 조회)
- `DELETE /api/v1/files/{fileId}` 또는 유사 — `deleteFile`

### 8.4 제약 사항

| 항목 | 값 |
|---|---|
| 개별 파일 최대 크기 | **10 MB** (createFile response body 설명) |
| 1메일 첨부 총용량 | **20 MB** (createMailRequest `attachFileIds` 설명) |
| 파일 형식 제한 | **공식 문서에서 확장자/MIME 화이트리스트 명시되지 않음** |
| 인라인 이미지 | **공식 문서에서 CID/인라인 이미지 전용 필드 확인되지 않음**. HTML `body`에 `<img src="data:image/png;base64,...">` 또는 외부 URL 참조 방식으로 대체 가능 (비공식) |

**출처**:
- https://api.ncloud-docs.com/docs/en/ai-application-service-cloudoutboundmailer-createfile
- https://api.ncloud-docs.com/docs/ko/ai-application-service-cloudoutboundmailer-createmailrequest

---

## 9. 한국 / 글로벌 발송 & 스팸 회피

### 9.1 리전별 발송

- 동일 서비스가 **Korea / Singapore / Japan** 리전에서 각각 독립 제공 (각자 구독 필요)
- 엔드포인트만 다를 뿐 스키마/인증은 동일

### 9.2 스팸 필터 회피 모범 사례 (공식 권고)

1. **DMARC 적용 포털 계정 사용 금지** — `id@naver.com` 등은 DMARC 검사 실패로 스팸 처리됨
2. **실제 소유 도메인 사용** + 콘솔에서 도메인 등록
3. **SPF / DKIM / DMARC 3종 모두 인증 완료** — 하나라도 빠지면 일부 수신 도메인에서 발송 실패 가능
4. **광고 메일(`advertising: true`)은 수신 거부 메시지 필수** — 기본 메시지(`useBasicUnsubscribeMsg: true`) 또는 사용자 정의 메시지(+`#{UNSUBSCRIBE_MESSAGE}` 태그)
5. **금지 도메인**: `senderAddress`에 `naver.com`, `navercorp.com`, `ncloud.com` 사용 불가

### 9.3 수신 거부 관리

- `getSendBlockList` — 시스템 차단 목록
- `registerUnsubscribers` / `deleteUnsubscribers` — 수신거부자 관리
- 광고 메일 발송 시 자동으로 수신거부 대상자는 제외됨

**출처**:
- https://api.ncloud-docs.com/docs/ko/ai-application-service-cloudoutboundmailer-createmailrequest
- https://guide.ncloud-docs.com/docs/en/cloudoutboundmailer-use-domain

---

## 10. 모범 사례 / 알려진 함정

### 10.1 HMAC 시그니처 함정 (SMS 경험 재사용)

- `timestamp`는 **한 번만 생성**하여 헤더와 signing string에 동일하게 사용
- URI에 **host 포함 금지** (`/api/v1/mails`만, `https://mail.apigw.ntruss.com/api/v1/mails` ❌)
- 5분 이상 시간 drift 시 `77101` 발생 → NTP 동기화 필수
- URI에 querystring 포함 시 **인코딩된 상태로** 서명 (`startDateTime=2018-11-01%2000:00` 그대로)
- `secret_key.encode("utf-8")` 로 바이트 변환 → `hmac.new(..., hashlib.sha256)` → `base64.b64encode(...).decode("utf-8")`

### 10.2 HTTP 상태 코드 함정

- **성공 시 HTTP 201 반환** (SMS v2는 202). 기존 `NCPClient._raise_for_status`를 그대로 재사용하면 **정상 응답을 에러로 처리**함. Mailer 전용 클라이언트에서는 `(200, 201)`을 성공으로 취급하도록 수정 필수.

### 10.3 발송 API 호출 패턴

- **단일 호출로 100,000명까지 가능** → SMS처럼 100건씩 청크 분할할 필요 없음. 단일 호출 시 내부적으로 30건씩 비동기 처리됨.
- `individual: true`(기본) + `recipients[].parameters`로 개인화 발송 권장
- `senderName` 반드시 지정 (스팸 필터 통과율 향상)
- `confirmAndSend: false` (즉시 발송) — `true`면 콘솔에서 수동 승인 필요

### 10.4 폴링 주의사항

- Mailer의 발송은 **비동기** — `count` 응답 직후 `getMailRequestStatus`를 호출해도 `readyCompleted: false`일 수 있음
- `readyCompleted: true` 이후에도 `finishCount < requestCount`일 수 있음 (발송 진행 중). 두 조건 모두 체크 필요
- 이력 2개월 제한 → 장기 감사 로그는 자체 DB에 복제 필수

### 10.5 치환 태그 사용법

- 본문/제목에서 치환 태그 문법은 `${variable_name}` (createMailRequest 예시)
- 수신거부 메시지 위치 지정은 `#{UNSUBSCRIBE_MESSAGE}` (특수 태그, `$` 가 아니라 `#` 사용)
- 전체 공통 치환은 `parameters`, 개인별 치환은 `recipients[].parameters` — 동일 key 충돌 시 수신자별 값이 우선 적용될 것으로 추정 (공식 명시 없음)

### 10.6 템플릿 사용 시 주의

- `templateSid`를 지정하면 `senderAddress/title/body`는 생략 가능 (템플릿 값 사용)
- 그러나 `recipients/individual/advertising` 등은 여전히 필요
- 템플릿 수정 시 진행 중인 발송에는 영향 없음 (템플릿 스냅샷 기반)

---

## 부록 A. kotify 프로젝트 적용 가이드

### A.1 `app/ncp/mailer.py` 초안 구조

```python
"""NCP Cloud Outbound Mailer API v1 클라이언트.

SMS(SENS)와 동일한 HMAC-SHA256 시그니처(app.ncp.signature.make_headers)를
재사용하되, 다음 차이점을 반영한다:
- 호스트: mail.apigw.ntruss.com (sens.apigw.ntruss.com 아님)
- 성공 코드: 201 (SMS는 202)
- 청크 분할 불필요 (단일 호출 100,000명까지)
- 별도 파일 업로드 엔드포인트 (POST /files, multipart)
- 폴링: getMailRequestStatus + getMailList 조합
"""

_BASE_URL = "https://mail.apigw.ntruss.com"
_SEND_PATH = "/api/v1/mails"
_FILE_UPLOAD_PATH = "/api/v1/files"
_REQUEST_STATUS_PATH = "/api/v1/mails/requests/{request_id}/status"
_REQUEST_MAIL_LIST_PATH = "/api/v1/mails/requests/{request_id}/mails"
_MAIL_DETAIL_PATH = "/api/v1/mails/{mail_id}"

# 단일 호출 최대 수신자 (NCP 공식 제약)
_MAX_RECIPIENTS_PER_CALL = 100_000

# 성공 HTTP 코드 (SMS와 다름: 201)
_SUCCESS_CODES = (200, 201)
```

핵심 메서드:
- `send_mail(sender_address, sender_name, title, body, recipients, *, individual=True, attach_file_ids=None, reservation_utc=None, advertising=False, template_sid=None) -> SendResponse`
- `upload_attachment(file_bytes, filename) -> AttachFileResponse`
- `get_request_status(request_id) -> RequestStatusResponse`
- `list_mails_in_request(request_id, *, page=0, size=100, statuses=None) -> MailListResponse`
- `get_mail_detail(mail_id) -> MailDetailResponse`

### A.2 `app/services/sender/email.py` 설계 포인트

- `dispatch_email_campaign(campaign_id)`:
  - 수신자 조회 → `RecipientForRequest[]` 빌드
  - `individual=True` + `recipients[].parameters` 로 개인별 치환 (DB의 회원 속성을 key-value로 전개)
  - 단일 호출로 `send_mail` (청크 분할 불필요)
  - `requestId` DB 저장
- `poll_email_status(request_id)`:
  - `get_request_status` → `readyCompleted && finishCount == requestCount` 체크
  - 미완료 시 지수 백오프로 재시도
  - 완료 시 `list_mails_in_request(statuses=["F", "PF"])` 로 실패 수신자만 수집
  - 각 실패 건에 대해 `get_mail_detail` 또는 `list_mails_in_request`의 결과로 `sendResultCode/sendResultMessage` 저장

### A.3 SMS 대비 차이점 요약 (구현 시 반드시 반영)

| 항목 | SMS (SENS v2) | Mailer (v1) |
|---|---|---|
| Host | `sens.apigw.ntruss.com` | `mail.apigw.ntruss.com` |
| Base path | `/sms/v2/services/{serviceId}` | `/api/v1` |
| Service ID | URL에 포함 | **없음** (API Gateway 레벨에서 account로 식별) |
| 발송 성공 코드 | 202 | **201** |
| 1회 최대 | 100명 | **100,000명** |
| 개인별 치환 | `messages[]` 배열로 분할 | `recipients[].parameters` |
| 첨부파일 | MMS 이미지 (별도 `attachment-create`) | **`POST /files` multipart 업로드** |
| 발송 응답 필드 | `requestId, requestTime, statusCode, statusName` | **`requestId, count`만** |
| 조회 API | `GET /messages?requestId=` 단일 | 4종 (status/list/mail detail/request list) |
| 예약 | `reserveTime, reserveTimeZone` | **`reservationUtc` (epoch ms) or `reservationDateTime` (KST)** |
| 에러 코드 prefix | SMS 고유 | **`77xxx`** |
| Webhook | ❌ 없음 | ❌ 없음 (폴링 필수) |

---

## 부록 B. 전체 Operations 카탈로그

### Send Email
| Operation | Method | URI |
|---|---|---|
| createMailRequest | POST | `/mails` |
| getMail | GET | `/mails/{mailId}` |
| getMailList | GET | `/mails/requests/{requestId}/mails` |
| getMailRequestList | GET | `/mails/requests` |
| getMailRequestStatus | GET | `/mails/requests/{requestId}/status` |
| createFile | POST | `/files` |
| getFile | GET | `/files/...` |
| deleteFile | DELETE | `/files/...` |

### Template management
createTemplate, createTemplateExportRequest, getTemplate (`GET /template/{templateSid}`), getTemplateExportRequestList, getTemplateStructure, updateTemplate, exportTemplate, importTemplate, deleteTemplate, restoreTemplate, createCategory, deleteCategory

### Address book / Recipient groups
createAddressBook, getAddressBook (`GET /address-book`), deleteAddressBook, deleteAddress, deleteRecipientGroup, deleteRecipientGroupRelation, deleteRecipientGroupRelationEmpty

### Send block & unsubscribe
getSendBlockList, registerUnsubscribers, deleteUnsubscribers

---

## 부록 C. 전체 출처 URL

### 공식 API 가이드 (api.ncloud-docs.com)
- Overview: https://api.ncloud-docs.com/docs/en/ai-application-service-cloudoutboundmailer
- createMailRequest (KO, 전체 필드 포함): https://api.ncloud-docs.com/docs/ko/ai-application-service-cloudoutboundmailer-createmailrequest
- getMail: https://api.ncloud-docs.com/docs/en/ai-application-service-cloudoutboundmailer-getmail
- getMailList: https://api.ncloud-docs.com/docs/en/ai-application-service-cloudoutboundmailer-getmaillist
- getMailRequestList: https://api.ncloud-docs.com/docs/en/ai-application-service-cloudoutboundmailer-getmailrequestlist
- getMailRequestStatus: https://api.ncloud-docs.com/docs/en/ai-application-service-cloudoutboundmailer-getmailrequeststatus
- createFile: https://api.ncloud-docs.com/docs/en/ai-application-service-cloudoutboundmailer-createfile
- getTemplate: https://api.ncloud-docs.com/docs/en/ai-application-service-cloudoutboundmailer-gettemplate
- getAddressBook: https://api.ncloud-docs.com/docs/en/ai-application-service-cloudoutboundmailer-getaddressbook
- RecipientForRequest (수신자 스키마): https://api.ncloud-docs.com/docs/common-vapidatatype-nesrecipientrequest

### 공식 사용 가이드 (guide.ncloud-docs.com)
- Overview: https://guide.ncloud-docs.com/docs/en/email-email-1-1
- Prerequisites (spec/pricing): https://guide.ncloud-docs.com/docs/en/cloudoutboundmailer-spec
- Quickstart/scenario: https://guide.ncloud-docs.com/docs/en/cloudoutboundmailer-procedure
- Domain management (SPF/DKIM/DMARC): https://guide.ncloud-docs.com/docs/en/cloudoutboundmailer-use-domain
- Mail usage (치환 태그): https://guide.ncloud-docs.com/docs/en/cloudoutboundmailer-use-mail
- Sub Account 권한: https://guide.ncloud-docs.com/docs/en/email-email-subaccount

### 포털 (제품/요금)
- 제품 페이지: https://www.ncloud.com/product/applicationService/cloudOutboundMailer

### 관련 참조
- NCP API 공통 인증 가이드: https://api.ncloud-docs.com/docs/en/common-ncpapi
- DMARC RFC 7489: https://www.ietf.org/rfc/rfc7489.txt

---

## 불확실성 / 추가 확인 필요 항목

공식 문서(api.ncloud-docs.com, guide.ncloud-docs.com)에서 **명확히 확인되지 않은** 항목들:

1. **Rate limit 수치**: 초/분당 API 호출 제한. HTTP 429 반환 동작 미문서화.
2. **구체적 발송 단가 (KRW/건)**: 포털 제품 페이지로만 안내됨. 프로젝트 시점에 직접 확인 필요.
3. **Webhook/Callback**: 기능 자체가 존재하지 않는 것으로 **강하게 추정**되나, 공식 "없음" 선언은 아님. 반증으로 operations 카탈로그 전체에 callback 엔드포인트 부재.
4. **첨부파일 MIME/확장자 화이트리스트**: 제한 여부 자체가 명시되지 않음.
5. **인라인 이미지 (CID) 전용 지원**: `attachFile`에 `isInline` 같은 필드 존재 여부 미확인. HTML `body` + base64/외부 URL 대체 권장.
6. **`parameters` vs `recipients[].parameters` 우선순위**: 동일 key 충돌 시 어느 쪽이 적용되는지 공식 명시 없음. 구현 시 테스트 필수.
7. **v2 API 존재 여부**: 2026-04 기준 `api.ncloud-docs.com`에 `cloudoutboundmailer-v2` 경로는 존재하지 않음. v1이 현재 유일한 버전.
8. **HTTP 429 재시도 동작**: API Gateway 레벨에서 429가 발생할 가능성은 있으나 공식 문서에서 언급되지 않음. 방어적으로 클라이언트에 재시도 로직 포함 권장.

---

**보고서 작성자 메모**: 본 조사는 `api.ncloud-docs.com` 및 `guide.ncloud-docs.com`의 Angular 기반 SPA를 Tavily Extract로 수집하여 공식 텍스트를 확보했습니다. 모든 필드 정의와 예시 JSON은 공식 문서 원문 그대로이며, 한국어/영어 문서를 교차 검증했습니다.
