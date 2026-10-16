# 2.3.2 통합 RCS 메시지
> 원문: https://doc.msghub.uplus.co.kr/rest-api/02메시지발송/020302rcs_integrated/ · 확인일 2026-10-16

통합 RCS 는 단말 제조사와 상관없이 국내 이통 3사가 제공하는 RCS 표준 규격이다. 엔드포인트는 안드로이드 RCS([03a-rcs-android.md](03a-rcs-android.md))와 같고 `messagebaseId` 와 일부 필드 제약만 다르다. 버튼·칩·`recvInfoLst`·`fbInfoLst`·Agency 객체는 03a 의 [공통 개념](03a-rcs-android.md#공통-개념) 과 동일하므로 거기를 참고한다.

## 한눈에 보기

| 기능 | Method | 경로 | 호스트 |
|---|---|---|---|
| 통합 RCS 발송 v1.1 (단방향) | POST | `/rcs/v1.1` | api-send |
| 통합 RCS 양방향 발송 v1.1 | POST | `/rcs/bi/v1.1` | api-send |

공통 헤더: `Authorization`(●, 사용자 인증 토큰, 예: `Bearer {token}`), `Content-Type`(●, `application/json`).

## 안드로이드 RCS 와의 차이 (요약)

| 항목 | 안드로이드 RCS (03a) | 통합 RCS |
|---|---|---|
| `header` | `0` 정보성 / `1` 광고성 | `0` 만 가능 |
| `footer` (무료수신거부 번호) | 필드 있음 (광고성이면 필수) | 필드 없음. 본문 끝에 직접 표기, 글자수 포함 |
| 광고 표기 | `header=1` + `footer` | 제목 또는 본문에 직접 `(광고)` 표기, 글자수 포함 |
| `clickUrlYn` (단축URL) | 있음 | 없음 |
| `copyAllowed` | 있음 | 없음 |
| `messagebaseId` | 유형별 고정 코드 | 고정 코드(RP…) + 등록한 템플릿 코드(IBR…/UBR…) |
| `productCode` | SMS/LMS/MMS/ITMPL/CHAT | 예시에 없음 (대행사만 필수) |

## 통합 RCS 발송 (단방향)

`POST /rcs/v1.1`

통합 RCS 메시지를 보낸다. 1건에 수신자 최대 10명까지 동보 발송한다.

### Request Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| resvYn | String | | 1 | 예약발송 여부 (Y/N) |
| resvReqDt | String | | - | 예약 발송 시각 (예: `2025-07-13 13:15`) |
| agency | Object | | - | 대행사 정보 |
| messagebaseId | String | ● | 100 | 메시지베이스 ID ([공통 개념](#메시지베이스-id)) |
| callback | String | ● | 100 | 발신번호 / 양방향 대화방 ID |
| header | String | ● | 1 | `0` 만 가능 |
| expiryOption | String | | 1 | 만료(expire) 옵션 |
| campaignId | String | | 20 | 캠페인 ID |
| deptCode | String | | 20 | 부서 코드 |
| buttons | Array | | - | 버튼 (구조는 [03a](03a-rcs-android.md#버튼-구조-buttons)와 동일) |
| recvInfoLst | Array | ● | 10개 | 수신자 목록 |
| fbInfoLst | Array | | - | 대체발송 정보 목록 |
| brandId | String | | - | 브랜드 ID (대행사는 필수) |
| brandKey | String | | - | 브랜드 KEY (대행사는 필수) |
| productCode | String | | - | 상품 코드 (대행사는 필수) |

`recvInfoLst[]`: `cliKey`(●, 최대 30자), `phone`(●, 최대 20자, 국제문자는 맨 앞 `0` 없이), `mergeData`(선택), `userCustomFields`(선택).

`fbInfoLst[]`: `ch`(●), `title`(MMS 면 필수), `msg`(●), `fileId`(`fileIdLst` 와 택1), `fileIdLst`(최대 3개). 대체발송 채널은 SMS, MMS 만 가능하고 메인 채널과 같을 수 없다.

### Response (`data[]`)

| 필드 | 타입 | 설명 |
|---|---|---|
| data[].cliKey | String | 클라이언트 키 |
| data[].msgKey | String | 메시지 키 |
| data[].phone | String | 수신번호 |
| data[].code | String | 수신자별 결과 코드 |
| data[].message | String | 수신자별 결과 메시지 |

예약발송이면 `data` 가 객체: `data.regDt`(예약 등록 시각, 예 `2026-04-08T11:16:55`), `data.webReqId`(예약 요청 ID).

### 예시 (통합 RCS SMS 카드)

```json
{
  "resvYn": "N",
  "messagebaseId": "RPSSAXX001",
  "callback": "07000000000",
  "header": "0",
  "expiryOption": "1",
  "recvInfoLst": [
    {
      "cliKey": "test001",
      "phone": "01000000000",
      "mergeData": { "name": "이름", "description": "{{name}}님 안녕하세요." },
      "userCustomFields": { "key1": "value1", "key2": 123 }
    }
  ],
  "buttons": [
    { "suggestions": [ { "action": {
      "displayText": "버튼1",
      "postback": { "data": "set_by_chatbot_open_url" },
      "urlAction": { "openUrl": { "url": "https://example.com" } } } } ] }
  ]
}
```

### 유형별 요약

| 유형 | messagebaseId | mergeData 키 |
|---|---|---|
| 통합 RCS SMS 카드 | `RPSSAXX001` | name, description |
| 통합 RCS LMS 카드 | `RPLSAXX001` | name, description, title |
| 통합 RCS MMS 카드 T형 | `RPMSMTX001` | name, description, title, media |
| 통합 RCS MMS 카드 M형 | `RPMSMMX001` | name, description, title, media |
| 통합 이미지 템플릿 M / T | 등록한 템플릿 코드 (예: `IBR.…`) | name, description, title, media |
| 통합 정보성 템플릿 승인형 | 등록한 템플릿 코드 (예: `UBR.…`) | name, description, title |
| 통합 프리템플릿 | 브랜드별 프리템플릿 코드 (예: `UBR.…-RPTFXXX001`) | description |

`media` 는 `maapfile://{fileId}` 형식. `mergeData` 의 `{{변수명}}` 은 같은 객체의 키 값으로 치환된다.

> 주의
> - 동보 발송: 1건에 수신자 최대 10명. TPS 는 수신자 수 기준(수신자 5명 1건이면 TPS 5).
> - 예약발송은 현재 시점부터 최대 30일까지.
> - 광고성은 `header` 를 못 바꾸므로(`0` 만 가능) 제목/본문에 `(광고)` 를, 본문 끝에 무료수신거부 번호를 직접 쓴다. 둘 다 글자수에 포함된다.
> - 대체발송은 SMS, MMS 만, 메인 채널과 동일 불가.
> - 원문 확인 필요: 통합 RCS 에서 버튼 최대 개수는 이 문서에 없다 (안드로이드 문서는 4개). `expiryOption` 값 의미, `fbInfoLst.ch` 허용값도 원문에 없다.
> - 원문 확인 필요: 예약발송 응답 예시 JSON 에 짝이 맞지 않는 `]` 가 있다.
> - 원문 확인 필요: 프리템플릿 예시는 `{{name}}` 을 쓰는데 `mergeData` 에 `name` 키가 없다.

## 통합 RCS 양방향 발송

`POST /rcs/bi/v1.1`

고객이 보낸 메시지에 대한 응답을 보낸다. 양방향 번호로 등록된 번호만 쓸 수 있다. 수신자 배열이 없고 한 요청에 수신자 1명이다.

### Request Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| agency | Object | | - | 대행사 정보 |
| replyId | String | ● | - | 양방향 응답메시지 ID |
| cliKey | String | ● | 20 | 클라이언트 키 |
| messagebaseId | String | ● | 100 | 메시지베이스 ID |
| chatbotId | String | ● | 40 | 발신번호 / 양방향 대화방 ID |
| telco | String | ● | - | 이통사 (예시: `LGU`) |
| phone | String | ● | - | 휴대폰번호 |
| body | Object | ● | - | 메시지 내용 |
| body.description | String | ● | - | 메시지 본문 |
| body.media | String | | - | 미디어형에서 사용하는 `maapfile://{fileId}` (표에는 없고 예시에만 있음) |
| header | String | ● | 1 | `0` 만 가능 |
| campaignId | String | | 20 | 캠페인 ID |
| deptCode | String | | 20 | 부서 코드 |
| buttons | Array | | - | 버튼 목록 |
| chipList | Array | | - | 칩 목록 |
| brandId | String | | - | 브랜드 ID (대행사는 필수) |
| brandKey | String | | - | 브랜드 KEY (대행사는 필수) |
| productCode | String | | - | 상품 코드 (대행사는 필수) |

### Response (`data[]`)

| 필드 | 타입 | 설명 |
|---|---|---|
| data[].cliKey | String | 클라이언트 키 |
| data[].msgKey | String | 메시지 키 |
| data[].replyId | String | 양방향 응답메시지 ID |
| data[].chatbotId | String | 챗봇 ID |
| data[].code | String | 결과 코드 |
| data[].message | String | 결과 메시지 |

### 예시 (통합 양방향 카드 텍스트형)

```json
{
  "messagebaseId": "RPCSAXX001",
  "chatbotId": "07000000000",
  "header": "0",
  "replyId": "REPLY_ID_EXAMPLE",
  "cliKey": "test001",
  "telco": "LGU",
  "phone": "01000000000",
  "body": { "description": "자동응답 메시지 답변내용" },
  "buttons": [
    { "suggestions": [ { "action": {
      "displayText": "버튼1",
      "postback": { "data": "set_by_chatbot_open_url" },
      "urlAction": { "openUrl": { "url": "https://example.com" } } } } ] }
  ],
  "chipList": [
    { "suggestions": [ { "action": {
      "displayText": "복사하기",
      "clipboardAction": { "copyToClipboard": { "text": "복사할 내용" } },
      "postback": { "data": "set_by_chatbot_copy_to_clipboard" } } } ] }
  ]
}
```

응답 예시:

```json
{
  "code": "10000",
  "message": "성공",
  "data": [
    { "cliKey": "test001", "msgKey": "MSG_KEY_EXAMPLE", "replyId": "REPLY_ID_EXAMPLE",
      "chatbotId": "07000000000", "code": "10000", "message": "성공" }
  ]
}
```

> 주의
> - 양방향 번호로 등록된 번호만 사용 가능.
> - `cliKey` 최대 20자 (단방향의 `recvInfoLst[].cliKey` 는 30자).
> - `footer`, `copyAllowed` 필드가 요청 표에 없다. `fbInfoLst`, 예약발송도 없다.
> - 원문 확인 필요: `replyId` 유효 시간(세션 길이)·재사용 규칙, `telco` 허용값이 문서에 없다.
> - 원문 확인 필요: 양방향 curl 예시 두 개의 제목이 둘 다 '텍스트형' 으로 되어 있으나 두 번째는 `RPCSMTX001`(T형)/`RPCSMMX001`(M형) 이며 `body.media` 가 들어간다.
> - 원문 확인 필요: 칩 구조는 03a 의 [칩 구조](03a-rcs-android.md#칩-구조-chiplist) 와 같은 불일치가 있다 (표는 `chipList[].action`, 예시는 `chipList[].suggestions[].action`).

## 공통 개념

### 메시지베이스 ID

| 구분 | messagebaseId | 비고 |
|---|---|---|
| 단방향 SMS 카드 | `RPSSAXX001` | |
| 단방향 LMS 카드 | `RPLSAXX001` | |
| 단방향 MMS 카드 T형 | `RPMSMTX001` | |
| 단방향 MMS 카드 M형 | `RPMSMMX001` | |
| 이미지 템플릿 M / T | 등록한 템플릿 코드 (`IBR.…` 형태) | 사전 등록 필요 |
| 정보성 템플릿 승인형 | 등록한 템플릿 코드 (`UBR.…` 형태) | 사전 등록 필요 |
| 프리템플릿 | 브랜드별 프리템플릿 코드 (`UBR.…-RPTFXXX001` 형태) | 브랜드마다 다름 |
| 양방향 카드 텍스트형 | `RPCSAXX001` | |
| 양방향 카드 T형 | `RPCSMTX001` | `body.media` 사용 |
| 양방향 카드 M형 | `RPCSMMX001` | `body.media` 사용 |

> 원문 확인 필요: 위 코드 중 `RPMSMTX001`/`RPMSMMX001` 의 'T형/M형' 이 무엇의 약자인지(원문은 MMS 카드 T/M 으로만 표기), 템플릿 등록 절차는 이 문서에 없다.

### 버튼·칩·수신자·대체발송·Agency

구조와 `postback.data` 코드값(`set_by_chatbot_open_url` 등 7종), 동작 객체 필드는 안드로이드 문서와 동일하다. [03a 공통 개념](03a-rcs-android.md#공통-개념) 참고.

### 결과 코드

원문은 결과 코드 목록을 별도 페이지로 링크한다. 이 문서에는 포함되지 않는다 (성공은 `10000`).
