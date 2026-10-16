# 4.2 카카오 통계
> 원문: https://doc.msghub.uplus.co.kr/rest-api/04통계/0402kakao_statistics/ · 확인일 2026-10-16

## 한눈에 보기

카카오 채널(알림톡·브랜드메시지)의 읽음·클릭 통계 7종. 모두 GET 이고 호스트는 mnt-api.

| 기능 | Method | 경로 | 호스트 |
|---|---|---|---|
| 채널 알림톡 읽음 통계 | GET | `/kko/v2/stat/kkoChId/alimtalkRead` | mnt-api |
| 채널 브랜드메시지 읽음 통계 | GET | `/kko/v2/stat/kkoChId/brandtalkRead` | mnt-api |
| 채널 브랜드메시지 클릭 통계 | GET | `/kko/v2/stat/kkoChId/brandtalkClick` | mnt-api |
| 템플릿별 알림톡 읽음 통계 | GET | `/kko/v2/stat/template/alimtalkRead` | mnt-api |
| 템플릿별 브랜드메시지 읽음 통계 | GET | `/kko/v2/stat/template/brandtalkRead` | mnt-api |
| 템플릿별 알림톡 클릭(버튼) 통계 | GET | `/kko/v2/stat/template/alimtalkClick` | mnt-api |
| 템플릿별 브랜드메시지 클릭 통계 | GET | `/kko/v2/stat/template/brandtalkClick` | mnt-api |

## 공통 개념

### 공통 요청

7개 API 모두 Header 와 Query 가 같다.

| 구분 | 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|---|
| Header | Authorization | String | ● | - | 사용자 인증 토큰 (`Bearer {token}`) |
| Header | Content-Type | String | ● | - | `application/json` |
| Query | kkoChId | String | ● | 61 | 카카오채널 ID (예: `@채널명`) |
| Query | date | String | ● | 8 | 조회일(발송일) `yyyyMMdd` |
| Query | elapsedDay | String | ● | 1 | 조회일 기준 경과일수, 0~2 |

### 공통 코드값

| 필드 | 값 |
|---|---|
| messageType | `AT` 알림톡, `AI` 이미지 알림톡 |
| receiveUserType | `PhoneNumber` 전화번호, `AppUserId` 앱유저아이디, `UserKey` 유저키, `None` 잘못된 수신자 정보 |
| messageSpec | `BASIC` 템플릿형, `FREESTYLE` 자유형 |
| chatBubbleType | `TEXT`, `IMAGE`, `WIDE`, `WIDE_ITEM_LIST`, `CAROUSEL_FEED`, `PREMIUM_VIDEO`, `COMMERCE`, `CAROUSEL_COMMERCE` |
| friendType | `N` 비친구, `F` 친구 |
| targeting | 발송 타게팅 (원문에 값 목록 없음, 예시에는 `I`, `M` 등장) |

> 원문 확인 필요: `targeting` 의 가능한 값과 의미는 원문에 정의되어 있지 않다.

## 채널 알림톡 읽음 통계

`GET /kko/v2/stat/kkoChId/alimtalkRead`

메시지 타입·수신자 유형별 유효 읽음 수.

응답 data[]

| 필드 | 타입 | 설명 |
|---|---|---|
| date | String | 조회일(발송일) yyyyMMdd |
| kkoChId | String | 카카오채널 ID |
| messageType | String | `AT` / `AI` |
| receiveUserType | String | 수신자 유형 |
| readCount | Integer | 유효 읽음 수 |

```json
{ "code": "10000", "message": "성공",
  "data": [ { "date": "20250710", "kkoChId": "@channel_example", "messageType": "AT",
              "receiveUserType": "PhoneNumber", "readCount": 120 } ] }
```

## 채널 브랜드메시지 읽음 통계

`GET /kko/v2/stat/kkoChId/brandtalkRead`

발송 타입·메시지 타입·타게팅·친구 유형별 유효 읽음 수.

응답 data[]

| 필드 | 타입 | 설명 |
|---|---|---|
| date | String | 조회일(발송일) yyyyMMdd |
| kkoChId | String | 카카오채널 ID |
| messageSpec | String | 발송 타입 |
| chatBubbleType | String | 메시지 타입 |
| receiveUserType | String | 수신자 유형 |
| targeting | String | 발송 타게팅 |
| friendType | String | 친구 타입 |
| readCount | Integer | 유효 읽음 수 |

```json
{ "code": "10000", "message": "성공",
  "data": [ { "date": "20250710", "kkoChId": "@channel_example", "messageSpec": "BASIC",
              "chatBubbleType": "TEXT", "receiveUserType": "PhoneNumber",
              "targeting": "I", "friendType": "F", "readCount": 80 } ] }
```

## 채널 브랜드메시지 클릭 통계

`GET /kko/v2/stat/kkoChId/brandtalkClick`

버튼·리스트·썸네일·기타 클릭 수.

응답 data[]

| 필드 | 타입 | 설명 |
|---|---|---|
| date | String | 조회일(발송일) yyyyMMdd |
| kkoChId | String | 카카오채널 ID |
| messageSpec | String | 발송 타입 |
| chatBubbleType | String | 메시지 타입 |
| receiveUserType | String | 수신자 유형 |
| targeting | String | 발송 타게팅 |
| friendType | String | 친구 타입 |
| buttonClickCount | Integer | 버튼 클릭 수 |
| listClickCount | Integer | 리스트 클릭 수 |
| thumbnailClickCount | Integer | 썸네일 클릭 수 |
| etcClickCount | Integer | 이외 항목 클릭 수 |

```json
{ "code": "10000", "message": "성공",
  "data": [ { "date": "20250710", "kkoChId": "@channel_example", "messageSpec": "BASIC",
              "chatBubbleType": "WIDE", "receiveUserType": "PhoneNumber", "targeting": "I",
              "friendType": "F", "buttonClickCount": 40, "listClickCount": 5,
              "thumbnailClickCount": 12, "etcClickCount": 2 } ] }
```

## 템플릿별 알림톡 읽음 통계

`GET /kko/v2/stat/template/alimtalkRead`

템플릿 코드·메시지 타입별 유효 읽음 수.

응답 data[]

| 필드 | 타입 | 설명 |
|---|---|---|
| date | String | 조회일(발송일) yyyyMMdd |
| kkoChId | String | 카카오채널 ID |
| messageType | String | `AT` / `AI` |
| templateCode | String | 템플릿 코드 |
| readCount | Integer | 유효 읽음 수 |

```json
{ "code": "10000", "message": "성공",
  "data": [ { "date": "20250710", "kkoChId": "@channel_example", "messageType": "AT",
              "templateCode": "TMPL_ORDER_001", "readCount": 95 } ] }
```

## 템플릿별 브랜드메시지 읽음 통계

`GET /kko/v2/stat/template/brandtalkRead`

템플릿 코드·그룹태그·발송 타입별 유효 읽음 수.

응답 data[]

| 필드 | 타입 | 설명 |
|---|---|---|
| date | String | 조회일(발송일) yyyyMMdd |
| kkoChId | String | 카카오채널 ID |
| templateCode | String | 템플릿 코드 |
| groupTagKey | String | 그룹 태그 키 |
| messageSpec | String | 발송 타입 |
| chatBubbleType | String | 메시지 타입 |
| targeting | String | 발송 타게팅 |
| friendType | String | 친구 타입 |
| readCount | Integer | 유효 읽음 수 |

```json
{ "code": "10000", "message": "성공",
  "data": [ { "date": "20250710", "kkoChId": "@channel_example", "templateCode": "BM_TMPL_001",
              "groupTagKey": "GRP_TAG_01", "messageSpec": "BASIC", "chatBubbleType": "TEXT",
              "targeting": "I", "friendType": "F", "readCount": 60 } ] }
```

## 템플릿별 알림톡 클릭(버튼) 통계

`GET /kko/v2/stat/template/alimtalkClick`

버튼 순서·유형·바로연결 유형별 클릭 상세. (원문 목차는 "버튼 통계", 본문 제목은 "클릭 통계")

응답 data[]

| 필드 | 타입 | 설명 |
|---|---|---|
| date | String | 조회일(발송일) yyyyMMdd |
| kkoChId | String | 카카오채널 ID |
| templateCode | String | 템플릿 코드 |
| messageType | String | `AT` / `AI` |
| clickInfo.buttonOrders | Array | 버튼 순서별 클릭 수 |
| clickInfo.buttonType | Json | 버튼 유형별 클릭 수 (예: WL, AL, DS, MD) |
| clickInfo.qrType | Json | 바로연결 유형별 클릭 수 (예: WL, AL, DS, MD) |
| clickInfo.etc | Integer | 순서/타입 집계에 들어가지 않는 링크 클릭 요소 합계 |

```json
{ "code": "10000", "message": "성공",
  "data": [ { "date": "20250710", "kkoChId": "@channel_example", "templateCode": "TMPL_ORDER_001",
              "messageType": "AT",
              "clickInfo": { "buttonOrders": [10, 5, 2],
                             "buttonType": { "WL": 8, "AL": 6, "DS": 3 },
                             "qrType": { "WL": 4, "MD": 1 }, "etc": 2 } } ] }
```

> 원문 확인 필요: `buttonType`/`qrType` 의 WL·AL·DS·MD 약어 의미는 원문에 없다(카카오 버튼 유형 약어로 보이나 미확인).

## 템플릿별 브랜드메시지 클릭 통계

`GET /kko/v2/stat/template/brandtalkClick`

버튼·이미지·리스트 순서별 클릭 상세.

응답 data[]

| 필드 | 타입 | 설명 |
|---|---|---|
| date | String | 조회일(발송일) yyyyMMdd |
| kkoChId | String | 카카오채널 ID |
| templateCode | String | 템플릿 코드 |
| groupTagKey | String | 그룹 태그 키 |
| messageSpec | String | 발송 타입 |
| chatBubbleType | String | 메시지 타입 |
| targeting | String | 발송 타게팅 |
| friendType | String | 친구 타입 |
| clickInfo.buttonOrders | Array | 버튼 순서별 클릭 수 |
| clickInfo.imageOrders | Array | 이미지 순서별 클릭 수 |
| clickInfo.listOrders | Array | 리스트 순서별 클릭 수 |
| clickInfo.etc | Integer | 그 외 항목 클릭 수 |

```json
{ "code": "10000", "message": "성공",
  "data": [ { "date": "20250710", "kkoChId": "@channel_example", "templateCode": "BM_TMPL_001",
              "groupTagKey": "GRP_TAG_01", "messageSpec": "BASIC", "chatBubbleType": "WIDE_ITEM_LIST",
              "targeting": "I", "friendType": "F",
              "clickInfo": { "buttonOrders": [15, 7], "imageOrders": [9, 3],
                             "listOrders": [4, 2, 1], "etc": 1 } } ] }
```

> 주의
> - 원문 확인 필요: 읽음·클릭 수는 "유효" 집계라고만 되어 있고, `elapsedDay`(0~2) 가 발송일 이후 며칠 뒤까지의 누적을 뜻하는지 단일 일자인지는 설명이 없다.
> - 원문 확인 필요: 7개 모두 `GET` 이면서 Header 에 `Content-Type: application/json` 을 필수로 표기한다(본문 없음).
