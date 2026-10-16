# 3.4 카카오 V2 브랜드메시지 템플릿 관리
> 원문: https://doc.msghub.uplus.co.kr/rest-api/03채널/0304mnt-kko_v2-brandtalk/ · 확인일 2026-10-16

카카오 브랜드메시지(원문 제목 3.4 카카오 V2 브랜드메시지) 템플릿의 등록·수정·조회·삭제와 채널 무료수신거부(080) 정보 수정 API 모음이다. 모든 API 가 mnt-api 호스트이며 `Authorization: Bearer {token}` 헤더가 필요하다.

## 한눈에 보기

| 기능 | Method | 경로 | 호스트 |
|---|---|---|---|
| 브랜드메시지 템플릿 등록 | POST | `/kko/v2/channel/brand/template/create` | mnt-api |
| 브랜드메시지 템플릿 수정 | POST | `/kko/v2/channel/brand/template/update` | mnt-api |
| 채널별 템플릿 전체 조회 | GET | `/kko/v2/channel/brand/template/list` | mnt-api |
| 템플릿 상세 조회 | POST | `/kko/v2/channel/brand/template/get` | mnt-api |
| 템플릿 삭제 | POST | `/kko/v2/channel/brand/template/delete` | mnt-api |
| 채널 무료수신거부(080) 정보 수정 | POST | `/kko/v2/channel/brand/unsubscribeContent/update` | mnt-api |

원문 API 수 6개(01~06)와 일치. 이미지는 별도 "파일 업로드 API"(다른 문서)로 먼저 올린 뒤 그 URL 을 쓴다.

## 공통 개념

### 공통 헤더

| 이름 | 타입 | 필수 | 설명 |
|---|---|---|---|
| Authorization | String | ● | 사용자 인증 토큰 (`Bearer {token}`) |
| Content-Type | String | ● | `application/json` |

### 채널 식별 필드

| 필드 | 타입 | 길이 | 설명 |
|---|---|---|---|
| kkoChId | String | 최대 61자 | 카카오 채널 ID (예: `@채널명`) |
| kkoGrpId | String | 최대 100자 | 카카오 그룹 ID |
| senderKeyType | String | 1자 | 채널ID 유형. `S` 일반ID(기본), `G` 그룹ID |
| tmpltCode | String | 최대 50자 | 템플릿 코드(공백 불가). 등록 시 생략하면 서버가 생성 |

### 템플릿 유형 (chatBubbleType)

8종. 유형에 따라 필수 필드와 buttons/coupon 사용 가능 여부가 다르다.

| 값 | 설명 | content 한도 | buttons 개수 | 비고 |
|---|---|---|---|---|
| TEXT | 텍스트형 | 최대 1,300자 (줄바꿈 99개, URL 형식 입력 가능) | coupon 사용 시 최대 4개, 그 외 최대 5개 | |
| IMAGE | 이미지형 | 최대 400자 (줄바꿈 29개, URL 형식 입력 가능) | coupon 사용 시 최대 4개, 그 외 최대 5개 | imageUrl 필수 |
| WIDE | 와이드형 | 최대 76자 (줄바꿈 5개) | 최대 2개 | imageUrl 필수 |
| WIDE_ITEM_LIST | 와이드 아이템 리스트형 | content 없음(header 사용) | 최대 2개 | header, mainWideItem, subWideItemList 필수 |
| PREMIUM_VIDEO | 프리미엄 동영상형 | 최대 76자 (줄바꿈 5개) | 최대 1개 | video 필수 |
| COMMERCE | 커머스형 | content 없음 | 최소 1개, 최대 2개 | imageUrl, commerce 필수 |
| CAROUSEL_FEED | 캐러셀 피드형 | content 없음 | 캐러셀 항목별 1~2개 | 최상위 buttons/coupon 사용 불가 |
| CAROUSEL_COMMERCE | 캐러셀 커머스형 | content 없음 | 캐러셀 항목별 1~2개 | 최상위 buttons/coupon 사용 불가 |

> 원문 확인 필요: 수정 API 표에는 content 한도가 "TEXT, IMAGE: 최대 1,300자"로, 등록 API 표에는 "IMAGE: 최대 400자"로 적혀 있어 서로 다르다. 위 표는 등록 API 기준(응답 설명도 IMAGE 400자).

### Button 객체

요청의 `buttons[]`, 응답의 `data.buttons[]`, 캐러셀 항목의 `list[].buttons[]` 가 모두 같은 구조다.

| 필드 | 타입 | 설명 |
|---|---|---|
| buttons[].name | String | 버튼 이름 |
| buttons[].linkType | String | 버튼 타입 ([버튼 타입 코드](#버튼-타입-코드) 참고) |
| buttons[].linkMobile | String | 모바일에서 눌렀을 때 이동할 URL |
| buttons[].linkPc | String | PC 에서 눌렀을 때 이동할 URL |
| buttons[].linkAndroid | String | 안드로이드에서 실행할 앱 커스텀 스킴 |
| buttons[].linkIos | String | iOS 에서 실행할 앱 커스텀 스킴 |
| buttons[].bizFormId | Number | 비즈니스폼 ID |

> 주의
> - WL(웹링크)은 linkAndroid, linkIos 를 사용하지 않는다.
> - BF(비즈니스폼)는 bizFormId 가 필수다.
> - BF 버튼 이름은 비즈니스폼 유형에 따라 "톡에서 설문하기", "톡에서 응모하기", "톡에서 예약하기" 중 하나만 쓸 수 있다(등록 API 원문 기준, 수정 API 원문에는 이 항목 없음).
> - AC(채널추가) 버튼은 TEXT·IMAGE 유형에서는 첫 번째 버튼, 그 밖의 유형에서는 마지막 버튼으로 등록해야 한다.

### Coupon 객체

요청의 `coupon`, 응답의 `data.coupon`, 캐러셀 항목의 `list[].coupon` 이 같은 구조다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| title | String | ● | 쿠폰 제목 ([쿠폰 제목 규칙](#쿠폰-제목-규칙) 참고) |
| description | String | ● | 쿠폰 설명 |
| linkMobile | String | - | 모바일에서 쿠폰을 눌렀을 때 이동할 URL |
| linkPc | String | - | PC 에서 쿠폰을 눌렀을 때 이동할 URL |
| linkAndroid | String | - | 안드로이드에서 실행할 앱 커스텀 스킴 |
| linkIos | String | - | iOS 에서 실행할 앱 커스텀 스킴 |

> 원문 확인 필요: 원문 표에는 쿠폰·와이드 아이템·커머스 제목 필드가 `tile` 로 표기되어 있으나 요청 예시 JSON 은 모두 `title` 을 쓴다(응답 예시도 `title`). `tile` 은 오타로 보이며 이 문서는 `title` 로 적는다.

> 주의
> - 채널 쿠폰 URL(포맷 `alimtalk=coupon://`)을 쓰면 linkAndroid, linkIos 중 하나가 필수다.
> - 채널 쿠폰이 아닌 기본 쿠폰을 쓰면 linkMobile 이 필수다.
> - 캐러셀 유형(CAROUSEL_FEED, CAROUSEL_COMMERCE)은 최상위 coupon 을 쓸 수 없고 `carousel.list[].coupon` 으로만 넣는다.

#### 쿠폰 제목 규칙

쿠폰 제목은 아래 5가지 고정 문구 중 하나여야 한다. 변수 자리는 그대로 `#{...}` 로 등록하면 발송 시 값을 채우는 변수가 되고, 숫자·문자를 직접 넣으면 고정 값이 된다.

| 고정 문구 | 변수 자리를 고정 값으로 넣을 때 범위 | 고정 값 예시 |
|---|---|---|
| `#{할인금액}원 할인 쿠폰` | 1 ~ 99,999,9999 | `50000원 할인 쿠폰` |
| `#{할인율}% 할인 쿠폰` | 1 ~ 100 | `20% 할인 쿠폰` |
| `배송비 할인 쿠폰` | (변수 없음) | - |
| `#{상품명} 무료 쿠폰` | 최대 7자 | `바나나우유 무료 쿠폰` |
| `#{상품명} UP 쿠폰` | 최대 7자 | - |

> 원문 확인 필요: 할인금액 범위가 원문에 "1 ~ 99,999,9999"(자릿수가 맞지 않는 표기)로 되어 있다. 원문 그대로 옮겼다.

### WideItem 객체

`mainWideItem`(단일 객체)과 `subWideItemList[]`(배열)가 같은 구조다. 응답의 `data.wideItemList[]` 는 필드명이 약간 다르다([응답 공통](#템플릿-응답-data-필드-등록수정상세-공통) 참고).

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| title | String | mainWideItem 은 -, subWideItemList 는 ● | 아이템 제목. mainWideItem 최대 25자, subWideItemList 최대 30자 |
| imageUrl | String | ● | 이미지 업로드 API 로 등록한 아이템 이미지 URL |
| linkMobile | String | ● | 모바일 이동 URL. 링크를 하나라도 입력하면 linkMobile 필수 |
| linkPc | String | - | PC 이동 URL |
| linkAndroid | String | - | 안드로이드 커스텀 스킴 |
| linkIos | String | - | iOS 커스텀 스킴 |

### Video 객체

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| videoUrl | String | ● | 500자 | 카카오TV 동영상 URL |
| thumbnailUrl | String | - | 500자 | 이미지 업로드 API 로 등록한 썸네일 URL |

### Commerce 객체

`commerce`(COMMERCE 유형)와 `carousel.list[].commerce`(CAROUSEL_COMMERCE 유형)가 같은 구조다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| title | String | ● | 상품 제목 (30자) |
| regularPrice | Number | - | 정상가격 (0 ~ 99,999,999) |
| discountPrice | Number | - | 할인 후 가격 (0 ~ 99,999,999) |
| discountRate | Number | - | 할인율 (1 ~ 100). 정액 할인 가격과 둘 중 하나만 입력 |
| discountFixed | Number | - | 정액 할인 가격. 할인율과 둘 중 하나만 입력 |

> 원문 확인 필요: discountFixed 범위가 COMMERCE 요청 표에는 "0 ~ 999,999", Commerce 객체 표에는 "0 ~ 99,999,999"로 서로 다르다.

> 주의: 가격 필드(regularPrice, discountPrice, discountRate, discountFixed)를 입력하지 않으면 고정 변수명으로 저장된다. 고정 변수명을 쓰면 메시지 발송 시 금액을 바꿔서 보낼 수 있다. 응답에서는 `regularPriceName`, `discountPriceName`, `discountRateName`, `discountFixedName` 으로 변수명(예: `#{정상가격}`)이 내려온다(CAROUSEL_COMMERCE 응답 예시 기준).

### Carousel 객체

CAROUSEL_COMMERCE, CAROUSEL_FEED 유형에서 `carousel` 이 필수다.

| 필드 | 타입 | 필수 | 크기 | 설명 |
|---|---|---|---|---|
| carousel.head | Object | - | | 캐러셀 인트로. CAROUSEL_COMMERCE 에서만 사용 |
| carousel.head.header | String | ● (head 사용 시) | 최대 20자 | 인트로 헤더 |
| carousel.head.content | String | ● (head 사용 시) | | 인트로 내용 |
| carousel.head.imageUrl | String | ● (head 사용 시) | | 파일 업로드 API 로 등록한 인트로 이미지 URL |
| carousel.head.linkMobile | String | - | | 모바일 이동 URL. 링크를 하나라도 입력하면 linkMobile 필수 |
| carousel.head.linkPc | String | - | | PC 이동 URL |
| carousel.head.linkAndroid | String | - | | 안드로이드 커스텀 스킴 |
| carousel.head.linkIos | String | - | | iOS 커스텀 스킴 |
| carousel.list | Object[] | ● | | 캐러셀 목록. head 사용 시 1~5개, 그 외 2~6개 |
| carousel.list[].header | String | CAROUSEL_FEED 에서 ● | 최대 20자 | 항목 헤더 (CAROUSEL_FEED 전용) |
| carousel.list[].content | String | CAROUSEL_FEED 에서 ● | 최대 180자 | 항목 내용 (CAROUSEL_FEED 전용) |
| carousel.list[].additionalContent | String | - | 최대 34자 | 항목 부가정보 (CAROUSEL_COMMERCE 전용) |
| carousel.list[].imageUrl | String | ● | | 파일 업로드 API 로 등록한 이미지 URL |
| carousel.list[].imageLink | String | - | | 이미지 클릭 시 이동 URL |
| carousel.list[].commerce | Commerce | CAROUSEL_COMMERCE 에서 ● | | [Commerce 객체](#commerce-객체) |
| carousel.list[].buttons | Button[] | ● | | [Button 객체](#button-객체). 항목당 최소 1개, 최대 2개 |
| carousel.list[].coupon | Coupon | - | | [Coupon 객체](#coupon-객체) |
| carousel.tail | Object | - | | "더보기" 버튼 |
| carousel.tail.linkMobile | String | - | | 모바일 이동 URL. 링크를 하나라도 입력하면 linkMobile 필수 |
| carousel.tail.linkPc | String | - | | PC 이동 URL |
| carousel.tail.linkAndroid | String | - | | 안드로이드 커스텀 스킴 |
| carousel.tail.linkIos | String | - | | iOS 커스텀 스킴 |

> 원문 확인 필요: `carousel.head.content` 의 설명이 원문 일부 표에서 "mobile 환경에서 버튼 클릭 시 이동할 url"로 복붙되어 있다. 필드명과 Carousel 객체 표의 맥락상 인트로 내용으로 보이나 확정되지 않았다. 또 원문 요청 표는 `carousel.list` 의 header·imageUrl 등을 유형 구분 없이 필수(●)로 표기하나, 유형별 전용 필드(header/content 는 FEED, additionalContent/commerce 는 COMMERCE)라는 설명이 함께 있어 위 표에서는 유형별로 구분했다.

### 버튼 타입 코드

| 값 | 설명 |
|---|---|
| WL | 웹링크 |
| AL | 앱링크 |
| BK | 봇키워드 |
| MD | 메시지전달 |
| AC | 채널추가 |
| BF | 비즈니스폼 |

### 템플릿 응답 data 필드 (등록·수정·상세 공통)

등록·수정·상세 조회 응답의 `data` 는 구조가 거의 같다. 유형에 해당하는 필드만 내려온다. 상세 조회에는 `tmpltCode` 가 응답 표에 없다.

| 필드 | 타입 | 설명 |
|---|---|---|
| data.tmpltCode | String | 템플릿 코드 (등록·수정 응답) |
| data.name | String | 템플릿명 |
| data.kkoChId | String | 카카오 채널 검색용 ID |
| data.senderKeyType | String | 발신 프로필 타입 (S 카카오채널, G 그룹) |
| data.chatBubbleType | String | 메시지 타입 |
| data.adult | boolean | 성인용 템플릿 여부 |
| data.header | String | 템플릿 헤더 (WIDE_ITEM_LIST, PREMIUM_VIDEO 에서 사용) |
| data.content | String | 템플릿 내용 |
| data.videoUrl | String | 카카오TV 동영상 URL |
| data.thumbnailUrl | String | 동영상 썸네일 URL |
| data.buttons[] | Button[] | [Button 객체](#button-객체)와 동일 필드 |
| data.coupon | Coupon | [Coupon 객체](#coupon-객체)와 동일 필드 |
| data.carousel | Carousel | [Carousel 객체](#carousel-객체)와 동일 구조 (head, list, tail) |
| data.wideItemList[].title | String | 와이드 아이템 제목 |
| data.wideItemList[].imageUrl | String | 와이드 아이템 이미지 URL |
| data.wideItemList[].linkMobile | String | 모바일 이동 URL |
| data.wideItemList[].linkPc | String | PC 이동 URL |
| data.wideItemList[].linkAndroid | String | 안드로이드 커스텀 스킴 |
| data.wideItemList[].linkIos | String | iOS 커스텀 스킴 |

> 원문 확인 필요: 수정 API 응답 표의 `data.wideItemList[].linkAnd` 는 `linkAndroid` 의 오타로 보인다. 응답 구조는 요청 구조와 달리 `mainWideItem`/`subWideItemList` 가 `wideItemList[]` 하나로 합쳐져 내려온다(상세 조회 예시에서 첫 항목이 메인 아이템).

---

## 브랜드메시지 템플릿 등록

`POST /kko/v2/channel/brand/template/create`

브랜드메시지 템플릿을 등록한다. 유형별 필드는 [템플릿 유형](#템플릿-유형-chatbubbletype)과 각 객체 표를 참고한다.

### 요청 Body

공통 필드

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| kkoChId | String | ● | 최대 61자 | 카카오 채널 ID |
| kkoGrpId | String | - | 최대 100자 | 카카오 그룹 ID |
| tmpltCode | String | - | 최대 50자 | 템플릿 코드(공백 불가) |
| senderKeyType | String | - | 1자 | S 일반ID(기본), G 그룹ID |
| name | String | ● | 최대 200자 | 템플릿 이름 |
| chatBubbleType | String | ● | | 메시지 타입 8종 중 하나 |
| adult | boolean | ● | | 성인용 템플릿 여부 |
| content | String | - | 유형별 | TEXT, IMAGE, WIDE, PREMIUM_VIDEO 에서 사용 |
| buttons | Button[] | - | | 유형별 개수 제한. 캐러셀 유형은 사용 불가 |
| coupon | Coupon | - | | 캐러셀 유형은 사용 불가 |

IMAGE, WIDE 유형

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| imageUrl | String | ● | 최대 500자 | 파일 업로드 API 로 등록한 이미지 URL |
| imageLink | String | - | 최대 500자 | 이미지 클릭 시 이동 URL |

WIDE_ITEM_LIST 유형

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| header | String | ● | 최대 20자 | 템플릿 헤더 |
| mainWideItem | WideItem | ● | | 첫 번째 아이템 ([WideItem](#wideitem-객체), title 은 선택·최대 25자) |
| subWideItemList | WideItem[] | ● | | 2~4번째 아이템 (title 필수·최대 30자) |

PREMIUM_VIDEO 유형

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| header | String | - | 최대 20자 | 템플릿 헤더 |
| video | Object | ● | | [Video 객체](#video-객체) |
| video.videoUrl | String | ● | 500자 | 카카오TV 동영상 URL |
| video.thumbnailUrl | String | - | 500자 | 썸네일 URL |

COMMERCE 유형

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| additionalContent | String | - | 최대 34자 | 부가정보 (줄바꿈 최대 1개) |
| imageUrl | String | ● | 최대 500자 | 파일 업로드 API 로 등록한 이미지 URL |
| imageLink | String | - | 최대 500자 | 이미지 클릭 시 이동 URL (원문 COMMERCE 요청 표에는 없고 요청 예시에 등장) |
| commerce | Object | ● | | [Commerce 객체](#commerce-객체) |

CAROUSEL_COMMERCE, CAROUSEL_FEED 유형: `carousel` 이 필수이며 구조는 [Carousel 객체](#carousel-객체)를 따른다.

### 응답

[템플릿 응답 data 필드](#템플릿-응답-data-필드-등록수정상세-공통) 참고.

### 예시

TEXT 유형 요청

```json
{
  "kkoChId": "@채널명",
  "name": "TEXT형",
  "chatBubbleType": "TEXT",
  "adult": false,
  "content": "#{name}님 안녕하세요. 브랜드 메시지 테스트입니다.",
  "buttons": [
    { "name": "버튼01", "linkType": "WL",
      "linkMobile": "https://example.com/#{linkMobile}",
      "linkPc": "https://example.com/#{linkPc}" }
  ],
  "coupon": {
    "title": "#{상품명} 무료 쿠폰",
    "description": "#{쿠폰내용}",
    "linkMobile": "https://example.com/#{linkMobile}"
  }
}
```

WIDE_ITEM_LIST 유형 요청

```json
{
  "kkoChId": "@채널명",
  "tmpltCode": "WIDEITEMLIST02",
  "name": "와이드아이템리스트형",
  "chatBubbleType": "WIDE_ITEM_LIST",
  "adult": false,
  "header": "#{헤더}",
  "mainWideItem": { "title": "#{메인타이틀}", "imageUrl": "https://example.com/main.jpg", "linkMobile": "https://example.com" },
  "subWideItemList": [
    { "title": "#{서브타이틀}", "imageUrl": "https://example.com/sub1.jpg", "linkMobile": "https://example.com/#{linkMobile}" },
    { "title": "#{서브타이틀2}", "imageUrl": "https://example.com/sub2.jpg", "linkMobile": "https://example.com/#{linkMobile}" }
  ],
  "buttons": [ { "name": "버튼01", "linkType": "WL", "linkMobile": "https://example.com/#{linkMobile}" } ]
}
```

COMMERCE 유형 요청

```json
{
  "kkoChId": "@채널명",
  "tmpltCode": "COMMERCE02",
  "name": "커머스형",
  "chatBubbleType": "COMMERCE",
  "adult": false,
  "additionalContent": "#{부가내용}",
  "imageUrl": "https://example.com/item.jpg",
  "commerce": { "title": "#{커머스제목}", "regularPrice": 1000000, "discountPrice": 900000, "discountRate": 10 },
  "buttons": [ { "name": "버튼01", "linkType": "MD" } ]
}
```

CAROUSEL_FEED 유형 요청 (캐러셀 항목은 buttons 가 필수이고 AC 버튼은 name 없이 `linkType` 만 넣은 예가 원문에 있다)

```json
{
  "kkoChId": "@채널명",
  "name": "캐러셀피드형",
  "chatBubbleType": "CAROUSEL_FEED",
  "adult": false,
  "carousel": {
    "list": [
      { "header": "#{헤더1}", "content": "#{피드내용1}", "imageUrl": "https://example.com/1.jpg",
        "buttons": [
          { "name": "버튼01", "linkType": "WL", "linkMobile": "https://example.com/#{linkMobile}" },
          { "name": "버튼02", "linkType": "AL", "linkAndroid": "app://example/#{linkAndroid}", "linkIos": "app://example/#{linkIos}" }
        ] },
      { "header": "#{헤더2}", "content": "#{피드내용2}", "imageUrl": "https://example.com/2.jpg",
        "buttons": [ { "linkType": "AC" } ] }
    ],
    "tail": { "linkMobile": "https://example.com", "linkPc": "https://example.com" }
  }
}
```

CAROUSEL_COMMERCE 유형 요청

```json
{
  "kkoChId": "@채널명",
  "name": "캐러셀커머스형",
  "chatBubbleType": "CAROUSEL_COMMERCE",
  "adult": false,
  "carousel": {
    "head": { "header": "#{헤드헤더}", "content": "#{헤드내용}", "imageUrl": "https://example.com/head.jpg", "linkMobile": "https://example.com/#{linkMobile}" },
    "list": [
      { "additionalContent": "#{리스트부가정보}", "imageUrl": "https://example.com/1.jpg",
        "commerce": { "title": "#{커머스제목}" },
        "buttons": [ { "name": "버튼", "linkType": "WL", "linkMobile": "https://example.com/#{linkMobile}" } ],
        "coupon": { "title": "#{할인율}% 할인 쿠폰", "description": "#{쿠폰내용}", "linkMobile": "https://example.com/#{linkMobile}" } }
    ],
    "tail": { "linkMobile": "https://example.com" }
  }
}
```

응답 (CAROUSEL_COMMERCE, 일부 생략)

```json
{
  "code": "10000",
  "message": "성공",
  "data": {
    "kkoChId": "@msghub",
    "senderKeyType": "S",
    "tmpltCode": "TP_CODE_EXAMPLE",
    "name": "캐러셀커머스형",
    "chatBubbleType": "CAROUSEL_COMMERCE",
    "adult": false,
    "carousel": {
      "list": [
        { "commerce": { "title": "#{커머스제목}", "regularPriceName": "#{정상가격}", "discountPriceName": "#{할인가격}",
                        "discountRateName": "#{할인율}", "discountFixedName": "#{정액할인가격}" } }
      ]
    }
  }
}
```

> 주의
> - 이미지는 파일 업로드 API 를 통해 템플릿 유형별로 등록한 뒤 URL 을 넣는다.
> - 변수명은 최대 20개, 각 20자 이내이며 한글·영문·숫자·`-`·`_` 만 쓸 수 있다.
> - WIDE_ITEM_LIST 에서 mainWideItem 은 title 이 필수가 아니지만 subWideItemList 는 title 이 필수다.
> - COMMERCE 에서 가격 필드를 비우면 고정 변수명으로 저장되어 발송 시 금액을 바꿀 수 있다.
> - AC 버튼은 TEXT·IMAGE 는 첫 번째, 그 외 유형은 마지막 버튼으로 둔다.
> - 캐러셀 유형은 최상위 buttons, coupon 을 쓸 수 없다. 캐러셀 항목마다 buttons 는 1~2개다.
> - 원문 확인 필요: 요청 표는 WIDE_ITEM_LIST 의 `mainWideItem.tile` 처럼 `tile` 로 적혀 있으나 예시는 `title` 이다(위 공통 개념 참고). 응답 예시 JSON 은 data 필드 전체를 보여주지 않고 CAROUSEL_COMMERCE 한 가지만 있다. 응답 `data.carousel.list.commerce` 설명은 요청과 달리 `regularPrice` 대신 `...Name` 변수명이 내려오는 예시다.

---

## 브랜드메시지 템플릿 수정

`POST /kko/v2/channel/brand/template/update`

등록한 브랜드메시지 템플릿을 수정한다. 요청 구조는 등록과 같고 `tmpltCode` 가 필수이며 `adult` 가 선택이라는 점이 다르다.

### 요청 Body

[등록 API 의 요청 Body](#요청-body) 와 동일하되 아래만 다르다.

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| tmpltCode | String | ● | 최대 50자 | 수정할 템플릿 코드(공백 불가) |
| adult | boolean | - | | 성인용 템플릿 여부 |

나머지 필드(kkoChId, kkoGrpId, senderKeyType, name, chatBubbleType, content, buttons, coupon, imageUrl, imageLink, header, mainWideItem, subWideItemList, video, additionalContent, commerce, carousel)와 유형별 필수 규칙은 등록과 동일하다. `name`, `chatBubbleType` 은 수정에서도 필수다.

### 응답

[템플릿 응답 data 필드](#템플릿-응답-data-필드-등록수정상세-공통) 참고.

### 예시

```json
{
  "kkoChId": "@채널명",
  "tmpltCode": "TP_CODE_EXAMPLE",
  "name": "TEXT형",
  "chatBubbleType": "TEXT",
  "adult": false,
  "content": "#{name}님 안녕하세요. 브랜드 메시지 테스트입니다.",
  "buttons": [
    { "name": "버튼01", "linkType": "WL", "linkMobile": "https://example.com/#{linkMobile}" }
  ],
  "coupon": { "title": "#{상품명} 무료 쿠폰", "description": "#{쿠폰내용}", "linkMobile": "https://example.com/#{linkMobile}" }
}
```

> 주의
> - 유형별 요청 예시는 등록 API 의 예시에 `tmpltCode` 만 추가하면 된다.
> - 원문 확인 필요: 수정 API 의 응답 예시 JSON 이 TEXT 요청과 달리 캐러셀 커머스형(CAROUSEL_COMMERCE) 내용으로 실려 있다(예시 복붙으로 보임). 수정 시 chatBubbleType 을 바꿀 수 있는지는 원문에 언급이 없다.

---

## 채널별 템플릿 전체 조회

`GET /kko/v2/channel/brand/template/list`

채널에 등록된 브랜드메시지 템플릿 목록을 페이지 단위로 조회한다.

### 요청 Query

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| kkoChId | String | ● | 최대 61자 | 카카오 채널 ID (`@` 는 `%40` 으로 인코딩) |
| page | Number | - | | 페이지 번호 |
| size | Number | - | | 페이지당 노출 개수 |

### 응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| data.list[].tmpltCode | String | 템플릿 코드 |
| data.list[].name | String | 템플릿명 |
| data.list[].status | String | 템플릿 상태 |
| data.list[].regDt | String | 등록일자 |
| data.list[].updDt | String | 수정일자 |
| data.totalElements | Number | 전체 데이터 개수 |
| data.totalPages | Number | 전체 페이지 수 |
| data.currentPage | Number | 현재 페이지 번호 |
| data.size | Number | 페이지당 노출 개수 |
| data.hasNext | boolean | 다음 페이지 존재 여부 |

### 예시

요청

```
GET /kko/v2/channel/brand/template/list?kkoChId=%40test&page=0&size=20
```

응답

```json
{
  "code": "10000",
  "message": "성공",
  "data": {
    "list": [
      { "tmpltCode": "TP_CODE_EXAMPLE", "name": "캐러셀커머스형", "status": "A",
        "regDt": "2025-10-22 09:56:18", "updDt": "2025-10-22 09:56:18" }
    ],
    "totalElements": 2,
    "totalPages": 0,
    "currentPage": 0,
    "size": 2,
    "hasNext": true
  }
}
```

> 주의
> - 원문 확인 필요: `status` 코드값(예시의 `A`)의 의미 표가 원문에 없다.
> - 원문 확인 필요: page 시작 번호와 size 기본값·최대값이 명시되어 있지 않다(예시는 page=0). 예시 응답은 `totalPages: 0`, `size: 2`, `totalElements: 2` 인데 `hasNext: true` 라서 값들이 서로 일관되지 않는다.
> - 원문 확인 필요: 목록 응답에는 `chatBubbleType` 이 없다. 유형까지 알아야 하면 상세 조회를 써야 한다.

---

## 템플릿 상세 조회

`POST /kko/v2/channel/brand/template/get`

템플릿 코드로 템플릿 하나의 전체 구성을 조회한다.

### 요청 Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| kkoChId | String | ● | 최대 61자 | 카카오 채널 ID |
| kkoGrpId | String | - | 최대 100자 | 카카오 그룹 ID |
| tmpltCode | String | ● | 최대 50자 | 템플릿 코드(공백 불가) |

### 응답

[템플릿 응답 data 필드](#템플릿-응답-data-필드-등록수정상세-공통) 참고. 유형에 해당하는 필드만 내려온다.

### 예시

요청

```json
{ "kkoChId": "@채널명", "tmpltCode": "TP_CODE_EXAMPLE" }
```

응답 (WIDE_ITEM_LIST)

```json
{
  "code": "10000",
  "message": "성공",
  "data": {
    "kkoChId": "@채널명",
    "senderKeyType": "S",
    "name": "WIDEITEMLIST형",
    "chatBubbleType": "WIDE_ITEM_LIST",
    "adult": false,
    "header": "템플릿 아이템 리스트 헤더",
    "buttons": [ { "name": "버튼", "linkType": "AL", "linkAndroid": "app://example", "linkIos": "app://example" } ],
    "wideItemList": [
      { "title": "메인아이템 타이틀", "imageUrl": "https://example.com/main.jpg", "linkMobile": "https://example.com" },
      { "title": "서브아이템 타이틀1", "imageUrl": "https://example.com/sub1.jpg", "linkMobile": "https://example.com" }
    ]
  }
}
```

> 주의: 요청에 `mainWideItem`/`subWideItemList` 로 넣은 와이드 아이템은 응답에서 `wideItemList[]` 하나로 합쳐져 내려온다.

---

## 템플릿 삭제

`POST /kko/v2/channel/brand/template/delete`

템플릿을 삭제한다.

### 요청 Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| kkoChId | String | ● | 최대 61자 | 카카오 채널 ID |
| kkoGrpId | String | - | 최대 100자 | 카카오 그룹 ID |
| senderKeyType | String | - | 1자 | S 일반ID(기본), G 그룹ID |
| tmpltCode | String | ● | 최대 50자 | 삭제할 템플릿 코드(공백 불가) |

### 응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| data.kkoChId | String | 카카오 채널 검색용 ID |
| data.kkoGrpId | String | 카카오 그룹 ID |
| data.senderKeyType | String | 발신 프로필 타입 (S 카카오채널, G 그룹) |
| data.tmpltCode | String | 템플릿 코드 |

### 예시

요청

```json
{ "kkoChId": "@채널명", "senderKeyType": "S", "tmpltCode": "TP_CODE_EXAMPLE" }
```

응답

```json
{
  "code": "10000",
  "message": "성공",
  "data": { "kkoChId": "@채널명", "kkoGrpId": null, "senderKeyType": "S", "tmpltCode": "TP_CODE_EXAMPLE" }
}
```

---

## 채널 무료수신거부(080) 정보 수정

`POST /kko/v2/channel/brand/unsubscribeContent/update`

브랜드메시지 발송에 쓰는 080 무료수신거부 정보를 채널 단위로 수정한다.

### 요청 Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| kkoChId | String | ● | 최대 61자 | 카카오 채널 ID |
| cm080Num | String | ● | | 무료수신거부 전화번호 (`080-1234-5678` 포맷) |
| cm080AuthNum | String | - | | 무료수신거부 전화번호 인증번호(내선번호 개념) |

### 응답

`data` 없이 `code`, `message` 만 내려온다.

### 예시

요청

```json
{ "kkoChId": "@채널명", "cm080Num": "080-0000-0000", "cm080AuthNum": "000000" }
```

응답

```json
{ "code": "10000", "message": "성공" }
```

> 주의
> - cm080AuthNum 은 080 번호의 내선번호 개념의 옵션값이며 cm080Num 없이는 입력할 수 없다.

---

## 결과 코드

원문의 "결과 코드" 항목은 이 페이지에 표가 없고 제목만 있다. 성공은 예시 기준 `code: "10000"`, `message: "성공"` 이다.

> 원문 확인 필요: 결과 코드 목록은 이 페이지에서 확인되지 않는다. 공통 결과 코드 문서를 별도로 참고해야 한다.
