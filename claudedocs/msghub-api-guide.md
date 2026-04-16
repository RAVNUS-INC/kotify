# U+ msghub API 가이드

> 작성일: 2026-04-16
> 참조: https://docs2.msghub.uplus.co.kr/api/intro

---

## 목차

1. [플랫폼 개요](#1-플랫폼-개요)
2. [인증 (Authentication)](#2-인증-authentication)
3. [SMS 발송 API](#3-sms-발송-api)
4. [LMS/MMS 발송 API](#4-lmsmms-발송-api)
5. [MMS 파일 첨부 방식](#5-mms-파일-첨부-방식)
6. [통합 발송 API (템플릿 기반)](#6-통합-발송-api-템플릿-기반)
7. [예약 발송](#7-예약-발송)
8. [발송 결과 조회 & 웹훅](#8-발송-결과-조회--웹훅)
9. [에러 코드](#9-에러-코드)
10. [주요 제약사항 요약](#10-주요-제약사항-요약)

---

## 1. 플랫폼 개요

U+ Message Hub는 LG U+에서 제공하는 기업 메시징 플랫폼으로 SMS, LMS, MMS, RCS, 카카오톡(알림톡/친구톡), 모바일 PUSH를 지원한다.

### Base URL

| 환경 | URL |
|------|-----|
| **운영 (인터넷)** | `https://api.msghub.uplus.co.kr` |
| **QA (인터넷)** | `https://api.msghub-qa.uplus.co.kr` |
| **운영 (전용선)** | `https://api-direct.msghub.uplus.co.kr` (IP: 1.209.4.60 / 1.209.4.75, Port: 443) |
| **QA (전용선)** | `https://api-direct.msghub-qa.uplus.co.kr` (IP: 1.209.4.92 / 1.209.4.105, Port: 443) |

### 통신 규격

- HTTP 메서드: POST (생성), PUT (수정), GET (조회), DELETE (삭제)
- Content-Type: `application/json` (파일 업로드만 `multipart/form-data`)
- 인코딩: UTF-8
- CORS 미지원 — 브라우저에서 직접 호출 불가 (서버 사이드 전용)

---

## 2. 인증 (Authentication)

msghub는 **JWT 토큰** 방식을 사용한다.

### 2.1 토큰 수명

| 토큰 | 만료 | 권장 갱신 시점 |
|------|------|---------------|
| Access Token | 1시간 | 만료 10분 전 |
| Refresh Token | 25시간 | 만료 30분 전 |

### 2.2 인증 요청

```
POST /auth/v1/{randomStr}
Content-Type: application/json
```

**비밀번호 암호화 절차:**

```
step1 = Base64(SHA512(apiPwd))
step2 = Base64(SHA512(step1 + "." + randomStr))
→ 최종 apiPwd = step2
```

| 파라미터 | 위치 | 필수 | 설명 |
|---------|------|------|------|
| `randomStr` | Path | Y | 암호화용 랜덤 문자열 (영숫자/하이픈/언더스코어, 최대 20자) |
| `apiKey` | Body | Y | API 키 |
| `apiPwd` | Body | Y | 위 절차로 암호화된 비밀번호 |

**요청 예시:**

```bash
curl -X POST "https://api.msghub.uplus.co.kr/auth/v1/abc123" \
  -H "Content-Type: application/json" \
  -d '{"apiKey": "mykey", "apiPwd": "fwxbxKFf7Rj..."}'
```

**응답:**

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

### 2.3 토큰 갱신

```
PUT /auth/v1/refresh
Authorization: Bearer {refreshToken}
```

새 access token 발급 (1시간). refresh token은 재발급되지 않음.

### 2.4 보안 요구사항

- API 키에 최소 1개 이상의 **소스 IP 대역** 등록 필수
- 인증 요청 IP도 허용 범위에 포함되어야 함

---

## 3. SMS 발송 API

```
POST /msg/v1/sms
Authorization: Bearer {token}
Content-Type: application/json
```

### 요청 본문

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `callback` | String | Y | 발신번호 (사전 등록 필요) |
| `campaignId` | String | N | 캠페인 ID |
| `agency` | Agency | N | 대행사 정보 |
| `resvYn` | String | N | 예약 발송 여부 ("Y"/"N") |
| `resvReqDt` | String | N | 예약 일시 (`yyyy-MM-dd hh:mm`) |
| `deptCode` | String | N | 부서 코드 |
| `msg` | String | Y | 메시지 본문 (**최대 90바이트**) |
| `recvInfoLst` | RecvInfo[] | Y | 수신자 목록 (**최대 10명**) |
| `fbInfoLst` | FbInfo[] | N | 대체 발송 (SMS는 최종 채널이므로 미사용) |
| `clickUrlYn` | String | N | 단축 URL 사용 여부 |

### RecvInfo 스키마

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `cliKey` | String | Y | 클라이언트 고유키 (정규식: `^[a-zA-Z0-9-_.@]{1,30}$`) |
| `phone` | String | Y | 수신번호 (정규식: `^[0-9-]{1,20}$`) |
| `mergeData` | HashMap | N | 변수 치환 데이터 (`#{변수명}` 문법) |
| `userCustomFields` | HashMap | N | 웹훅 전달용 커스텀 필드 |

### 요청 예시

```json
{
  "callback": "0212341234",
  "msg": "테스트 문자입니다",
  "recvInfoLst": [
    { "cliKey": "msg-001", "phone": "01012345678" },
    { "cliKey": "msg-002", "phone": "01087654321" }
  ]
}
```

### 응답

```json
{
  "code": "10000",
  "message": "성공",
  "data": [
    {
      "cliKey": "msg-001",
      "msgKey": "tw9Tomlcen.6bTb0O",
      "phone": "01012345678",
      "code": "10000",
      "message": "성공"
    },
    {
      "cliKey": "msg-002",
      "msgKey": "tw9Tomlcen.7cUc1P",
      "phone": "01087654321",
      "code": "10000",
      "message": "성공"
    }
  ]
}
```

---

## 4. LMS/MMS 발송 API

LMS와 MMS는 **동일 엔드포인트**를 사용한다. 파일 첨부 유무로 구분.

```
POST /msg/v1/mms
Authorization: Bearer {token}
Content-Type: application/json
```

### 요청 본문

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `callback` | String | Y | 발신번호 |
| `campaignId` | String | N | 캠페인 ID |
| `agency` | Agency | N | 대행사 정보 |
| `resvYn` | String | N | 예약 발송 여부 |
| `resvReqDt` | String | N | 예약 일시 |
| `deptCode` | String | N | 부서 코드 |
| `title` | String | Y | 제목 (**최대 60바이트**, 통신사에 따라 40바이트로 절삭) |
| `msg` | String | Y | 본문 (**최대 2000바이트**) |
| `fileIdLst` | String[] | N | 사전등록 파일 ID 목록 (MMS일 때만 사용) |
| `recvInfoLst` | RecvInfo[] | Y | 수신자 (**최대 10명**) |
| `fbInfoLst` | FbInfo[] | N | 대체 발송 (MMS는 최종 채널이므로 미사용) |
| `clickUrlYn` | String | N | 단축 URL |

### LMS vs MMS 구분

- `fileIdLst` 없음 → **LMS** (장문 텍스트만)
- `fileIdLst` 있음 → **MMS** (텍스트 + 이미지/오디오/비디오)

### 요청 예시 (LMS)

```json
{
  "callback": "0212341234",
  "title": "공지사항",
  "msg": "장문 메시지 본문입니다. 90바이트를 초과하는 긴 메시지...",
  "recvInfoLst": [
    { "cliKey": "lms-001", "phone": "01012345678" }
  ]
}
```

### 요청 예시 (MMS — 사전등록 파일)

```json
{
  "callback": "0212341234",
  "title": "이벤트 안내",
  "msg": "이미지가 포함된 MMS입니다",
  "fileIdLst": ["FLETt9wbx"],
  "recvInfoLst": [
    { "cliKey": "mms-001", "phone": "01012345678" }
  ]
}
```

---

## 5. MMS 파일 첨부 방식

### 방식 A: 사전등록 파일 ID

1. 이미지 사전등록 API로 업로드 → `fileId` 수신
2. `POST /msg/v1/mms`의 `fileIdLst`에 해당 ID 포함
3. **반복 사용에 적합** (같은 이미지 여러 번 발송)

### 방식 B: multipart 직접 첨부

```
POST /msg/v1/mms
Authorization: Bearer {token}
Content-Type: multipart/form-data
```

| 파트 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `reqMsg` | JSON | Y | 메시지 객체 (callback, title, msg, recvInfoLst 등) |
| `parts` | File | N | 첨부 이미지 파일 |

```bash
curl -X POST "https://api.msghub.uplus.co.kr/msg/v1/mms" \
  -H "Authorization: Bearer eyJhbG..." \
  -H "Content-Type: multipart/form-data" \
  -F 'reqMsg={"callback":"0212341234","title":"MMS","msg":"본문","recvInfoLst":[{"cliKey":"k1","phone":"01012345678"}],"fbInfoLst":[]}' \
  -F "parts=@image.jpg;type=image/jpeg"
```

### 파일 제약조건

| 항목 | 제한 |
|------|------|
| 허용 포맷 | JPG (이미지), MMF (오디오), K3G (비디오) |
| 최대 파일 수 | 3개/메시지 |
| 최대 파일 크기 | 300KB/파일 |

---

## 6. 통합 발송 API (템플릿 기반)

콘솔에서 사전 구성한 템플릿으로 발송. 채널 우선순위와 fallback 체인이 템플릿에 정의됨.

```
POST /msg/v1.1/send
Authorization: Bearer {token}
Content-Type: application/json
```

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `tmpltCode` | String | Y | 통합 발송 템플릿 코드 |
| `campaignId` | String | N | 캠페인 ID |
| `resvYn` | String | N | 예약 여부 |
| `resvReqDt` | String | N | 예약 일시 |
| `recvInfoLst` | SmartRecvInfo[] | Y | 수신자 (최대 10명) |
| `clickUrlYn` | String | Y | 단축 URL 사용 여부 |

### SmartRecvInfo

| 필드 | 타입 | 필수 | 설명 |
|------|------|------|------|
| `cliKey` | String | Y | 클라이언트 고유키 |
| `phone` | String | Y | 수신번호 |
| `callback` | String | N | 채널별 발신번호 오버라이드 |
| `cuid` | String | Y | 앱 로그인 사용자 ID |
| `kvData` | HashMap | N | 템플릿 변수 데이터 |
| `fileData` | HashMap | N | 파일 데이터 (예: `{"mms.1":"FLETt9wbx"}`) |
| `userCustomFields` | HashMap | N | 웹훅 전달 커스텀 필드 |

---

## 7. 예약 발송

모든 발송 API에서 다음 필드를 추가하면 예약 발송:

```json
{
  "resvYn": "Y",
  "resvReqDt": "2026-04-20 14:30"
}
```

### 예약 관리 API

| 엔드포인트 | 메서드 | 설명 |
|-----------|--------|------|
| `/msg/v1/resv/sendList` | GET | 예약 발송 목록 조회 (v1) |
| `/msg/v1.1/resv/sendList` | GET | 예약 발송 목록 조회 (v1.1, 간소화 응답) |
| `/msg/v1/resv/sendCancel` | POST | 예약 발송 취소 |

**취소 요청:**

```json
{
  "webReqId": "SMS9rQTUiu",
  "resvCnclReason": "취소 사유"
}
```

---

## 8. 발송 결과 조회 & 웹훅

### 8.1 MO (수신 메시지) 조회

**폴링 방식:**
```
GET /mo/v1/msg
```

**웹훅 방식 (권장):**
- 콘솔에서 웹훅 URL 등록
- 수신 시 해당 URL로 POST 호출

**MO 웹훅 페이로드:**

```json
{
  "moCnt": 1,
  "moLst": [
    {
      "moKey": "pcNUC3QGVk.6cDbSU",
      "moNumber": "12341234",
      "moType": "SMSMO",
      "moCallback": "01012340000",
      "productCode": "SMSMO",
      "moTitle": null,
      "moMsg": "답장 내용",
      "telco": "LGU",
      "contentCnt": 0,
      "contentInfoLst": null,
      "moRecvDt": "2022-02-23 11:36:38"
    }
  ]
}
```

### 8.2 발송 결과 (Delivery Report)

- `RecvInfo.userCustomFields`에 넣은 데이터가 웹훅으로 전달됨
- 웹훅 URL은 콘솔에서 API 키별로 설정
- 구체적인 리포트 포맷은 콘솔에서 구성

> msghub는 **웹훅 기반 Delivery Report**를 지원하므로 폴링 없이 실시간 결과 수신 가능

---

## 9. 에러 코드

### 성공

| 코드 | 설명 |
|------|------|
| `10000` | 성공 |

### 인증 에러 (HTTP 401)

| 코드 | 설명 |
|------|------|
| `20000` | 미등록 API 키 |
| `20001` | 비허용 IP |
| `20002` | 비밀번호 불일치 |
| `20003` | 토큰 생성 에러 |
| `20004` | 헤더 데이터 에러 |
| `29011` | 권한 없음 (재인증 필요) |
| `29025` | 비허용 IP (재인증) |

### 요청 에러 (HTTP 400)

| 코드 | 설명 | 재시도 |
|------|------|--------|
| `29000` | 필수값 누락 | N |
| `29001` | 파라미터 에러 | N |
| `29002` | CPS 초과 | **Y (재시도 필요)** |
| `29005` | 중복 발송 | N |
| `29010` | 유효하지 않은 요청 | N |
| `29015` | 발송 타임아웃 | Y |
| `29018` | 발송 한도 초과 (HTTP 200) | N |
| `29020` | 전송 용량 초과 | N |
| `21001` | 야간 발송 제한 시간 | N |
| `21012` | 요청 건수 초과 | N |

### 파일/MMS 에러

| 코드 | 설명 |
|------|------|
| `21002` | 첨부파일 크기 에러 |
| `21003` | 등록된 파일 ID 없음 |
| `21004` | 파일 수 초과 (최대 3개) |
| `21006` | 첨부파일 확장자 에러 |
| `21007` | 첨부파일 크기 에러 |
| `21029` | 기등록 파일 만료 |
| `29029` | 유효하지 않은 첨부파일 |

### SMS 전송 에러 (30xxx)

| 코드 | 설명 |
|------|------|
| `30109`/`30110` | 유효하지 않은 번호 |
| `30114` | 스팸 필터링 |
| `30116` | 미등록 발신번호 |
| `30126` | 전원 꺼짐 |
| `30127` | 음영지역 |

### MMS 전송 에러 (31xxx)

| 코드 | 설명 |
|------|------|
| `31000` | 유효하지 않은 번호 |
| `31001` | 콘텐츠 에러 |
| `31102` | 크기/수량 초과 |
| `31104` | 미지원 단말 |
| `31106` | 전송 타임아웃 |
| `31107` | 전원 꺼짐 |
| `31108` | 음영지역 |

### 재시도 필요 에러 코드

`29002`, `49xxx`, `21400`, `22004`, `23004`, `23005`, `29017`, `29019`, `29032`, `31112`, `31118`, `65999`, HTTP 5xx

---

## 10. 주요 제약사항 요약

| 항목 | 제한 |
|------|------|
| **수신자/요청** | SMS/LMS/MMS: **10명**, RCS 단방향: **10명**, RCS 양방향: **1명** |
| **SMS 본문** | 최대 **90바이트** |
| **LMS 본문** | 최대 **2000바이트** |
| **LMS/MMS 제목** | 최대 **60바이트** (통신사별 40B 절삭) |
| **MMS 첨부** | 최대 **3파일**, **300KB/파일**, JPG/MMF/K3G |
| **RCS 이미지** | 최대 **1MB/파일**, JPG/JPEG/PNG/BMP/GIF |
| **RCS 버튼** | 최대 **4개** |
| **cliKey** | 1~30자, `[a-zA-Z0-9-_.@]`, 10분 내 중복 금지 |
| **phone** | 1~20자, `[0-9-]` |
| **예약 발송** | 현재 + 최대 **30일** |
| **Access Token** | **1시간** 유효, 만료 10분 전 갱신 |
| **Refresh Token** | **25시간** 유효, 만료 30분 전 갱신 |
| **IP 허용** | API 키당 최소 1개 소스 IP 등록 **필수** |
| **웹훅 리포트** | 72시간 보관, 실패 시 10초 재시도 |
| **cliKey 조회** | 최대 **90일**, 10건/요청 |
| **CORS** | **미지원** — 서버 사이드 전용 |
| **광고성 (header=1)** | footer (080 수신거부 번호) **필수** |

### 호스트별 용도

| 용도 | 상용 호스트 |
|------|-----------|
| 인증/리포트 | `https://api.msghub.uplus.co.kr` |
| 메시지 발송 | `https://api-send.msghub.uplus.co.kr` |
| 파일/관리 | `https://mnt-api.msghub.uplus.co.kr` |

### 재시도 필요 에러 코드

```
29002, 29006, 29007, 29012, 29015, 29017, 29019, 29031, 29032,
21400, 22004, 23004, 23005, 31112, 31118, 41007, 54004, 55806,
55820, 65999, HTTP 5xx
```
