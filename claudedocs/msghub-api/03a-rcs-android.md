# 2.3.1 RCS 메시지 (android)
> 원문: https://doc.msghub.uplus.co.kr/rest-api/02메시지발송/020301rcs_android/ · 확인일 2026-10-16

안드로이드 RCS(브랜드 RCS) 메시지를 보낸다. 단방향 발송(브랜드가 먼저 보냄)과 양방향 응답(고객이 보낸 메시지에 답함) 두 API가 있다. 통합 RCS 는 [03b-rcs-integrated.md](03b-rcs-integrated.md) 참고.

## 한눈에 보기

| 기능 | Method | 경로 | 호스트 |
|---|---|---|---|
| RCS 발송 v1.1 (단방향) | POST | `/rcs/v1.1` | api-send |
| RCS 양방향 발송 v1.1 | POST | `/rcs/bi/v1.1` | api-send |

공통 헤더: `Authorization`(●, 사용자 인증 토큰, 예: `Bearer {token}`), `Content-Type`(●, `application/json`).

## RCS 발송 (단방향)

`POST /rcs/v1.1`

RCS 메시지를 보낸다. 텍스트·이미지·버튼 등 풍부한 형태를 지원하며, 1건에 수신자 최대 10명까지 동보 발송한다.

### Request Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| clickUrlYn | String | | 1 | 단축URL 사용 여부 (Y/N) |
| resvYn | String | | 1 | 예약발송 여부 (Y/N) |
| resvReqDt | String | | - | 예약 발송 시각 (예: `2025-07-13 13:15`) |
| agency | Object | | - | 대행사 정보 ([Agency 객체](#agency-객체)) |
| messagebaseId | String | ● | 100 | 메시지베이스 ID (사전 등록된 ID만 가능, [공통 개념](#메시지베이스-id--상품-유형) 참고) |
| callback | String | ● | 100 | 발신번호 / 양방향 대화방 ID |
| header | String | ● | 1 | `0` 정보성, `1` 광고성 |
| footer | String | | 20 | 무료수신거부 번호 (광고성이면 필수) |
| copyAllowed | Boolean | | - | 복사/공유 허용 여부 |
| expiryOption | String | | 1 | 만료(expire) 옵션 |
| campaignId | String | | 20 | 캠페인 ID |
| deptCode | String | | 20 | 부서 코드 |
| buttons | Array | | - | 버튼 ([버튼 구조](#버튼-구조-buttons)) |
| recvInfoLst | Array | ● | 10개 | 수신자 목록 ([recvInfoLst](#recvinfolst-객체)) |
| fbInfoLst | Array | | - | 대체발송 정보 목록 ([fbInfoLst](#fbinfolst-객체-대체발송)) |
| brandId | String | | - | 브랜드 ID (대행사는 필수) |
| brandKey | String | | - | 브랜드 KEY (대행사는 필수) |
| productCode | String | | - | 상품 코드 (대행사는 필수) |

### Response (`data[]`)

| 필드 | 타입 | 설명 |
|---|---|---|
| data[].cliKey | String | 요청 때 보낸 클라이언트 키 |
| data[].msgKey | String | 메시지 키 |
| data[].phone | String | 수신번호 |
| data[].code | String | 수신자별 결과 코드 |
| data[].message | String | 수신자별 결과 메시지 |

예약발송이면 `data` 가 배열이 아니라 객체로 온다.

| 필드 | 타입 | 설명 |
|---|---|---|
| data.regDt | String | 예약 등록 시각 (예: `2026-04-08T11:16:55`) |
| data.webReqId | String | 예약 요청 ID |

### 예시 (RCS SMS형)

```json
{
  "brandId": "BRAND_ID_EXAMPLE",
  "brandKey": "BRAND_KEY_EXAMPLE",
  "productCode": "SMS",
  "clickUrlYn": "N",
  "resvYn": "N",
  "messagebaseId": "SS000000",
  "callback": "07000000000",
  "header": "0",
  "copyAllowed": false,
  "expiryOption": "1",
  "recvInfoLst": [
    {
      "cliKey": "test001",
      "phone": "01000000000",
      "mergeData": { "name": "이름", "title": "제목", "description": "{{name}}님 안녕하세요." },
      "userCustomFields": { "key1": "value1", "key2": 123 }
    }
  ],
  "buttons": [
    {
      "suggestions": [
        {
          "action": {
            "displayText": "버튼1",
            "postback": { "data": "set_by_chatbot_open_url" },
            "urlAction": { "openUrl": { "url": "https://example.com" } }
          }
        }
      ]
    }
  ]
}
```

응답 예시:

```json
{
  "code": "10000",
  "message": "성공",
  "data": [
    { "cliKey": "test001", "msgKey": "MSG_KEY_EXAMPLE", "phone": "01000000000", "code": "10000", "message": "성공" }
  ]
}
```

### 상품 유형별 mergeData 예시 요약

모든 유형이 같은 요청 골격이고 `productCode`, `messagebaseId`, `recvInfoLst[].mergeData` 키만 다르다. 이미지는 `maapfile://{fileId}` 형식으로 지정한다.

| 유형 | productCode | messagebaseId | mergeData 키 |
|---|---|---|---|
| SMS형 | SMS | SS000000 | name, title, description |
| LMS형 | LMS | SL000000 | name, title, description |
| MMS형 (세로 medium / tall / 이미지강조) | MMS | SMwThM00 / SMwThT00 / OMHIMV0001 | name, title, description, media |
| 이미지&타이틀 강조형 | MMS | OMHITV0001 | name, title, media, subTitle1~3, subDesc1~3 |
| 썸네일형(세로) | ITMPL | OMTBNV0001 | media, title, description, subMedia1~3, subDesc1~3 |
| 썸네일형(가로) | ITMPL | OMTBNH0001 | media, title, description, subMedia1~3 |
| SNS형 | ITMPL | OMSNSS0001 | name, title, description, media |
| 슬라이드형 Small | ITMPL | CMwShS0200 ~ CMwShS0600 | media1~6, title1~6, description1~6 (슬라이드 수에 맞게) |
| 슬라이드형 Medium | ITMPL | CMwMhM0200 ~ CMwMhM0600 | media1~6, title1~6, description1~6 (슬라이드 수에 맞게) |

`mergeData` 안의 `{{변수명}}` 은 같은 객체의 다른 키 값으로 치환된다. 슬라이드형은 `name`, `name2` 처럼 슬라이드별 치환 변수를 둘 수 있다.

> 주의
> - 동보 발송: 1건에 수신자 최대 10명. TPS 는 수신자 수 기준(수신자 5명 1건이면 TPS 5).
> - `messagebaseId` 는 사전에 등록된 ID만 사용할 수 있다.
> - 예약발송은 현재 시점부터 최대 30일까지.
> - 광고성(`header=1`)은 `footer`(무료수신거부 번호) 필수.
> - 버튼은 최대 4개.
> - 단축URL(`clickUrlYn=Y`) 사용 시 메시지 길이가 제한될 수 있다.
> - 대체발송(`fbInfoLst`)은 SMS, MMS 만 지원하고 메인 채널과 같을 수 없다.
> - Web Console 의 'API 전송 Json 코드 보기'로 유형별 JSON 구조를 확인할 수 있다.
> - 원문 확인 필요: `expiryOption` 에 들어갈 수 있는 값과 의미가 원문에 없다 (예시는 `"1"`).
> - 원문 확인 필요: 예약발송 응답 예시 JSON 에 짝이 맞지 않는 `]` 가 있어 위 필드 구성은 원문 표기를 해석한 것이다.
> - 원문 확인 필요: 요청 표에는 `productCode`·`brandId`·`brandKey` 가 선택(대행사만 필수)인데, 모든 curl 예시에는 포함돼 있다.

## RCS 양방향 발송

`POST /rcs/bi/v1.1`

고객이 보낸 메시지에 대한 응답 메시지를 보낸다. 양방향 번호로 등록된 번호만 쓸 수 있다.

단방향과 달리 수신자 배열(`recvInfoLst`)이 없고 한 요청이 수신자 1명(`phone`)이며, 응답 ID(`replyId`)와 이통사(`telco`)를 요구한다.

### Request Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| agency | Object | | - | 대행사 정보 ([Agency 객체](#agency-객체)) |
| replyId | String | ● | - | 양방향 응답메시지 ID (고객 메시지 수신 이벤트로 받은 값) |
| cliKey | String | ● | 20 | 클라이언트 키 |
| messagebaseId | String | ● | 100 | 메시지베이스 ID |
| chatbotId | String | ● | 40 | 발신번호 / 양방향 대화방 ID |
| telco | String | ● | - | 이통사 (예시: `LGU`) |
| phone | String | ● | - | 휴대폰번호 |
| body | Object | ● | - | 메시지 내용 |
| body.description | String | ● | - | 메시지 본문 |
| header | String | ● | 1 | `0` 정보성, `1` 광고성 |
| footer | String | | 20 | 무료수신거부 번호 (광고성이면 필수) |
| copyAllowed | Boolean | | - | 복사/공유 허용 여부 |
| campaignId | String | | 20 | 캠페인 ID |
| deptCode | String | | 20 | 부서 코드 |
| buttons | Array | | - | 버튼 목록 ([버튼 구조](#버튼-구조-buttons)) |
| chipList | Array | | - | 칩 목록 ([칩 구조](#칩-구조-chiplist)) |
| brandId | String | | - | 브랜드 ID (대행사는 필수) |
| brandKey | String | | - | 브랜드 KEY (대행사는 필수) |
| productCode | String | | - | 상품 코드 (대행사는 필수, 예시는 `CHAT`) |

### Response (`data[]`)

| 필드 | 타입 | 설명 |
|---|---|---|
| data[].cliKey | String | 클라이언트 키 |
| data[].msgKey | String | 메시지 키 |
| data[].replyId | String | 양방향 응답메시지 ID |
| data[].chatbotId | String | 챗봇 ID |
| data[].code | String | 결과 코드 |
| data[].message | String | 결과 메시지 |

### 예시

```json
{
  "brandId": "BRAND_ID_EXAMPLE",
  "brandKey": "BRAND_KEY_EXAMPLE",
  "productCode": "CHAT",
  "messagebaseId": "SCL00000",
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

> 주의
> - 양방향 번호로 등록된 번호만 `chatbotId` 로 쓸 수 있다.
> - `cliKey` 는 양방향 발송에서 최대 20자 (단방향 `recvInfoLst[].cliKey` 는 30자).
> - 양방향에는 `fbInfoLst`(대체발송), 예약발송, 동보 필드가 없다.
> - 원문 확인 필요: `replyId` 의 유효 시간(세션 길이)·재사용 가능 횟수·`telco` 허용값·`phone` 길이 제한이 이 문서에 없다.
> - 원문 확인 필요: `chipList` 표는 `action` 이 바로 오는 구조인데, 요청 예시는 `chipList[].suggestions[].action` 으로 감싼 구조이다. 아래 [칩 구조](#칩-구조-chiplist) 참고.

## 공통 개념

### 메시지베이스 ID / 상품 유형

`messagebaseId` 는 메시지 레이아웃(템플릿)을 가리킨다. 사전 등록된 값만 쓸 수 있다. 이 문서의 예시에 나온 값:

| 유형 | messagebaseId | productCode |
|---|---|---|
| SMS형 | `SS000000` | SMS |
| LMS형 | `SL000000` | LMS |
| MMS 세로형(medium) | `SMwThM00` | MMS |
| MMS 세로형(tall) | `SMwThT00` | MMS |
| MMS 이미지강조형 | `OMHIMV0001` | MMS |
| 이미지&타이틀 강조형 | `OMHITV0001` | MMS |
| 썸네일형(세로) | `OMTBNV0001` | ITMPL |
| 썸네일형(가로) | `OMTBNH0001` | ITMPL |
| SNS형 | `OMSNSS0001` | ITMPL |
| 슬라이드형 Small (슬라이드 2~6개) | `CMwShS0200` ~ `CMwShS0600` | ITMPL |
| 슬라이드형 Medium (슬라이드 2~6개) | `CMwMhM0200` ~ `CMwMhM0600` | ITMPL |
| 양방향 | `SCL00000` | CHAT |

> 원문 확인 필요: 양방향에서 쓸 수 있는 다른 messagebaseId(텍스트 외 미디어형 등)는 이 문서에 없다. `productCode` 는 대행사만 필수라 일반 계정의 필요 여부는 원문에 명시되지 않았다.

### 대체발송 (fbInfoLst 객체)

단방향 발송 실패 시 대체로 보낼 메시지. 채널은 SMS, MMS 만 가능하며 메인 채널과 같을 수 없다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| ch | String | ● | 대체 발송 채널 |
| title | String | | 제목 (MMS 면 필수) |
| msg | String | ● | 메시지 |
| fileId | String | | 파일 ID (`fileIdLst` 와 둘 중 하나만 사용) |
| fileIdLst | Array | | 파일 ID 목록 (최대 3개) |

> 원문 확인 필요: `ch` 에 넣는 정확한 값 표기(예: `SMS`/`MMS`)와 RCS 도달 실패의 정확한 정의는 원문에 없다.

### recvInfoLst 객체

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| cliKey | String | ● | 30 | 클라이언트 키 |
| phone | String | ● | 20 | 수신번호 (국제문자 발송 시 맨 앞의 `0` 없이) |
| mergeData | Object | | - | 채널별 개별화(치환) 데이터 |
| userCustomFields | Object | | - | 사용자 정의 필드 |

### Agency 객체

대행사 정보. 세 필드 모두 선택이다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| kisaOrigCode | String | | 재판매사 KISA 최초식별코드 |
| rcsAgencyId | String | | RBC 에 등록된 대행사 ID |
| rcsAgencyKey | String | | RBC 에서 발급된 대행사 키 |

### 버튼 구조 (buttons)

`buttons` 는 `suggestions` 배열을 가진 객체의 배열이다. 한 발송에 버튼 최대 4개.

```
buttons[].suggestions[].action
```

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| suggestions | Array | ● | 버튼 목록 |
| suggestions[].action | Object | ● | 버튼 동작 정보 |
| suggestions[].action.displayText | String | ● | 버튼에 보이는 문구 |
| suggestions[].action.postback | Object | ● | 클릭 시 서버로 돌려줄 데이터 |
| suggestions[].action.postback.data | String | ● | 버튼 종류 코드 (아래 표) |
| suggestions[].action.urlAction | Object | | URL링크 버튼 정보 |
| suggestions[].action.clipboardAction | Object | | 복사하기 버튼 정보 |
| suggestions[].action.dialerAction | Object | | 전화걸기 버튼 정보 |
| suggestions[].action.calendarAction | Object | | 일정추가 버튼 정보 |
| suggestions[].action.mapAction | Object | | 지도 버튼 정보 |

`postback.data` 값과 함께 채워야 하는 동작 객체:

| 버튼 | postback.data | 채울 객체 |
|---|---|---|
| URL링크 | `set_by_chatbot_open_url` | urlAction |
| 복사하기 | `set_by_chatbot_copy_to_clipboard` | clipboardAction |
| 전화걸기 | `set_by_chatbot_dial_phone_number` | dialerAction |
| 일정추가 | `set_by_chatbot_create_calendar_event` | calendarAction |
| 지도맵(현재위치) | `set_by_chatbot_request_location_push` | mapAction.requestLocationPush |
| 지도맵(좌표입력) | `set_by_chatbot_show_location` | mapAction.showLocation (latitude/longitude/label) |
| 지도맵(쿼리입력) | `set_by_chatbot_search_locations` | mapAction.showLocation (query) |

동작 객체 필드:

| 객체 | 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|---|
| urlAction | openUrl | Object | ● | 오픈 URL 정보 |
| | openUrl.url | String | ● | 이동할 URL |
| clipboardAction | copyToClipboard | Object | ● | 클립보드 복사 정보 |
| | copyToClipboard.text | String | ● | 복사할 텍스트 |
| dialerAction | dialPhoneNumber | Object | ● | 전화 걸기 정보 |
| | dialPhoneNumber.phoneNumber | String | ● | 전화번호 |
| calendarAction | createCalendarEvent | Object | ● | 일정 정보 |
| | createCalendarEvent.title | String | ● | 일정 제목 |
| | createCalendarEvent.description | String | ● | 일정 설명 |
| | createCalendarEvent.startTime | String | ● | 시작 (예: `2025-07-09T00:00:00Z`) |
| | createCalendarEvent.endTime | String | ● | 종료 (예: `2025-07-09T12:00:00Z`) |
| mapAction | requestLocationPush | Object | | 현재위치 버튼이면 필수 (내용 없음, `{}`) |
| | showLocation | Object | | 좌표 또는 쿼리 지도 버튼이면 필수 |
| | showLocation.fallbackUrl | String | ● | 지도 앱 실행 실패 시 대체 URL |
| | showLocation.location | Object | ● | 위치 정보 |
| | showLocation.location.latitude | String | | 위도 (좌표 기반이면 필수) |
| | showLocation.location.longitude | String | | 경도 (좌표 기반이면 필수) |
| | showLocation.location.label | String | | 지도 앱에 표시할 라벨 (좌표 기반이면 필수) |
| | showLocation.location.query | String | | 검색어 (검색 기반이면 필수) |

버튼 JSON 예시 (유형별로 `action` 안만 다르다):

```json
{ "action": { "displayText": "전화", "postback": { "data": "set_by_chatbot_dial_phone_number" },
  "dialerAction": { "dialPhoneNumber": { "phoneNumber": "01000000000" } } } }
```

```json
{ "action": { "displayText": "일정", "postback": { "data": "set_by_chatbot_create_calendar_event" },
  "calendarAction": { "createCalendarEvent": { "title": "일정 제목", "description": "일정 내용",
    "startTime": "2025-07-09T00:00:00Z", "endTime": "2025-07-10T23:59:59Z" } } } }
```

```json
{ "action": { "displayText": "지도(좌표)", "postback": { "data": "set_by_chatbot_show_location" },
  "mapAction": { "showLocation": { "fallbackUrl": "https://example.com/map",
    "location": { "latitude": "37.0", "longitude": "127.0", "label": "라벨" } } } } }
```

```json
{ "action": { "displayText": "지도(검색)", "postback": { "data": "set_by_chatbot_search_locations" },
  "mapAction": { "showLocation": { "fallbackUrl": "https://example.com/map",
    "location": { "query": "검색할 구문" } } } } }
```

```json
{ "action": { "displayText": "현재위치 공유", "postback": { "data": "set_by_chatbot_request_location_push" },
  "mapAction": { "requestLocationPush": {} } } }
```

(URL링크·복사하기 예시는 위 요청 예시 참고.)

### 칩 구조 (chipList)

칩은 양방향 응답에서만 쓰는 제안 칩이다. 동작 객체(urlAction, clipboardAction, dialerAction, calendarAction, mapAction)와 `postback.data` 값은 버튼과 동일하다. 버튼과 다른 점은 `suggestions` 래퍼 유무에 대한 표기다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| action | Object | ● | 칩 동작 정보 |
| action.displayText | String | ● | 칩에 표시되는 문구 |
| action.postback | Object | ● | 클릭 시 서버로 전송할 데이터 |
| action.urlAction / clipboardAction / dialerAction / calendarAction / mapAction | Object | | 버튼과 같은 동작 정보 |

> 원문 확인 필요: 원문 필드 표는 `chipList[].action`(표에는 `action[].displayText` 로 표기) 구조인데, 양방향 curl 예시는 `chipList[].suggestions[].action` 구조로 쓰였다. 실제 수용 구조를 검수 환경에서 확인할 것. 또한 원문의 칩 '일정추가/지도' JSON 예시는 키 이름이 `chipList` 가 아닌 `buttons` 로 적혀 있다 (오기로 보임).

### 결과 코드

원문은 결과 코드 목록을 별도 페이지로 링크한다. 이 문서에는 포함되지 않는다 (성공은 `10000`).
