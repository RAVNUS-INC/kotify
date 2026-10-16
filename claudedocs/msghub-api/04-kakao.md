# 2.4 카카오톡 메시지
> 원문: https://doc.msghub.uplus.co.kr/rest-api/02메시지발송/0204kko_v12/ · 확인일 2026-10-16

이 페이지는 알림톡 V1.2, 브랜드메시지 템플릿형 V1, 브랜드메시지 자유형 V1 세 가지를 다룬다. (페이지 제목은 "카카오톡 메시지"이며 친구톡 전용 API는 이 페이지에 없다.) 세 API 모두 동보발송(한 건에 최대 10명)을 지원하고 같은 공통 객체(`recvInfoLst`, `fbInfoLst`, `agency`)를 쓴다.

## 한눈에 보기

| 기능 | Method | 경로 | 호스트 |
|---|---|---|---|
| 알림톡 발송 V1.2 | POST | `/kko/alimtalk/v1.2` | api-send |
| 브랜드메시지 템플릿형 발송 V1 | POST | `/kko/brandtalk/tmplt/v1` | api-send |
| 브랜드메시지 자유형 발송 V1 | POST | `/kko/brandtalk/custom/v1` | api-send |

## 공통 개념

- **동보발송**: 같은 내용을 여러 수신자에게 한 번에 보내는 방식. 1건 요청에 수신자(`recvInfoLst`) 최대 10명. TPS는 수신자 수 기준(수신자 5명 = TPS 5).
- **예약발송**: `resvYn=Y` + `resvReqDt`. 현재 시점부터 최대 30일까지.
- **대체발송(`fbInfoLst`)**: 카카오 발송 실패 시 보내는 대체 메시지. 채널은 SMS, MMS만 가능하고 메인 채널(카카오)과 같을 수 없다.
- **응답 형태 두 가지**: 즉시발송은 `data` 가 수신자별 배열, 예약발송은 `data` 가 `{regDt, webReqId}` 객체(아래 각 API 예시 참고).
- 발신번호(`callback`)는 사전 등록된 번호만 사용 가능. 템플릿 코드는 사전에 승인(등록)된 것만 사용 가능.

### agency 객체

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| kisaOrigCode | String | - | 재판매사 KISA 최초식별코드 |
| rcsAgencyId | String | - | RBC에 등록된 대행사 ID |
| rcsAgencyKey | String | - | RBC에서 발급된 대행사 키 |

### recvInfoLst[] 객체

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| cliKey | String | ● | 30자 | 클라이언트 키 |
| phone | String | ● | 20자 | 수신번호 (국제문자는 맨 앞 `0` 없이) |
| mergeData | Object | - | - | 채널별 개별화 메시지용 머지 데이터 |
| userCustomFields | Object | - | - | 사용자 정의 필드 |

### fbInfoLst[] 객체

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| ch | String | ● | 대체발송 채널 (SMS 또는 MMS) |
| title | String | - | 제목 (MMS는 필수) |
| msg | String | ● | 메시지 |
| fileId | String | - | 파일 ID (`fileIdLst` 와 둘 중 하나만) |
| fileIdLst | Array | - | 파일 ID 목록, 최대 3개 |

### 공통 응답

`data[]` (즉시발송) 필드:

| 필드 | 타입 | 설명 |
|---|---|---|
| data[].cliKey | String | 클라이언트 키 |
| data[].msgKey | String | 메시지 키 |
| data[].phone | String | 수신번호 |
| data[].code | String | 수신자별 결과 코드 |
| data[].message | String | 수신자별 결과 메시지 |

결과 코드 값은 [09-result-codes.md](09-result-codes.md) 참고.

---

## 알림톡 발송 V1.2

`POST /kko/alimtalk/v1.2`

카카오 알림톡(승인된 템플릿 기반 정보성 메시지)을 발송한다.

### 요청

Header

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| Authorization | String | ● | 사용자 인증 토큰 |
| Content-Type | String | ● | `application/json` |

Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| clickUrlYn | String | - | 1자 | 단축URL 사용 여부 (Y/N) |
| resvYn | String | - | 1자 | 예약발송 여부 (Y/N) |
| resvReqDt | String | - | - | 예약발송 시간 (예: `2025-07-13 13:15`) |
| agency | Object | - | - | 대행사 정보 |
| callback | String | ● | 20자 | 발신번호 |
| campaignId | String | - | 20자 | 캠페인 ID |
| deptCode | String | - | 20자 | 부서 코드 |
| title | String | - | - | 강조표기 메시지 |
| itemHeader | String | - | - | 헤더 |
| itemHighlightTitle | String | - | - | 요약정보 |
| itemHighlightDescription | String | - | - | 요약내용 |
| msg | String | ● | 1,000자 | 메시지 내용 |
| item | Object | - | - | 아이템리스트 정보 |
| kkoChId | String | ● | 61자 | 카카오채널 ID |
| tmpltCode | String | ● | - | 템플릿 코드 |
| service | Integer | - | - | 서비스 번호 |
| recvInfoLst | Array | ● | 10개 | 수신자 정보 목록 |
| fbInfoLst | Array | - | - | 대체발송 정보 |
| buttons | Array | - | - | 버튼 리스트 (최대 5개) |
| groupKey | String | - | 200자 | 알림톡 그룹키 |

`item` 객체 (아이템리스트형 템플릿)

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| item.list | Array | ● | - | 아이템리스트. 최소 2개, 최대 10개 |
| item.list[].title | String | ● | 6자 | 아이템 타이틀 |
| item.list[].description | String | ● | 23자 | 아이템 설명 |
| item.summary | Object | - | - | 아이템리스트 요약 |
| item.summary.title | String | ● | 6자 | 요약 타이틀 |
| item.summary.description | String | - | 14자 | 요약 설명 (변수·화폐 단위·숫자·쉼표·마침표만 가능) |

`buttons[]` 객체

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| name | String | ● | 14자 | 버튼 이름 |
| type | String | ● | 2자 | 버튼 타입 (아래 표) |
| linkMo | String | - | - | 모바일에서 클릭 시 이동할 URL |
| linkPc | String | - | - | PC에서 클릭 시 이동할 URL |
| linkAnd | String | - | - | 안드로이드에서 실행할 앱 커스텀 스킴 |
| linkIos | String | - | - | iOS에서 실행할 앱 커스텀 스킴 |
| ordering | Integer | - | - | 버튼 노출 순서 |
| varUrlYn | String | - | - | URL 가변 값 포함 여부 |
| kkoBtnOutbrowserYn | boolean | - | - | WL 타입에서 URL을 외부 브라우저로 열지 여부 (true/false) |
| chat_extra | String | - | 64자 | 봇 관련 정보 (type BC, BT) |
| chat_event | String | - | 64자 | 봇 관련 이벤트 정보 (type BT) |

버튼 타입(`type`)

| 타입 | 의미 | 필수 입력 / 제약 |
|---|---|---|
| WL | 웹링크 | `url_mobile` 필수, `url_pc` 선택 |
| AL | 앱링크 | `linkIos`, `linkAnd`, `linkMo` 중 2개 이상 필수 |
| BK | 봇 키워드 | 해당 버튼 텍스트 전송 |
| MD | 메시지 전달 | 버튼 텍스트 + 메시지 본문 전송 |
| BC | 상담톡 전환 | 상담톡 서비스 이용 중이면 상담톡으로 전환 |
| BT | 봇 전환 | 채널 봇으로 전환 |
| DS | 배송조회 | 메시지 내 송장번호로 배송조회 페이지 연결 (quickReplies 사용 불가) |
| AC | 채널추가 | 광고추가형/복합형 템플릿에서만, 버튼 단독 또는 첫 번째 버튼에만 추가 가능 (quickReplies 사용 불가) |

> 원문 확인 필요: 버튼 필드 이름이 원문 안에서 갈린다. 타입 설명과 요청 예시는 WL 버튼에 `url_mobile`/`url_pc` 를 쓰는데 `buttons` 필드 표에는 `linkMo`/`linkPc` 만 있다. 또 예시의 `kkoBtnOutbrowserYn` 값이 `true 또는 "true"` 로 적혀 있어 불리언/문자열 모두 허용되는 것으로 보이나 명시는 없다.

### 응답

공통 응답 구조(위 "공통 응답") 그대로다. 즉시발송이면 `data[]` 배열.

### 예시

일반(아이템리스트형 이외) 템플릿 요청:

```json
{
  "callback": "0212341234",
  "title": "U+ Cloud 서비스 알림",
  "msg": "안녕하세요. #{name} 고객님.\n\nU+ Cloud서비스에서 설정하신 일일 사용량(1,000건) 초과 사용을 알려드립니다.",
  "kkoChId": "@myservice",
  "tmpltCode": "TPnJhpG82k",
  "recvInfoLst": [
    { "cliKey": "test001", "phone": "01012341234", "mergeData": { "name": "홍길동" } }
  ],
  "buttons": [
    { "name": "사용량 제한 이용안내", "type": "WL",
      "url_mobile": "https://m.uplus.co.kr/cloud/usage",
      "url_pc": "https://www.uplus.co.kr/cloud/usage",
      "kkoBtnOutbrowserYn": true },
    { "name": "포인트 전환하기", "type": "AL",
      "linkMo": "https://m.uplus.co.kr/point",
      "linkAnd": "upluscloud://point/convert",
      "linkIos": "upluscloud://point/convert" }
  ],
  "fbInfoLst": [
    { "ch": "MMS", "title": "제목", "msg": "MMS 메시지 내용", "fileId": "testFileId001" }
  ]
}
```

아이템리스트형 템플릿은 위 본문에 아래 필드를 더한다.

```json
{
  "item": {
    "list": [
      { "title": "test01", "description": "test01" },
      { "title": "test02", "description": "test02" }
    ],
    "summary": { "title": "테스트", "description": "1,000,000원" }
  },
  "itemHeader": "헤더",
  "itemHighlightTitle": "타이틀",
  "itemHighlightDescription": "설명"
}
```

즉시발송 응답:

```json
{
  "code": "10000",
  "message": "성공",
  "data": [
    { "cliKey": "test001", "msgKey": "3jVnyk0m8U.6fKG1w", "phone": "01012341234", "code": "10000", "message": "성공" }
  ]
}
```

예약발송 응답:

```json
{
  "code": "10000",
  "message": "성공",
  "data": { "regDt": "2026-04-08T11:16:55", "webReqId": "RRR...b5jv" }
}
```

> 주의
> - 단축URL 사용 시 메시지 길이가 제한될 수 있다.
> - 버튼은 최대 5개.
> - 예약발송 응답은 건별 `msgKey` 대신 `regDt`, `webReqId` 를 돌려준다.
> - 원문 확인 필요: 예약발송 응답 예시에 JSON 괄호가 어긋나 있다(객체 뒤에 `]`). 위 예시는 객체 형태로 바로잡은 것이다.
> - 원문 확인 필요: `item.summary` 객체의 설명이 "아이템리스트 설명"으로 되어 있어 요약 객체임을 문맥으로 추정했다.

---

## 브랜드메시지 템플릿형 발송 V1

`POST /kko/brandtalk/tmplt/v1`

승인·등록된 브랜드메시지 템플릿으로 발송한다. 한 번에 최대 10건. 본문 내용은 템플릿이 정하므로 요청에는 템플릿 코드·말풍선 유형·수신자만 보낸다.

### 요청

Header

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| Authorization | String | ● | 사용자 인증 토큰 |

Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| targeting | String | ● | 1자 | 마수동 타입. `M`(I+N: I 타입 실패 시 N 타입으로 발송), `N`(일반), `I`(정보) |
| resvYn | String | - | 1자 | 예약발송 여부 (Y/N) |
| resvReqDt | String | - | - | 예약발송 시간 (예: `2025-07-13 13:15`) |
| agency | Object | - | - | 대행사 정보 |
| pushAlarm | String | - | 1자 | 푸시 알람 (Y/N), 기본 Y |
| kkoChId | String | ● | 61자 | 카카오채널 ID |
| tmpltCode | String | ● | - | 템플릿 코드 |
| chatBubbleType | String | ● | - | 메시지 타입 (아래 enum) |
| callback | String | ● | 20자 | 발신번호 |
| recvInfoLst | RecvInfo[] | ● | 10개 | 수신자 정보 목록 |
| fbInfoLst | FbInfo[] | - | - | 대체발송 정보 |
| unsubscribePhoneNumber | String | - | 13자 | 무료수신거부 전화번호 (`080-000-0000` 형식, 하이픈 포함) |
| unsubscribeAuthNumber | String | - | 10자 | 무료수신거부 인증번호 (080 번호의 내선 개념, `unsubscribePhoneNumber` 없이 사용 불가) |

`chatBubbleType` 값: `TEXT`, `IMAGE`, `WIDE`, `WIDE_ITEM_LIST`, `CAROUSEL_FEED`, `CAROUSEL_COMMERCE`, `COMMERCE`, `PREMIUM_VIDEO`

### 응답

공통 응답. 즉시발송은 `data[]` 배열, 예약발송은 `{regDt, webReqId}`.

### 예시

텍스트형 요청:

```json
{
  "targeting": "I",
  "tmpltCode": "TEST_TXT",
  "kkoChId": "@메시지허브",
  "chatBubbleType": "TEXT",
  "callback": "020010001",
  "fbInfoLst": [ { "ch": "MMS", "title": "제목", "msg": "MMS 메시지 내용" } ],
  "recvInfoLst": [ { "cliKey": "text_test", "phone": "01000010001" } ],
  "unsubscribePhoneNumber": "080-1234-1234",
  "unsubscribeAuthNumber": "1234"
}
```

와이드형·캐러셀피드형도 `tmpltCode`, `chatBubbleType` 값만 바뀐다(`TEST_WIDE`/`WIDE`, `TEST_CAROUSEL_FEED`/`CAROUSEL_FEED`).

예약발송 응답:

```json
{ "code": "10000", "message": "성공", "data": { "regDt": "2025-10-22T17:43:32", "webReqId": "BJ....pT" } }
```

> 주의
> - `unsubscribePhoneNumber`, `unsubscribeAuthNumber` 둘 다 생략하면 카카오채널에 등록된 무료수신거부 정보로 발송된다.
> - **캐러셀커머스형 변수**: `commerce` 객체 안에서 변수를 쓰면 `mergeData` 의 key 를 `변수명_캐러셀번호` 로 넣어야 한다. 변수를 쓰지 않는 캐러셀은 생략한다.
>   예) 1번째 캐러셀 `#{정상가격}`, `#{할인가격}`, `#{할인율}` / 2번째 `#{정상가격}`, `#{할인가격}`, `#{정액할인가격}` 이면

```json
{
  "recvInfoLst": [
    { "cliKey": "text_test", "phone": "01000010001",
      "mergeData": {
        "정상가격_1": "10000", "할인가격_1": "8000", "할인율_1": "20",
        "정상가격_2": "15000", "할인가격_2": "10000", "정액할인가격_2": "5000"
      } }
  ]
}
```

> 1번째 캐러셀에 변수가 없으면 `정상가격_2`, `할인가격_2`, `정액할인가격_2` 만 넣는다.

---

## 브랜드메시지 자유형 발송 V1

`POST /kko/brandtalk/custom/v1`

템플릿 없이 요청 본문에서 말풍선 내용을 직접 지정해 발송한다. 한 번에 최대 10건.

### 요청

Header

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| Authorization | String | ● | 사용자 인증 토큰 |

Body 공통

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| targeting | String | ● | 1자 | 마수동 타입. `M`(I+N: I 실패 시 N), `N`(일반), `I`(정보) |
| agency | Object | - | - | 대행사 정보 |
| resvYn | String | - | 1자 | 예약발송 여부 (Y/N) |
| resvReqDt | String | - | - | 예약발송 시간 (예: `2025-07-13 13:15`) |
| campaignId | String | - | 20자 | 캠페인 ID |
| deptCode | String | - | 20자 | 부서 코드 |
| callback | String | ● | 20자 | 발신번호 |
| recvInfoLst | RecvInfo[] | ● | 10개 | 수신자 정보 목록 |
| fbInfoLst | FbInfo[] | - | - | 대체발송 정보 |
| pushAlarm | String | - | 1자 | 푸시 알람 (Y/N), 기본 Y |
| unsubscribePhoneNumber | String | - | 13자 | 무료수신거부 전화번호 (`080-000-0000`) |
| unsubscribeAuthNumber | String | - | 10자 | 무료수신거부 인증번호 (`unsubscribePhoneNumber` 필요) |
| kkoChId | String | ● | 61자 | 카카오채널 ID |
| chatBubbleType | String | ● | - | `TEXT`, `IMAGE`, `WIDE`, `WIDE_ITEM_LIST`, `CAROUSEL_FEED`, `CAROUSEL_COMMERCE`, `COMMERCE`, `PREMIUM_VIDEO` |
| adult | boolean | - | 최대 5자 | 성인용 템플릿 여부 |
| content | String | - | - | 본문. TEXT·IMAGE: 최대 1,300자 (줄바꿈 최대 99개, URL 형식 입력 가능). WIDE·PREMIUM_VIDEO: 최대 76자 (줄바꿈 최대 5개) |
| buttons | Button[] | - | - | 버튼 (유형별 최대 개수는 아래 주의) |
| coupon | Coupon | - | - | 쿠폰 |

CAROUSEL_COMMERCE, CAROUSEL_FEED 는 최상위 `buttons`, `coupon` 을 쓸 수 없다(캐러셀 항목 안에서 지정).

유형별 추가 필드

IMAGE, WIDE

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| imageUrl | String | ● | 최대 500자 | 파일 업로드 API로 등록한 이미지 URL |
| imageLink | String | - | 최대 500자 | 이미지 클릭 시 이동할 URL |

WIDE_ITEM_LIST

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| header | String | ● | 최대 20자 | 템플릿 헤더 |
| wideItemList | WideItem[] | ● | 3개 필수 | 와이드 리스트 |

PREMIUM_VIDEO

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| header | String | - | 최대 20자 | 템플릿 헤더 |
| video | Object | ● | - | 동영상 객체 |
| video.videoUrl | String | ● | - | 카카오TV 동영상 URL |
| video.thumbnailUrl | String | - | - | 이미지 업로드 API로 등록한 썸네일 URL |

COMMERCE

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| additionalContent | String | - | 최대 34자 | 부가정보 (줄바꿈 최대 1개) |
| imageUrl | String | ● | 최대 500자 | 파일 업로드 API로 등록한 이미지 URL |
| commerce | Object | ● | - | 커머스 정보 |
| commerce.title | String | ● | 30자 | 상품 제목 |
| commerce.regularPrice | Number | ● | - | 정상가격 (0 ~ 99,999,999) |
| commerce.discountPrice | Number | ● | - | 할인 후 가격 (0 ~ 99,999,999) |
| commerce.discountRate | Number | - | - | 할인율 (1 ~ 100). `discountFixed` 와 둘 중 하나만 |
| commerce.discountFixed | Number | - | - | 정액 할인 가격 (0 ~ 999,999). `discountRate` 와 둘 중 하나만 |

CAROUSEL_COMMERCE

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| carousel | Object | ● | - | 캐러셀 객체 |
| carousel.head | Object | - | - | 캐러셀 인트로. CAROUSEL_COMMERCE 에서만 선택 사용 |
| carousel.head.header | String | ● | - | 인트로 헤더 (head 사용 시 필수) |
| carousel.head.content | String | ● | - | 인트로 내용 |
| carousel.head.imageUrl | String | ● | - | 파일 업로드 API로 등록한 인트로 이미지 URL |
| carousel.head.linkMobile | String | - | - | 모바일 이동 URL. 링크를 하나라도 입력하면 `linkMobile` 필수 |
| carousel.head.linkPc | String | - | - | PC 이동 URL |
| carousel.head.linkAnd | String | - | - | 안드로이드 앱 커스텀 스킴 |
| carousel.head.linkIos | String | - | - | iOS 앱 커스텀 스킴 |
| carousel.list | json[] | ● | - | 캐러셀 리스트 |
| carousel.list.additionalContent | String | - | 최대 34자 | 부가정보 |
| carousel.list.imageUrl | String | ● | - | 파일 업로드 API로 등록한 이미지 URL |
| carousel.list.imageLink | String | - | - | 이미지 클릭 시 이동 URL |
| carousel.list.commerce | Commerce | ● | - | 커머스 요소 |
| carousel.list.buttons | Button[] | ● | - | 버튼 목록 (캐러셀당 최소 1개, 최대 2개) |
| carousel.list.coupon | Coupon | - | - | 쿠폰 요소 |
| carousel.tail | json | - | - | 더보기 버튼 |
| carousel.tail.linkMobile | String | - | - | 모바일 이동 URL. 링크를 하나라도 입력하면 필수 |
| carousel.tail.linkPc | String | - | - | PC 이동 URL |
| carousel.tail.linkAnd | String | - | - | 안드로이드 앱 커스텀 스킴 |
| carousel.tail.linkIos | String | - | - | iOS 앱 커스텀 스킴 |

CAROUSEL_FEED

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| carousel | Object | ● | - | 캐러셀 객체 |
| carousel.list | json[] | ● | - | 캐러셀 리스트 |
| carousel.list.header | String | ● | 최대 20자 | 헤더 |
| carousel.list.content | String | ● | 최대 180자 | 내용 |
| carousel.list.imageUrl | String | ● | - | 파일 업로드 API로 등록한 이미지 URL |
| carousel.list.imageLink | String | - | - | 이미지 클릭 시 이동 URL |
| carousel.list.buttons | Button[] | ● | - | 버튼 목록 (캐러셀당 최소 1개, 최대 2개) |
| carousel.list.coupon | Coupon | - | - | 쿠폰 요소 |
| carousel.tail | json | - | - | 더보기 버튼 (필드는 CAROUSEL_COMMERCE 의 `carousel.tail.*` 와 동일) |

`buttons[]` 객체 (자유형은 알림톡과 필드명이 다르다)

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| name | String | ● | 14자 | 버튼 이름 |
| linkType | String | ● | 2자 | 버튼 타입 (아래 표) |
| linkMobile | String | - | - | 모바일 이동 URL |
| linkPc | String | - | - | PC 이동 URL |
| linkAndroid | String | - | - | 안드로이드 앱 커스텀 스킴 |
| linkIos | String | - | - | iOS 앱 커스텀 스킴 |

버튼 타입(`linkType`)

| 타입 | 의미 | 필수 입력 / 제약 |
|---|---|---|
| WL | 웹링크 | `linkMobile` 필수, `linkPc` 선택 |
| AL | 앱링크 | `linkIos`, `linkAndroid`, `linkMobile` 중 2개 이상 필수 |
| BK | 봇 키워드 | 해당 버튼 텍스트 전송 |
| MD | 메시지 전달 | 버튼 텍스트 + 메시지 본문 전송 |
| AC | 채널추가 | TEXT·IMAGE 형은 첫 번째 버튼으로, 그 외 유형은 마지막 버튼에만 추가 가능. `name` 은 "채널 추가" 고정 |
| BF | 비즈니스폼 | `bizFormId` 필수. 버튼명은 비즈니스폼 유형에 따라 "톡에서 설문하기", "톡에서 응모하기", "톡에서 예약하기" 중 하나 |

`coupon` 객체

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| title | String | ● | 쿠폰 제목 (아래 규칙) |
| description | String | ● | 쿠폰 설명 |
| linkMobile | String | - | 모바일에서 쿠폰 클릭 시 이동 URL |
| linkPc | String | - | PC에서 쿠폰 클릭 시 이동 URL |
| linkAndroid | String | - | 안드로이드 앱 커스텀 스킴 |
| linkIos | String | - | iOS 앱 커스텀 스킴 |

쿠폰 제목 규칙

- 변수를 쓰려면 고정 변수명 5가지 중에서만 고른다. 문자 그대로 입력한다.
  - `#{할인금액}원 할인 쿠폰`
  - `#{할인율}% 할인 쿠폰`
  - `배송비 할인 쿠폰`
  - `#{상품명} 무료 쿠폰`
  - `#{상품명} UP 쿠폰`
- 변수 대신 고정 값으로 보내려면 변수 자리에 값을 채운다. 예: `바나나우유 무료 쿠폰`, `20% 할인 쿠폰`, `50000원 할인 쿠폰`.
  - `#{할인금액}` 입력 범위 1 ~ 99,999,9999 (원문 표기 그대로)
  - `#{할인율}` 입력 범위 1 ~ 100
  - `#{상품명}` 최대 7자

> 원문 확인 필요: 쿠폰 필드 표에서 제목 필드가 `tile` 로 오타 표기되어 있다(본문 예시는 모두 `title`). 위 표는 `title` 로 적었다. 또 `#{할인금액}` 범위 `99,999,9999` 는 자릿수가 비정상이라 원문 값 그대로 옮겼다.

### 응답

공통 응답. 즉시발송은 `data[]` 배열, 예약발송은 `{regDt, webReqId}`.

### 예시

텍스트형 요청:

```json
{
  "targeting": "I",
  "kkoChId": "@메시지허브",
  "callback": "020010001",
  "chatBubbleType": "TEXT",
  "adult": false,
  "content": "안녕하세요. 브랜드 메시지 테스트 자유형 발송입니다.",
  "recvInfoLst": [ { "cliKey": "text_test", "phone": "01000010001" } ],
  "fbInfoLst": [ { "ch": "MMS", "title": "제목", "msg": "MMS 메시지 내용" } ],
  "buttons": [
    { "name": "채널 추가", "linkType": "AC" },
    { "name": "버튼01", "linkType": "WL", "linkMobile": "https://m.example.com", "linkPc": "https://www.example.com" }
  ],
  "coupon": { "title": "1000원 할인 쿠폰", "description": "설명", "linkMobile": "https://m.example.com" },
  "unsubscribePhoneNumber": "080-1234-1234",
  "unsubscribeAuthNumber": "1234"
}
```

커머스형에서 가격 필드 부분:

```json
{
  "chatBubbleType": "COMMERCE",
  "imageUrl": "https://example.com/img.jpg",
  "commerce": { "title": "상품명", "regularPrice": 1000, "discountPrice": 500, "discountRate": 50 }
}
```

캐러셀피드형 항목 부분:

```json
{
  "chatBubbleType": "CAROUSEL_FEED",
  "carousel": {
    "list": [
      { "header": "헤더1", "content": "내용1", "imageUrl": "https://example.com/1.jpg",
        "buttons": [ { "name": "버튼01", "linkType": "WL", "linkMobile": "https://m.example.com" } ] }
    ]
  }
}
```

원문에는 이 외에 이미지형·와이드형·비디오형·와이드아이템리스트형·캐러셀커머스형 예시도 있다. 구조는 위 유형별 필드 표와 같다. 와이드아이템리스트 항목 예시는 `wideItemList[]` 가 `title`, `imageUrl`, `linkMobile` 을 쓰는 것으로 나온다.

> 원문 확인 필요: `WideItem` 객체의 필드 표가 원문에 없다. 예시에서 `title`, `imageUrl`, `linkMobile` 만 확인된다.

예약발송 응답:

```json
{ "code": "10000", "message": "성공", "data": { "regDt": "2025-10-22T17:43:32", "webReqId": "BJ....pT" } }
```

> 주의
> - 버튼 최대 개수: TEXT·IMAGE 는 쿠폰을 쓰면 4개, 아니면 5개. WIDE·WIDE_ITEM_LIST 는 2개. PREMIUM_VIDEO 는 1개. COMMERCE 는 최소 1개 최대 2개.
> - 메시지 길이: TEXT·IMAGE 최대 1,300자, WIDE·PREMIUM_VIDEO 최대 76자.
> - 무료수신거부 번호 규칙은 템플릿형과 같다(둘 다 생략하면 채널 등록 정보 사용, 인증번호는 번호 없이 불가).
> - 발신번호는 사전 등록된 번호만 사용 가능.
> - 이미지 URL(`imageUrl`)은 반드시 파일 업로드 API로 등록한 URL을 쓴다.
> - 원문 확인 필요: 캐러셀 리스트 개수가 "캐러셀 인트로(head) 사용 시 15개, 그 외 26개"로 적혀 있으나 일반적이지 않은 수치라 원문 재확인이 필요하다.
> - 원문 확인 필요: 쿠폰 변수 5종과 필드 범위는 원문에 적힌 대로이며, `carousel.head.content` 설명이 "mobile 환경에서 버튼 클릭 시 이동할 url"로 잘못 복사된 듯하다(내용 필드로 추정).
