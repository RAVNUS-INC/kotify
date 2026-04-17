# U+ msghub 메시징 시스템 기획서

> 작성일: 2026-04-16
> 수정일: 2026-04-17 (결정사항 반영, NCP 참조 제거)
> 버전: v2.0
> 발송 방식: RCS 직접 발송 + fbInfoLst fallback (템플릿 미사용)
> 요금제: 후불
> RCS 브랜드: 등록 완료

---

## 목차

1. [프로젝트 개요](#1-프로젝트-개요)
2. [발송 전략](#2-발송-전략)
3. [시스템 아키텍처](#3-시스템-아키텍처)
4. [API 엔드포인트 전체 맵](#4-api-엔드포인트-전체-맵)
5. [인증 모듈](#5-인증-모듈)
6. [RCS 발송 API 상세](#6-rcs-발송-api-상세)
7. [SMS/LMS/MMS Fallback API 상세](#7-smslmsmms-fallback-api-상세)
8. [파일 업로드 API 상세](#8-파일-업로드-api-상세)
9. [예약 발송](#9-예약-발송)
10. [리포트 (발송 결과) 시스템](#10-리포트-발송-결과-시스템)
11. [에러 코드 전체 목록](#11-에러-코드-전체-목록)
12. [비용 계산 로직](#12-비용-계산-로직)
13. [DB 스키마 변경](#13-db-스키마-변경)
14. [영향 파일 및 변경 수준](#14-영향-파일-및-변경-수준)
15. [구현 순서](#15-구현-순서)

---

## 1. 프로젝트 개요

### 1.1 목적

U+ msghub API 기반 RCS 우선 메시징 시스템 구축:
- RCS 우선 발송으로 비용 절감 (특히 이미지: 85원 → 40원)
- RCS 실패 시 자동 fallback (msghub `fbInfoLst`)
- 웹훅 기반 리포트 수신으로 실시간 결과 확인
- 발송 비용 실시간 추적 (미리보기 + 결과)

### 1.2 발송 채널 및 요금 (후불, VAT 별도)

| 메시지 유형 | 1순위 발송 | 요금 | Fallback | 요금 | 절감 |
|------------|-----------|------|----------|------|------|
| 단문 (≤90B) | RCS 양방향 | **8원** | SMS | 9원 | 1원/건 |
| 장문 (>90B) | RCS LMS | **27원** | LMS | 27원 | 동일 (RCS 리치) |
| 이미지 | RCS 이미지 템플릿 | **40원** | MMS | 85원 | **45원/건** |

### 1.3 범위

- 카카오 알림톡: **제외**
- MO (수신 메시지): **미사용**
- 통합 발송 API (템플릿): **미사용** (매번 내용이 바뀌므로)
- RCS 직접 발송 + fbInfoLst fallback 방식 채택
- RCS 브랜드/챗봇: **등록 완료** (별도 준비 불필요)
- NCP 관련 코드: **전량 삭제** (마이그레이션이 아닌 완전 교체)

---

## 2. 발송 전략

### 2.1 메시지 유형별 라우팅

```
사용자 메시지 입력
    │
    ├─ 이미지 첨부 있음?
    │   └─ YES → RCS 이미지 템플릿 (40원)
    │            fbInfoLst: MMS (85원)
    │
    ├─ 본문 > 90바이트?
    │   └─ YES → RCS LMS (27원)
    │            fbInfoLst: LMS (27원)
    │
    └─ NO  → RCS 양방향 (8원)
             fbInfoLst: SMS (9원)
```

### 2.2 Fallback 동작 원리

msghub가 자동 처리:
1. RCS 발송 시도
2. 실패 시 (미지원 단말, 타임아웃 등) → `fbInfoLst`에 지정된 SMS/MMS로 자동 대체
3. **성공 채널만 과금** (이중 과금 없음)
4. 리포트에 `fbReasonLst`로 RCS 실패 사유 기록

### 2.3 cliKey 생성 규칙

msghub는 모든 수신자에 `cliKey`(클라이언트 고유키)를 필수로 요구한다.

- 정규식: `^[a-zA-Z0-9-_.@]{1,30}$`
- 생성 규칙: `c{campaign_id}-{chunk_idx}-{recipient_idx}`
  - 예: `c42-0-0`, `c42-0-1`, ..., `c42-9-9`
- 10분 이내 동일 cliKey 재사용 시 중복 판정 (에러 29005)
- 리포트 조회 시 이 키로 결과 매칭

---

## 3. 시스템 아키텍처

### 3.1 msghub API 호스트 구조

**msghub는 3개 호스트로 분리됨**

| 용도 | 상용 | QA |
|------|------|----|
| **인증/리포트** | `https://api.msghub.uplus.co.kr` | `https://api.msghub-qa.uplus.co.kr` |
| **메시지 발송** | `https://api-send.msghub.uplus.co.kr` | `https://api-send.msghub-qa.uplus.co.kr` |
| **파일/관리** | `https://mnt-api.msghub.uplus.co.kr` | `https://mnt-api.msghub-qa.uplus.co.kr` |

전용회선 (선택사항):

| 용도 | 상용 | IP |
|------|------|----|
| 인증/리포트 | `https://api-direct.msghub.uplus.co.kr` | 1.209.4.60 / 1.209.4.75 |
| 발송 | `https://api-send-direct.msghub.uplus.co.kr` | 별도 |
| 파일/관리 | `https://mnt-api-direct.msghub.uplus.co.kr` | 별도 |

### 3.2 통신 규격

| 항목 | 값 |
|------|-----|
| Content-Type | `application/json` (파일 업로드만 `multipart/form-data`) |
| 인코딩 | UTF-8 |
| CORS | **미지원** — 브라우저 직접 호출 불가, 서버 사이드 전용 |
| 인증 | `Authorization: Bearer {JWT}` |

---

## 4. API 엔드포인트 전체 맵

### 4.1 인증

| API | 메서드 | 엔드포인트 | 호스트 |
|-----|--------|-----------|--------|
| 토큰 발급 | POST | `/auth/v1/{randomStr}` | api |
| 토큰 갱신 | PUT | `/auth/v1/refresh` | api |

### 4.2 메시지 발송

| API | 메서드 | 엔드포인트 | 호스트 |
|-----|--------|-----------|--------|
| RCS 단방향 | POST | `/rcs/v1.1` | **api-send** |
| RCS 양방향 | POST | `/rcs/bi/v1.1` | **api-send** |
| SMS | POST | `/msg/v1/sms` | api |
| LMS/MMS (JSON) | POST | `/msg/v1/mms` | api |
| LMS/MMS (multipart) | POST | `/msg/v1/mms` | api |

### 4.3 파일 관리

| API | 메서드 | 엔드포인트 | 호스트 |
|-----|--------|-----------|--------|
| 파일 업로드 | POST | `/file/v1/{ch}` | **mnt-api** |

### 4.4 예약 발송

| API | 메서드 | 엔드포인트 | 호스트 |
|-----|--------|-----------|--------|
| 예약 목록 조회 | GET | `/msg/v1.1/resv/sendList` | api |
| 예약 취소 | POST | `/msg/v1/resv/sendCancel` | api |

### 4.5 리포트

| API | 메서드 | 엔드포인트 | 호스트 |
|-----|--------|-----------|--------|
| 리포트 Polling | GET | `/msg/v1.2/report` | api |
| 리포트 ACK | POST | `/msg/v1.2/report/result` | api |
| 개별 조회 (cliKey) | POST | `/msg/v1/sent` | api |
| 웹훅 수신 | POST | `{고객사 URL}` | 고객사 서버 |

### 4.6 RCS 브랜드/챗봇 관리

| API | 메서드 | 엔드포인트 | 호스트 |
|-----|--------|-----------|--------|
| 브랜드 목록 | GET | `/rcs/v1/brand` | mnt-api |
| 브랜드 등록 | POST | `/rcs/v1/brand` | mnt-api |
| 챗봇 목록 | GET | `/rcs/v1/chatbot` | mnt-api |
| 챗봇 등록 | POST | `/rcs/v1/chatbot` | mnt-api |
| 공통 메시지베이스 조회 | GET | `/rcs/v1/messagebase/common` | mnt-api |
| RCS 읽음 통계 | POST | `/rcs/v1/statQuery/message/{brandId}` | mnt-api |
| RCS 버튼클릭 통계 | POST | `/rcs/v1/statQuery/messageButton/{brandId}` | mnt-api |

---

## 5. 인증 모듈

### 5.1 토큰 수명

| 토큰 | 만료 | 갱신 시점 |
|------|------|----------|
| Access Token | 1시간 | 만료 10분 전 |
| Refresh Token | 25시간 | 만료 30분 전 |

### 5.2 토큰 발급

```
POST /auth/v1/{randomStr}
Content-Type: application/json
Host: api.msghub.uplus.co.kr
```

**비밀번호 SHA512 이중 해싱 (정확한 절차):**

```python
import hashlib, base64

def encrypt_password(api_pwd: str, random_str: str) -> str:
    # Step 1: SHA512 → Base64
    step1 = base64.b64encode(
        hashlib.sha512(api_pwd.encode('utf-8')).digest()
    ).decode('utf-8')

    # Step 2: (step1 + "." + randomStr) → SHA512 → Base64
    combined = step1 + "." + random_str
    step2 = base64.b64encode(
        hashlib.sha512(combined.encode('utf-8')).digest()
    ).decode('utf-8')

    return step2
```

**Path Parameter:**

| 이름 | 타입 | 필수 | 설명 |
|------|------|------|------|
| randomStr | String | Y | 영숫자/하이픈/언더스코어, 최대 20자 |

**Request Body:**

| 이름 | 타입 | 필수 | 설명 |
|------|------|------|------|
| apiKey | String | Y | API 키 |
| apiPwd | String | Y | 이중 해싱된 비밀번호 |

**Response:**

```json
{
  "code": "10000",
  "message": "성공",
  "data": {
    "token": "eyJhbGciOiJIUzI1NiJ9...",
    "refreshToken": "eyJhbGciOiJIUzI1NiJ9..."
  }
}
```

### 5.3 토큰 갱신

```
PUT /auth/v1/refresh
Authorization: Bearer {refreshToken}
Host: api.msghub.uplus.co.kr
```

**Response:** 새 access token만 발급. refresh token은 변경 없음.

```json
{
  "code": "10000",
  "message": "성공",
  "data": {
    "token": "eyJhbGciOiJIUzI1NiJ9..."
  }
}
```

### 5.4 보안 요구사항

- API 키에 최소 1개 소스 IP 대역 등록 필수 (콘솔에서)
- 인증 요청 IP도 허용 범위 포함 필요
- 미허용 IP → 에러 20001/29025

### 5.5 구현 설계: TokenManager 클래스

```
TokenManager
├── authenticate()          # 최초 토큰 발급
├── refresh()               # access token 갱신
├── get_token() → str       # 유효한 토큰 반환 (자동 갱신)
├── _is_token_expiring()    # 만료 10분 전 체크
├── _is_refresh_expiring()  # 만료 30분 전 체크
└── _encrypt_password()     # SHA512 이중 해싱
```

---

## 6. RCS 발송 API 상세

### 6.1 RCS 단방향 (SMS형/LMS형/이미지템플릿)

```
POST /rcs/v1.1
Authorization: Bearer {token}
Content-Type: application/json
Host: api-send.msghub.uplus.co.kr
```

**Request Body — 전체 필드:**

| 필드 | 타입 | 필수 | 크기 | 설명 |
|------|------|------|------|------|
| messagebaseId | String | **Y** | 100자 | 메시지베이스 ID (상품 유형 결정) |
| callback | String | **Y** | 100자 | 발신번호 |
| header | String | **Y** | 1자 | `0`=정보성, `1`=광고성 |
| footer | String | 조건부 | 20자 | 080 수신거부 번호 (header=1 시 **필수**) |
| copyAllowed | Boolean | N | - | 복사/공유 허용 |
| expiryOption | String | N | 1자 | 만료: `1`=24시간, `2`=30초, `3`=3분, `4`=1시간 |
| campaignId | String | N | 20자 | 캠페인 ID |
| deptCode | String | N | 20자 | 부서 코드 |
| clickUrlYn | String | N | 1자 | 단축URL 사용 (Y/N) |
| resvYn | String | N | 1자 | 예약발송 (Y/N) |
| resvReqDt | String | N | - | 예약일시 `yyyy-MM-dd hh:mm` (현재+최대 30일) |
| agency | Agency | N | - | 대행사 정보 |
| buttons | Array | N | 최대 4개 | 버튼 목록 |
| recvInfoLst | RecvInfo[] | **Y** | **최대 10명** | 수신자 목록 |
| fbInfoLst | FbInfo[] | N | - | Fallback 정보 |
| brandId | String | 조건부 | - | 대행사일 경우 필수 |
| brandKey | String | 조건부 | - | 대행사일 경우 필수 |
| productCode | String | 조건부 | - | 대행사일 경우 필수 |

**Response:**

```json
{
  "code": "10000",
  "message": "성공",
  "data": [
    {
      "cliKey": "c42-0-0",
      "msgKey": "tw9Tomlcen.6bTb0O",
      "phone": "01012345678",
      "code": "10000",
      "message": "성공"
    }
  ]
}
```

**예약발송 응답 (형태가 다름):**

```json
{
  "code": "10000",
  "message": "성공",
  "data": {
    "regDt": "2026-04-08T11:16:55",
    "webReqId": "RRRxxxb5jv"
  }
}
```

### 6.2 RCS 양방향

```
POST /rcs/bi/v1.1
Authorization: Bearer {token}
Content-Type: application/json
Host: api-send.msghub.uplus.co.kr
```

**Request Body:**

| 필드 | 타입 | 필수 | 크기 | 설명 |
|------|------|------|------|------|
| messagebaseId | String | **Y** | 100자 | `SCL00000` (양방향 SMS형) |
| chatbotId | String | **Y** | 40자 | 양방향대화방 ID (=발신번호) |
| replyId | String | **Y** | - | 양방향 응답메시지 ID |
| cliKey | String | **Y** | 20자 | 클라이언트 키 |
| telco | String | **Y** | - | 이통사 (`LGU`, `SKT`, `KT`) |
| phone | String | **Y** | - | 수신번호 |
| body | Object | **Y** | - | 메시지 내용 |
| body.description | String | **Y** | - | 메시지 본문 |
| header | String | **Y** | 1자 | `0`=정보성, `1`=광고성 |
| footer | String | 조건부 | 20자 | 광고성 시 필수 |
| copyAllowed | Boolean | N | - | 복사/공유 허용 |
| campaignId | String | N | 20자 | 캠페인 ID |
| deptCode | String | N | 20자 | 부서 코드 |
| buttons | Array | N | 최대 4개 | 버튼 목록 |
| chipList | Array | N | - | 칩 목록 (양방향 전용) |
| agency | Agency | N | - | 대행사 정보 |

**양방향 추가 응답 필드:**

| 필드 | 설명 |
|------|------|
| data[].replyId | 양방향 응답메시지 ID |
| data[].chatbotId | 챗봇 ID |

**양방향 제약사항:**
- **후불 고객사만** 사용 가능 ✓ (우리 해당)
- 양방향번호로 등록된 번호만 사용 가능
- 웹훅 URL 미지정 시 일정 시간 후 수신 메시지 삭제
- recvInfoLst가 아닌 **단건 발송** (cliKey, phone이 최상위)

### 6.3 messagebaseId 체계 (RCS 상품 유형)

| 유형 | messagebaseId | productCode | 용도 |
|------|---------------|-------------|------|
| **RCS SMS형** | `SS000000` | SMS | 단문 텍스트 |
| **RCS LMS형** | `SL000000` | LMS | 장문 텍스트 |
| **RCS MMS형 (세로 Medium)** | `SMwThM00` | MMS | 이미지+텍스트 |
| **RCS MMS형 (세로 Tall)** | `SMwThT00` | MMS | 이미지+텍스트 (세로 긴) |
| **이미지 강조형** | `OMHIMV0001` | MMS | 이미지 중심 |
| **이미지&타이틀 강조형** | `OMHITV0001` | MMS | 이미지+타이틀 |
| **썸네일형 (세로)** | `OMTBNV0001` | ITMPL | 메인+서브 썸네일 |
| **SNS형** | `OMSNSS0001` | ITMPL | SNS 스타일 |
| **슬라이드형 (Small 2~6장)** | `CMwShS0200`~`0600` | ITMPL | 카루셀 |
| **양방향 SMS형** | `SCL00000` | CHAT | 양방향 전용 |

**우리가 사용할 messagebaseId:**

| 메시지 유형 | messagebaseId | API |
|------------|---------------|-----|
| 단문 (양방향) | `SCL00000` | `/rcs/bi/v1.1` |
| 장문 | `SL000000` | `/rcs/v1.1` |
| 이미지 | `OMHIMV0001` 또는 `SMwThM00` | `/rcs/v1.1` |

### 6.4 mergeData (변수 치환)

RCS 메시지 내용은 `recvInfoLst[].mergeData`로 전달한다.

**RCS SMS/LMS형:**

```json
"mergeData": {
  "title": "발송 제목",
  "description": "본문 내용. {{name}}님 안녕하세요."
}
```

**RCS MMS형 (이미지 포함):**

```json
"mergeData": {
  "title": "제목",
  "description": "본문 텍스트",
  "media": "maapfile://{fileId}"
}
```

**이미지 강조형:**

```json
"mergeData": {
  "title": "제목",
  "description": "본문",
  "media": "maapfile://{fileId}",
  "subTitle1": "항목1", "subDesc1": "값1",
  "subTitle2": "항목2", "subDesc2": "값2",
  "subTitle3": "항목3", "subDesc3": "값3"
}
```

**변수 치환 문법:** `{{변수명}}` (이중 중괄호)
- SMS/LMS fallback의 mergeData: `#{변수명}` (샵+단일 중괄호)

### 6.5 buttons (버튼, 최대 4개)

```json
"buttons": [{
  "suggestions": [{
    "action": {
      "displayText": "버튼 텍스트",
      "postback": { "data": "set_by_chatbot_open_url" },
      "urlAction": { "openUrl": { "url": "https://example.com" } }
    }
  }]
}]
```

**버튼 유형:**

| 유형 | postback.data | action 필드 |
|------|---------------|------------|
| URL 링크 | `set_by_chatbot_open_url` | `urlAction.openUrl.url` |
| 복사하기 | `set_by_chatbot_copy_to_clipboard` | `clipboardAction.copyToClipboard.text` |
| 전화걸기 | `set_by_chatbot_dial_phone_number` | `dialerAction.dialPhoneNumber.phoneNumber` |
| 일정추가 | `set_by_chatbot_create_calendar_event` | `calendarAction.createCalendarEvent.*` |
| 지도(현재위치) | `set_by_chatbot_request_location_push` | `mapAction.requestLocationPush` |
| 지도(좌표) | `set_by_chatbot_show_location` | `mapAction.showLocation.location.*` |

### 6.6 fbInfoLst (Fallback 대체발송)

RCS 발송 실패 시 자동 대체. **SMS 또는 MMS만 지원.**

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| ch | String | **Y** | `"SMS"` 또는 `"MMS"` |
| title | String | MMS: Y | 제목, 최대 **40바이트** |
| msg | String | **Y** | 대체 메시지 본문 |
| fileId | String | N | MMS 파일 ID (fileIdLst와 택1) |
| fileIdLst | String[] | N | MMS 파일 ID 목록 (최대 3개, fileId와 택1) |

**우리의 fallback 설정:**

```json
// 단문 → SMS fallback
"fbInfoLst": [{ "ch": "SMS", "msg": "동일 본문 텍스트" }]

// 장문 → LMS fallback (MMS 엔드포인트이지만 ch="SMS" 시 90B 초과면 LMS 처리)
// 주의: fbInfoLst의 ch 값은 "SMS" 또는 "MMS"만 가능
// 90바이트 초과 msg를 ch="SMS"로 보내면 msghub가 자동으로 LMS 처리
"fbInfoLst": [{ "ch": "SMS", "msg": "장문 본문 텍스트..." }]

// 이미지 → MMS fallback
"fbInfoLst": [{
  "ch": "MMS",
  "title": "제목",
  "msg": "본문",
  "fileIdLst": ["uploaded_file_id"]
}]
```

### 6.7 RCS 발송 제한사항 종합

| 항목 | 제한 |
|------|------|
| recvInfoLst | **최대 10명/요청** |
| buttons | **최대 4개** |
| cliKey | 1~30자, `[a-zA-Z0-9-_.@]` |
| cliKey 중복 | 같은 날 10분 이내 동일 = 중복 |
| phone | 1~20자, `[0-9-]` |
| messagebaseId | 최대 100자 |
| callback | 최대 100자 |
| footer | 최대 20자 |
| campaignId | 최대 20자 |
| 예약발송 | 현재 + 최대 30일 |
| RCS 이미지 | 최대 **1MB**, JPG/JPEG/PNG/BMP/GIF |
| MMS fallback 이미지 | 최대 **300KB**, JPG만 |
| MMS fallback title | 최대 40바이트 |
| 양방향 | **후불 전용**, 단건 발송 |
| 광고성 (header=1) | footer (080번호) **필수** |

---

## 7. SMS/LMS/MMS Fallback API 상세

RCS fallback이 아닌, 직접 SMS/LMS/MMS를 보내야 할 경우 (예: RCS 브랜드 미등록 기간).

### 7.1 SMS 직접 발송

```
POST /msg/v1/sms
Authorization: Bearer {token}
Content-Type: application/json
Host: api.msghub.uplus.co.kr
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| callback | String | Y | 발신번호 |
| campaignId | String | N | 캠페인 ID |
| agency | Agency | N | 대행사 정보 |
| resvYn | String | N | 예약 (Y/N) |
| resvReqDt | String | N | 예약일시 |
| deptCode | String | N | 부서코드 |
| msg | String | Y | 본문, **최대 90바이트** |
| recvInfoLst | RecvInfo[] | Y | 수신자, **최대 10명** |
| fbInfoLst | FbInfo[] | N | SMS는 최종 채널이므로 미사용 |
| clickUrlYn | String | N | 단축URL |

**mergeData 변수:** `#{변수명}` 문법

### 7.2 LMS/MMS 직접 발송 (JSON)

```
POST /msg/v1/mms
Authorization: Bearer {token}
Content-Type: application/json
Host: api.msghub.uplus.co.kr
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| callback | String | Y | 발신번호 |
| campaignId | String | N | 캠페인 ID |
| agency | Agency | N | 대행사 정보 |
| resvYn | String | N | 예약 |
| resvReqDt | String | N | 예약일시 |
| deptCode | String | N | 부서코드 |
| title | String | Y | 제목, **최대 60바이트** (통신사별 40B 절삭) |
| msg | String | Y | 본문, **최대 2000바이트** |
| fileIdLst | String[] | N | 사전등록 파일 ID (없으면 LMS, 있으면 MMS) |
| recvInfoLst | RecvInfo[] | Y | 수신자, **최대 10명** |
| fbInfoLst | FbInfo[] | N | 미사용 |
| clickUrlYn | String | N | 단축URL |

### 7.3 MMS 직접 발송 (multipart)

```
POST /msg/v1/mms
Authorization: Bearer {token}
Content-Type: multipart/form-data
Host: api.msghub.uplus.co.kr
```

| 파트 | 타입 | 필수 | 설명 |
|------|------|------|------|
| reqMsg | JSON | Y | 메시지 객체 (위 JSON과 동일 구조) |
| parts | File | N | 이미지 파일 (JPG, 최대 300KB, 최대 3개) |

### 7.4 공통 응답 형식

```json
{
  "code": "10000",
  "message": "성공",
  "data": [
    {
      "cliKey": "c42-0-0",
      "msgKey": "tw9Tomlcen.6bTb0O",
      "phone": "01012345678",
      "code": "10000",
      "message": "성공"
    }
  ]
}
```

---

## 8. 파일 업로드 API 상세

### 8.1 엔드포인트

```
POST /file/v1/{ch}
Authorization: Bearer {token}
Content-Type: multipart/form-data
Host: mnt-api.msghub.uplus.co.kr    ← 주의: mnt-api 호스트
```

**Path Parameter:**

| 이름 | 값 | 설명 |
|------|-----|------|
| ch | `mms` | MMS용 파일 업로드 |
| ch | `rcs` | RCS용 파일 업로드 |

### 8.2 Request (multipart)

| 파트 | 타입 | 필수 | 설명 |
|------|------|------|------|
| reqFile | JSON | Y | `{"fileId": "고유ID", "wideYn": "N"}` |
| filePart | File | Y | 이미지 파일 |

- reqFile.fileId: 정규식 `^[a-zA-Z0-9-_]{0,64}$` (직접 지정)
- reqFile.wideYn: 와이드 여부 (카카오용, 일반은 "N")

### 8.3 채널별 파일 제약

| 채널 | 최대 크기 | 허용 포맷 | 비고 |
|------|----------|----------|------|
| **mms** | **300KB** | JPG | 해상도 최대 1500×1440px |
| **rcs** | **1MB** | JPG, JPEG, PNG, BMP, GIF | 유형별 권장 사이즈 상이 |

**RCS 이미지 유형별 권장 사이즈:**

| 유형 | 사이즈 | 비고 |
|------|--------|------|
| MMS형 (세로) | 568×336px | 권장 |
| 이미지 강조형 | 900×900px 또는 900×1200px | **필수** |
| 썸네일형 메인 | 900×560px | **필수** |
| 썸네일형 서브 | 300×300px | **필수** |
| SNS형 | 900×900px | **필수** |
| 슬라이드 (Small) | 360×336px | 권장 |
| 슬라이드 (Medium) | 696×504px | 권장 |

### 8.4 Response

```json
{
  "code": "10000",
  "message": "성공",
  "data": {
    "ch": "rcs",
    "fileId": "my-image-001",
    "fileExpDt": "2026-04-23T16:23:11"
  }
}
```

### 8.5 RCS에서 이미지 참조

업로드 후 mergeData에서 `maapfile://{fileId}` 형식으로 참조:

```json
"mergeData": {
  "media": "maapfile://my-image-001"
}
```

### 8.6 파일 유효기간

- 응답의 `fileExpDt`에 만료일시 포함
- 만료 후 사용 시 에러 21029 (만료된 파일)
- MMS fallback용 파일은 별도로 `ch=mms`로 업로드 필요

### 8.7 구현 주의사항

- 업로드 호스트는 발송과 다름: `mnt-api.msghub.uplus.co.kr`
- 파일 ID는 **클라이언트가 직접 지정** (서버 자동생성 아님)
- RCS와 MMS는 파일 제약이 다르므로 **이미지를 양쪽 모두에 업로드** 필요
  - `POST /file/v1/rcs` — RCS용 (1MB, 다포맷)
  - `POST /file/v1/mms` — MMS fallback용 (300KB, JPG only)
- RCS에서 이미지 참조: `maapfile://{fileId}` (mergeData 내)

---

## 9. 예약 발송

### 9.1 예약 설정

모든 발송 API에서 다음 필드 추가:

```json
{
  "resvYn": "Y",
  "resvReqDt": "2026-04-20 14:30"
}
```

- 형식: `yyyy-MM-dd hh:mm`
- 범위: 현재 ~ +30일
- 타임존: 서버 로컬 시간 (KST 추정)

### 9.2 예약 응답 (일반 발송과 다름)

```json
{
  "code": "10000",
  "message": "성공",
  "data": {
    "regDt": "2026-04-16T11:16:55",
    "webReqId": "SMS9rQTUiu"
  }
}
```

- `webReqId`를 저장해야 취소/조회 가능

### 9.3 예약 목록 조회

```
GET /msg/v1.1/resv/sendList
Authorization: Bearer {token}
Host: api.msghub.uplus.co.kr
```

**Response 필드:**

| 필드 | 설명 |
|------|------|
| webReqId | 예약 요청 ID |
| ch | 채널 |
| callback | 발신번호 |
| senderCnt | 발송 건수 |
| status | 상태 (`SEND_WAIT`, `COMPLETED`) |
| resvSenderYn | 예약 여부 |
| delYn | 삭제 여부 |
| reqDt | 요청일시 |

### 9.4 예약 취소

```
POST /msg/v1/resv/sendCancel
Authorization: Bearer {token}
Content-Type: application/json
Host: api.msghub.uplus.co.kr
```

```json
{
  "webReqId": "SMS9rQTUiu",
  "resvCnclReason": "사용자 취소"
}
```

### 9.5 주의사항

- 예약 최대 범위: 현재 시점 + **30일**
- 타임존: 서버 KST 기준 (별도 타임존 파라미터 없음)
- 예약 응답은 일반 발송과 구조가 다름 (`webReqId` 반환, 개별 `msgKey` 없음)
- 취소 시 `webReqId`가 필수이므로 DB에 반드시 저장

---

## 10. 리포트 (발송 결과) 시스템

### 10.1 3가지 방식

| 방식 | 설명 | 적합한 경우 |
|------|------|------------|
| **Webhook** | msghub → 고객사 서버 POST | **권장.** 실시간, 서버 부하 없음 |
| **Polling** | 고객사 → msghub GET (주기적) | 웹훅 불가 시 |
| **개별 조회** | cliKey로 상태 확인 | 특정 메시지 수동 확인 |

### 10.2 Webhook 방식 (권장)

**등록:** 콘솔 > 프로젝트 > API KEY 상세에서 URL 등록 (API 등록 불가)

**msghub → 고객사 POST 페이로드:**

```json
{
  "rptCnt": 2,
  "rptLst": [
    {
      "msgKey": "lXXYpOIuCd.6cGlYN",
      "cliKey": "c42-0-0",
      "ch": "SMS",
      "resultCode": "10000",
      "resultCodeDesc": "성공",
      "productCode": "SMS",
      "fbReasonLst": null,
      "telco": "KT",
      "rptDt": "2026-04-16T15:01:40"
    },
    {
      "msgKey": "abc123.7dEf2G",
      "cliKey": "c42-0-1",
      "ch": "SMS",
      "resultCode": "10000",
      "resultCodeDesc": "성공",
      "productCode": "LMS",
      "fbReasonLst": [
        {
          "ch": "RCS",
          "fbResultCode": "51004",
          "fbResultDesc": "단말 미지원",
          "telco": "KT"
        }
      ],
      "telco": "SKT",
      "rptDt": "2026-04-16T15:01:42"
    }
  ]
}
```

**리포트 필드:**

| 필드 | 타입 | 설명 |
|------|------|------|
| rptCnt | Integer | 리포트 건수 (최대 100) |
| rptLst[].msgKey | String | msghub 메시지 고유키 |
| rptLst[].cliKey | String | 클라이언트 고유키 (우리가 부여) |
| rptLst[].ch | String | **실제 발송 채널** (SMS/LMS/MMS/RCS) |
| rptLst[].resultCode | String | 결과코드 (10000=성공) |
| rptLst[].resultCodeDesc | String | 결과 설명 |
| rptLst[].productCode | String | 과금 상품코드 |
| rptLst[].fbReasonLst | FbReason[] | fallback 사유 (원래 채널 실패 사유) |
| rptLst[].telco | String | 이통사 (KT/SKT/LGU 등) |
| rptLst[].rptDt | String | 결과 수신 일시 |

**FbReason (fallback이 발생한 경우):**

| 필드 | 설명 |
|------|------|
| ch | 실패한 원래 채널 (예: "RCS") |
| fbResultCode | 실패 사유 코드 |
| fbResultDesc | 실패 사유 설명 |
| telco | 이통사 |

**고객사 응답:**
- `200`: 성공
- `204`: 성공 (처리할 리포트 없음)
- `400`: 실패 → msghub가 **10초 후 재시도**

**웹훅 규칙:**
- 결과는 **1회만** 전달
- 실패 시 10초 후 재시도 (변경 가능)
- 리포트 보관: **72시간** (변경 가능)
- **퍼블릭 URL만 지원** (전용선 불가)

### 10.3 Polling 방식

**Step 1: 리포트 가져오기**

```
GET /msg/v1.2/report
Authorization: Bearer {token}
Host: api.msghub.uplus.co.kr
```

Response: 웹훅 페이로드와 동일 + `rptKey` 추가

```json
{
  "code": "10000",
  "message": "성공",
  "data": {
    "rptKey": "RPsAOqHDhO",
    "rptCnt": 100,
    "rptLst": [ ... ]
  }
}
```

**Step 2: ACK 전달 (120초 이내 필수)**

```
POST /msg/v1.2/report/result
Authorization: Bearer {token}
Content-Type: application/json
Host: api.msghub.uplus.co.kr
```

```json
{
  "rptKeyLst": ["RPsAOqHDhO"]
}
```

**Polling 규칙:**
- 리포트 있으면 → 처리 후 **즉시** 다음 요청
- 리포트 없으면 → **10초 간격** (10초 이내 요청 시 실패)
- 배치 최대 **100건**
- ACK 미전달 시 **120초 후** 동일 리포트 재전송
- 미요청 시 **81시간 후** 리포트 만료

### 10.4 개별 조회 (cliKey 기반)

```
POST /msg/v1/sent
Authorization: Bearer {token}
Content-Type: application/json
Host: api.msghub.uplus.co.kr
```

```json
{
  "cliKeyLst": [
    { "cliKey": "c42-0-0", "reqDt": "2026-04-16" },
    { "cliKey": "c42-0-1", "reqDt": "2026-04-16" }
  ]
}
```

- 최대 **10건**/요청
- 최대 **90일** 조회 가능

**메시지 상태:**

| 상태 | 설명 |
|------|------|
| REG | 접수 완료 |
| ING | 처리 중 |
| DONE | 완료 |
| OVER_DATE | 조회기간 초과 (90일+) |
| INVALID_KEY | 잘못된 키 |

### 10.5 우리의 리포트 전략

1. **1순위: Webhook** — 콘솔에서 URL 등록, FastAPI에 수신 엔드포인트 추가
2. **2순위: 개별 조회** — 웹훅 미수신 건에 대해 `POST /msg/v1/sent`로 보완
3. **Polling은 미사용** — 웹훅이 더 효율적

### 10.6 리포트 보존 기간

| 항목 | 기간 |
|------|------|
| 웹훅 리포트 보관 | **72시간** (실패 시 10초 후 재시도) |
| Polling 미요청 시 만료 | 81시간 |
| Polling ACK 미전달 시 재전송 | 120초 |
| cliKey 개별 조회 | **최대 90일** |

---

## 11. 에러 코드 전체 목록

### 11.1 성공

| 코드 | 설명 |
|------|------|
| 10000 | 성공 |

### 11.2 인증 (20xxx)

| 코드 | 설명 | 조치 |
|------|------|------|
| 20000 | 미발급 API 키 | 키 확인 |
| 20001 | 미허용 IP | IP 등록 |
| 20002 | 비밀번호 불일치 | 해싱 확인 |
| 20003 | 토큰 생성 에러 | 재시도 |
| 20004 | 헤더 데이터 에러 | 헤더 확인 |

### 11.3 공통 API (21xxx)

| 코드 | 서비스 | 설명 |
|------|--------|------|
| 21001 | 공통 | 야간 발송 제한 시간 |
| 21002 | MMS/KKO | 첨부파일 크기 에러 |
| 21003 | MMS/KKO | 등록된 파일 ID 없음 |
| 21004 | MMS/KKO | 파일 수 초과 (최대 3개) |
| 21006 | MMS/KKO | 첨부파일 확장자 에러 |
| 21007 | MMS/KKO | 첨부파일 사이즈 에러 |
| 21012 | 공통 | 요청 건수 초과 |
| 21029 | MMS/KKO | 기등록 파일 만료 |
| 21049 | 공통 | KISA 최초식별코드 없음 |

### 11.4 요청 처리 (29xxx)

| 코드 | 설명 | 재시도 |
|------|------|--------|
| 29000 | 필수값 누락 | N |
| 29001 | 파라미터 에러 | N |
| 29002 | **CPS 초과** | **Y** |
| 29003 | 기타 에러 | N |
| 29004 | Fallback 기타 에러 | N |
| 29005 | 중복 발송 | N |
| 29006 | WRITE 소켓 에러 | Y |
| 29007 | READ 소켓 에러 | Y |
| 29008 | 연동규격 에러 | N |
| 29009 | 요청 데이터 없음 | N |
| 29010 | 잘못된 요청 | N |
| 29011 | 권한 없음 | 재인증 |
| 29012 | 서버 에러 | Y |
| 29015 | 발송 타임아웃 | Y |
| 29016 | 상품정보 없음 | N |
| 29017 | Redis 에러 | Y |
| 29018 | 발송 한도 초과 | N |
| 29019 | DB 에러 | Y |
| 29020 | 전송 용량 초과 | N |
| 29025 | 비허용 IP | 재인증 |
| 29029 | 잘못된 첨부파일 | N |
| 29031 | 재시도 필요 | Y |
| 29032 | 내부 에러 | Y |

### 11.5 SMS 전송 (30xxx)

| 코드 | 설명 |
|------|------|
| 30100 | 빌링 ID 포맷 에러 |
| 30101 | 단말기 메시지 FULL |
| 30102 | 타임아웃 |
| 30103 | 무선망 에러 |
| 30109 | 착신번호 에러 (자릿수) |
| 30110 | 착신번호 에러 (없는 국번) |
| 30114 | 스팸 필터링 |
| 30115 | 야간발송 차단 |
| 30116 | 사전 미등록 발신번호 |
| 30117 | 전화번호 세칙 미준수 |
| 30120 | 번호도용문자차단 가입 번호 |
| 30122 | 단말기 착신거부 |
| 30124 | 비가입자/결번/서비스정지 |
| 30125 | 비가입자/결번/서비스정지 |
| 30126 | 전원 꺼짐 |
| 30127 | 음영지역 |

### 11.6 MMS 전송 (31xxx)

| 코드 | 설명 |
|------|------|
| 31000 | 잘못된 번호 |
| 31001 | 잘못된 콘텐츠 |
| 31100 | 포맷 에러 |
| 31101 | 수신번호 에러 |
| 31102 | 콘텐츠 사이즈/수 초과 |
| 31104 | MMS 미지원 단말 |
| 31106 | 전송시간 초과 |
| 31107 | 전원 꺼짐 |
| 31108 | 음영지역 |
| 31112 | 통신사 내부 실패 |
| 31118 | 내부 에러 |
| 31119 | 스팸 |
| 31121 | 사전 미등록 발신번호 |
| 31122 | 세칙 미준수 발신번호 |
| 31124 | 번호도용차단 가입 번호 |

### 11.7 RCS (50xxx ~ 65xxx, 주요)

| 코드 | 설명 |
|------|------|
| 50201 | TPS 초과 |
| 50202 | Quota 초과 |
| 51004 | Parameter 에러 |
| 54004 | 전달 가능성 (재시도) |
| 55806 | 전달 가능성 (재시도) |
| 55820 | 전달 가능성 (재시도) |

### 11.8 재시도 필요 코드 모음

```python
RETRYABLE_CODES = {
    "29002",  # CPS 초과
    "29006",  # WRITE 소켓
    "29007",  # READ 소켓
    "29012",  # 서버 에러
    "29015",  # 타임아웃
    "29017",  # Redis
    "29019",  # DB
    "29031",  # 재시도 필요
    "29032",  # 내부 에러
    "21400",  # 내부 에러
    "22004",  # 내부 에러
    "23004",  # 내부 에러
    "23005",  # 내부 에러
    "31112",  # 통신사 내부
    "31118",  # 내부 에러
    "41007",  # RCS 전달 가능성
    "54004",  # RCS 전달 가능성
    "55806",  # RCS 전달 가능성
    "55820",  # RCS 전달 가능성
    "65999",  # 내부 에러
}
# + HTTP 5xx
```

---

## 12. 비용 계산 로직

### 12.1 요금표 (후불, VAT 별도)

```python
PRICE_TABLE = {
    # RCS
    "RCS_CHAT": 8,       # RCS 양방향 (단문)
    "RCS_LMS": 27,       # RCS LMS (장문)
    "RCS_ITMPL": 40,     # RCS 이미지 템플릿
    "RCS_MMS": 85,       # RCS MMS
    # Fallback (SMS/LMS/MMS)
    "SMS": 9,
    "LMS": 27,
    "MMS": 85,
}
```

### 12.2 비용 결정 시점

| 시점 | 방식 | 표시 |
|------|------|------|
| **미리보기** | 예상 범위 (RCS 전체 성공 ~ 전체 fallback) | "800 ~ 900원" |
| **확인 모달** | 동일 예상 범위 | "예상 비용: 800 ~ 900원" |
| **발송 결과** | 실제 비용 (리포트의 채널 + 성공/실패 기반) | "총 비용: 801원 (실패 3건 제외)" |

### 12.3 실제 비용 계산

```python
def calculate_message_cost(message: Message) -> int:
    """리포트 수신 후 건별 비용 계산"""
    if message.result_code != "10000":  # 실패
        return 0

    # productCode + channel로 요금 결정
    # msghub 리포트: ch=실제발송채널, productCode=과금상품
    mapping = {
        ("RCS", "CHAT"): 8,
        ("RCS", "SMS"): 17,     # 사용 안 함 (양방향 대신)
        ("RCS", "LMS"): 27,
        ("RCS", "MMS"): 85,
        ("RCS", "ITMPL"): 40,
        ("SMS", "SMS"): 9,
        ("LMS", "LMS"): 27,
        ("MMS", "MMS"): 85,
    }
    return mapping.get((message.channel, message.product_code), 0)
```

### 12.4 캠페인 비용 집계

```python
# Campaign 모델에 추가
class Campaign:
    total_cost: int = 0          # 총 비용 (성공 건만)
    rcs_count: int = 0           # RCS 성공 건수
    sms_count: int = 0           # SMS fallback 건수
    lms_count: int = 0           # LMS fallback 건수
    mms_count: int = 0           # MMS fallback 건수
```

### 12.5 예상 비용 계산 (미리보기)

```python
def estimate_cost(msg_type: str, recipient_count: int) -> tuple[int, int]:
    """(최소비용=RCS전체성공, 최대비용=전체fallback) 반환"""
    rates = {
        "short": (8, 9),      # RCS양방향 8원, SMS 9원
        "long": (27, 27),     # RCS LMS 27원, LMS 27원
        "image": (40, 85),    # RCS이미지 40원, MMS 85원
    }
    min_rate, max_rate = rates[msg_type]
    return (min_rate * recipient_count, max_rate * recipient_count)
```

---

## 13. DB 스키마 변경

### 13.1 Setting 키

```
msghub.api_key            # API 키 (is_secret=True)
msghub.api_pwd            # API 비밀번호 (is_secret=True)
msghub.env                # "production" 또는 "qa"
msghub.brand_id           # RCS 브랜드 ID
msghub.chatbot_id         # RCS 양방향 챗봇 ID
```

NCP 관련 키 (`ncp.*`) 는 마이그레이션에서 삭제:
```sql
DELETE FROM setting WHERE key LIKE 'ncp.%';
```

### 13.2 MsghubRequest (NcpRequest 교체)

```python
class MsghubRequest(Base):
    __tablename__ = "msghub_request"

    id: int                   # PK
    campaign_id: int          # FK → Campaign
    chunk_index: int          # 청크 순번
    response_code: str        # "10000" 등
    response_message: str     # "성공" 등
    error_body: str | None    # 에러 시 원문
    sent_at: datetime         # 발송 시각
```

### 13.3 Message 모델

```python
class Message(Base):
    __tablename__ = "message"

    id: int                   # PK
    campaign_id: int          # FK → Campaign
    msghub_request_id: int    # FK → MsghubRequest
    cli_key: str              # 클라이언트 고유키
    msg_key: str | None       # msghub 메시지키
    to_number: str            # 수신번호 (정규화)
    to_number_raw: str        # 원본 입력
    status: str               # REG/ING/DONE/FAILED
    result_code: str | None   # "10000" 등
    result_desc: str | None   # 결과 설명
    channel: str | None       # 실제 발송 채널 (RCS/SMS/LMS/MMS)
    product_code: str | None  # 과금 상품코드
    cost: int = 0             # 건당 비용 (원)
    telco: str | None         # 이통사
    fb_reason: str | None     # JSON: fallback 사유 [{ch, code, desc}]
    report_dt: datetime | None  # 리포트 수신 시간
```

### 13.4 Campaign 모델

```python
class Campaign(Base):
    # 기존 필드 유지 + 변경/추가:
    message_type: str         # "short" / "long" / "image" (채널 중립)
    rcs_message_base_id: str | None  # 사용한 messagebaseId
    web_req_id: str | None    # 예약발송 시 msghub webReqId
    total_cost: int = 0       # 총 비용 (성공 건만, 원)
    rcs_count: int = 0        # RCS 채널 성공 건수
    fallback_count: int = 0   # SMS/LMS/MMS fallback 건수
```

### 13.5 Caller 모델

```python
class Caller(Base):
    # 기존 필드 유지 + 추가:
    rcs_enabled: bool = False       # RCS 챗봇 등록 여부
    rcs_chatbot_id: str | None      # 챗봇 ID (nullable)
```

### 13.6 Attachment 모델

```python
class Attachment(Base):
    # 변경:
    msghub_file_id: str       # (was ncp_file_id)
    file_expires_at: datetime # (was ncp_expires_at)
    channel: str              # "mms" 또는 "rcs" (신규)
```

---

## 14. 영향 파일 및 변경 수준

### 14.1 삭제 파일

| 파일 | 사유 |
|------|------|
| `app/ncp/` (전체 디렉토리) | msghub로 완전 교체 |
| `app/ncp/client.py` | → `app/msghub/client.py` |
| `app/ncp/signature.py` | → `app/msghub/auth.py` (JWT) |
| `app/ncp/codes.py` | → `app/msghub/codes.py` |
| `app/services/poller.py` | → `app/routes/webhook.py` + `app/services/report.py` |
| `tests/test_signature.py` | HMAC 불필요 |
| `tests/test_poller.py` | 폴러 불필요 |

### 14.2 신규 파일

| 파일 | 설명 |
|------|------|
| `app/msghub/__init__.py` | 패키지 |
| `app/msghub/auth.py` | TokenManager (SHA512 해싱, JWT 발급/갱신/캐싱) |
| `app/msghub/client.py` | MsghubClient (RCS/SMS/LMS/MMS 발송, 파일 업로드) |
| `app/msghub/codes.py` | 에러 코드 매핑 + 설명 |
| `app/msghub/schemas.py` | 요청/응답 데이터클래스 |
| `app/routes/webhook.py` | 리포트 웹훅 수신 엔드포인트 |
| `app/services/report.py` | 웹훅 처리 + cliKey 개별조회 fallback |
| `app/services/cost.py` | 비용 계산 로직 |

### 14.3 수정 파일

| 파일 | 변경 수준 | 설명 |
|------|----------|------|
| `app/models.py` | **대폭** | NcpRequest→MsghubRequest, Message/Campaign/Caller/Attachment 변경 |
| `app/services/compose.py` | **대폭** | RCS 라우팅, 10명 청크, cliKey, 비용 예상 |
| `app/services/image.py` | **중간** | RCS 1MB/다포맷 + MMS 300KB/JPG 이중 처리 |
| `app/main.py` | **중간** | NCP client/Poller 제거 → TokenManager/웹훅 등록 |
| `app/routes/compose.py` | **중간** | 비용 미리보기, 채널 표시 |
| `app/routes/admin.py` | **대폭** | NCP 폼 삭제 → msghub + RCS 폼 |
| `app/routes/setup.py` | **대폭** | NCP 스텝 삭제 → msghub + RCS 스텝 |
| `app/routes/campaigns.py` | **중간** | 채널/비용/fallback 표시, CSV 확장 |
| `app/routes/dashboard.py` | **소폭** | RCS 도달률 카드 추가 |
| `app/config.py` | **소폭** | NCP 설정 제거 |
| `app/templates/compose.html` | **중간** | 바이트카운터+요금, 미리보기 비용 |
| `app/templates/campaigns/detail.html` | **대폭** | 채널분포 바, 비용 상세, 채널/FB/비용 열 |
| `app/templates/campaigns/list.html` | **소폭** | 유형 용어, 비용 열 |
| `app/templates/admin/settings.html` | **대폭** | NCP→msghub+RCS 폼 전면 교체 |
| `app/templates/admin/callers.html` | **중간** | RCS 열 추가, 힌트 변경 |
| `app/templates/setup.html` | **대폭** | NCP→msghub+RCS 스텝 전면 교체 |
| `app/templates/_layout/base.html` | **최소** | NCP 문구 있으면 제거 |
| `alembic/versions/` | **신규** | 마이그레이션 스크립트 |

---

## 15. 구현 순서

### Phase 1: 코어 교체 — msghub 클라이언트 + DB

> NCP 코드 삭제, msghub 기반 SMS/LMS/MMS 직접 발송 동작까지

1. `app/ncp/` 디렉토리 전체 삭제
2. `app/services/poller.py` 삭제
3. `tests/test_signature.py`, `tests/test_poller.py` 삭제
4. `app/msghub/auth.py` — TokenManager
5. `app/msghub/client.py` — MsghubClient (SMS/LMS/MMS + RCS)
6. `app/msghub/codes.py` — 에러 코드
7. `app/msghub/schemas.py` — 데이터클래스
8. DB 마이그레이션 — 모델 변경, NCP 설정 삭제
9. `app/models.py` — 새 모델 반영
10. `app/main.py` — NCP→msghub 초기화 교체
11. `app/services/compose.py` — msghub 클라이언트 + 10명 청크 + cliKey

### Phase 2: 리포트 + 비용

12. `app/routes/webhook.py` — 웹훅 수신 엔드포인트
13. `app/services/report.py` — 웹훅 처리 + cliKey 조회 fallback
14. `app/services/cost.py` — 비용 계산
15. 콘솔에서 웹훅 URL 등록

### Phase 3: RCS 라우팅

16. `app/services/compose.py` — RCS 우선 라우팅 + fbInfoLst
17. `app/services/image.py` — RCS용 이미지 처리 (1MB, 다포맷)
18. `app/msghub/client.py` — RCS 양방향 발송 메서드

### Phase 4: UI 전면 교체

19. `app/routes/admin.py` + `templates/admin/settings.html` — msghub+RCS 설정
20. `app/routes/setup.py` + `templates/setup.html` — msghub+RCS 셋업 마법사
21. `templates/admin/callers.html` — RCS 열 + 등록 번호만 발송
22. `templates/compose.html` — 바이트카운터+요금, 미리보기 비용, 확인 모달
23. `templates/campaigns/detail.html` — 채널분포 바, 비용 상세, 채널/FB/비용 열
24. `templates/campaigns/list.html` — 유형 용어 + 비용
25. `app/routes/dashboard.py` + 대시보드 템플릿 — RCS 도달률 카드
26. NCP 텍스트 전체 grep → 잔여 삭제
27. E2E 테스트 — 전체 플로우 검증
