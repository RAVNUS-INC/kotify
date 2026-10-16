# 3.5 RCS 관리 (브랜드·챗봇·템플릿·대행사·통계)
> 원문: https://doc.msghub.uplus.co.kr/rest-api/03채널/0305mnt-rcs/ · 확인일 2026-10-16

RCS 브랜드, 챗봇(발신번호), 템플릿(메시지베이스), 대행사 하위 고객, 고객반응 통계를 다루는 관리 API 모음이다. 메시지 발송 API가 아니며 호스트는 `mnt-api` 이다. 상용·검수 URL 은 00-README 를 본다.

## 한눈에 보기

| # | 기능 | Method | 경로 | 호스트 |
|---|---|---|---|---|
| 3.1 | 브랜드 목록 조회 | GET | `/rcs/v1/brand` | mnt-api |
| 3.2 | 브랜드 상세 조회 | GET | `/rcs/v1/brand/{brandId}` | mnt-api |
| 3.3 | 브랜드 카테고리 조회 | GET | `/rcs/v1/brand/categories` | mnt-api |
| 3.4 | 브랜드 등록 | POST | `/rcs/v1/brand` | mnt-api |
| 3.5 | 브랜드 수정 | PUT | `/rcs/v1/brand/{brandId}` | mnt-api |
| 3.6 | 브랜드 삭제 | DELETE | `/rcs/v1/brand/{brandId}` | mnt-api |
| 4.1 | 챗봇 리스트 조회 | GET | `/rcs/v1/brand/{brandId}/chatbot` | mnt-api |
| 4.2 | 챗봇 상세 조회 | GET | `/rcs/v1/brand/{brandId}/chatbot/{chatbotId}` | mnt-api |
| 4.3 | 챗봇 등록 요청 | POST | `/rcs/v1/brand/{brandId}/chatbot` | mnt-api |
| 4.4 | 챗봇 수정 요청 | PUT | `/rcs/v1/brand/{brandId}/chatbot/{chatbotId}` | mnt-api |
| 4.5 | 챗봇 삭제 요청 | DELETE | `/rcs/v1/brand/{brandId}/chatbot/{chatbotId}` | mnt-api |
| 4.6 | 대화방ID 등록 가능 여부 조회 | GET | `/rcs/v1/usableQuery/chatbotId/{chatbotId}` | mnt-api |
| 5.1 | 템플릿 양식 목록 조회 | GET | `/rcs/v1/messagebase/messagebaseform` | mnt-api |
| 5.2 | 템플릿 유형 상세 조회 | GET | `/rcs/v1/messagebase/messagebaseform/{messagebaseformId}` | mnt-api |
| 5.3 | 이통사 기본 템플릿 목록 조회 | GET | `/rcs/v1/messagebase/common` | mnt-api |
| 5.4 | 이통사 기본 템플릿 상세 조회 | GET | `/rcs/v1/messagebase/common/{messagebaseId}` | mnt-api |
| 5.5 | 템플릿 리스트 조회 | GET | `/rcs/v1/brand/{brandId}/messagebase` | mnt-api |
| 5.6 | 템플릿 상세 조회 | GET | `/rcs/v1/brand/{brandId}/messagebase/{messagebaseId}` | mnt-api |
| 5.7 | 템플릿 등록 요청 | POST | `/rcs/v1.1/{brandId}/messagebase` | mnt-api |
| 5.8 | 템플릿 수정 요청 | PUT | `/rcs/v1/brand/{brandId}/messagebase/{messagebaseId}` | mnt-api |
| 5.9 | 템플릿 삭제 요청 | DELETE | `/rcs/v1/brand/{brandId}/messagebase/{messagebaseId}` | mnt-api |
| 5.10 | 템플릿 승인 요청 취소 | PUT | `/rcs/v1/brand/{brandId}/messagebase/{messagebaseId}/cancel` | mnt-api |
| 6.1 | 대행사 하위 고객사 프로젝트 목록 조회 | POST | `/rcs/v1/agency/brand/project` | mnt-api |
| 6.2 | 대행사 하위 고객사 프로젝트 연결 | POST | `/rcs/v1/agency/subCorp/subBrandProjectReg` | mnt-api |
| 6.3 | 대행사 하위 브랜드 조회 | GET | `/rcs/v1/agency/{agencyId}/corp/{corpRegNum}/brand` | mnt-api |
| 6.4 | 대행사 하위 브랜드 상세 조회 | GET | `/rcs/v1/agency/{agencyId}/brand/{brandId}` | mnt-api |
| 6.5 | 대행사 하위고객 브랜드 수신 등록 목록 조회 | POST | `/rcs/v1/agency/subCorp/brandRegList` | mnt-api |
| 6.6 | 대행사 하위고객 브랜드 수신 등록 설정/해제 | POST | `/rcs/v1/agency/subCorp/brand` | mnt-api |
| 6.7 | 대행사 하위고객 브랜드 수신 등록/제외 | POST | `/rcs/v1/agency/subCorp/brandReg` | mnt-api |
| 6.8 | 대행사 브랜드 동기화 | POST | `/rcs/v1/agency/brand/sync` | mnt-api |
| 6.9 | 대행사 양방향 청약 고객 목록 조회 | GET | `/rcs/v1/agency/bi/corpUnitList` | mnt-api |
| 6.10 | 대행사 양방향 청약 고객 등록 | POST | `/rcs/v1/agency/bi/corpUnit` | mnt-api |
| 6.11 | 대행사 양방향 청약 고객 삭제 | DELETE | `/rcs/v1/agency/bi/corpUnit/{regNo}` | mnt-api |
| 7.1 | 캠페인 메시지 발송/읽음확인 통계 조회 | POST | `/rcs/v1/statQuery/message/{brandId}` | mnt-api |
| 7.2 | 캠페인 메시지 버튼 클릭 통계 조회 | POST | `/rcs/v1/statQuery/messageButton/{brandId}` | mnt-api |
| 7.3 | 대화방 메뉴 클릭 통계 조회 | POST | `/rcs/v1/statQuery/persistentMenu/{brandId}` | mnt-api |

총 36개 API.

## 공통 개념

### 공통 헤더

| 헤더 | 필수 | 설명 |
|---|---|---|
| Authorization | ● | `Bearer {token}` 인증 토큰 |
| Content-Type | ● | `application/json;charset=UTF-8` |
| apiId | 일부 | RCS Biz Center 가입 시 등록한 ID, 최대 20자. 브랜드 API(3.x)와 대행사 API(6.1~6.8)의 헤더 표에 있음 |
| apiSecret | 일부 | RCS Biz Center 가입 시 발급된 clientSecret, 최대 18자. apiId 와 같은 API 에 필요 |
| brandKey | 일부 | 브랜드 Key(최대 18자). 챗봇 조회(4.1·4.2)와 템플릿 조회(5.5·5.6)는 헤더, 통계 API(7.x)는 쿼리 파라미터로 받는다 |

각 API 의 "인증" 줄에 어떤 헤더가 필요한지 적는다. 원문 헤더 표와 curl 예시가 서로 다른 곳이 있어(예: 3.2 는 표에 apiId/apiSecret, 설명 경로는 brandId 인데 예시는 BK 값) 해당 위치에 `원문 확인 필요`를 표시했다.

### 응답 래퍼의 차이

기본 래퍼는 `{code, message, data}` 이고 성공 코드는 대부분 `"10000"` 이다. 다만 예시에 다음이 섞여 있다.

- 3.1(브랜드 목록)은 `code: "100000"` 이고 `data` 대신 `result` + `pagination` 최상위 구조.
- 5.5·5.6·5.7·5.8 은 `code: "100000"`.
- 챗봇 목록·템플릿 목록은 `data.result[]` + `data.pagination`.
- 통계 API 는 `data` 안에 다시 `status`, `code`(`"20000000"`), `result[]` 가 있다.
- RCS Biz Center 쪽 실패는 `code: "21399"`, message `RCS Biz Center 처리 실패` 로 감싸고 `data.code`/`data.message` 에 원 오류를 담는다(4.6 예시).

> 원문 확인 필요: `10000` 과 `100000` 중 어느 쪽이 정식 성공 코드인지 원문에 정리돼 있지 않다. 원문 Appendix 의 "결과 코드"는 링크만 있어 이 변환본에 코드표가 없다.

### 페이징 파라미터 (offset/limit)

목록 조회 API 가 공통으로 쓴다. 둘 다 표에는 필수(●)로 되어 있고 String 타입이다.

| 이름 | 타입 | 필수 | 설명 |
|---|---|---|---|
| offset | String | ● | 시작 위치. 기본 0 |
| limit | String | ● | 조회 최대 건수. 기본 100, 최대 1000 |

응답의 `pagination` 은 `{total, offset, limit}`.

### 브랜드 객체 (목록 항목, 3.1)

| 필드 | 설명 |
|---|---|
| brandId | 브랜드 ID (`BR.` 로 시작) |
| brandName | 브랜드명 |
| agencyId | 대행사 ID |
| approvalStatus | 승인 상태. 예시 값 `approved` |
| chatbotDate / messagebaseDate | 챗봇·메시지베이스 최종 변경 시각 |
| regDt / updDt / approvalDt | 등록·수정·승인 시각 (ISO 8601 UTC 형태) |

### 브랜드 상세 객체 (3.2 응답 data[])

| 필드 | 설명 |
|---|---|
| brandId, name, brandKey | 브랜드 ID, 이름, 브랜드 Key |
| status | 상태 문자열 (예시 `검수완료`) |
| chatbotDate, messagebaseDate, registerDate, updateDate, approvalDate | 시각 (`2021-09-10T11:30:01.000+09` 형식) |
| mediaUrl[] | `fileId`, `fileName`, `url`, `typeName`(예 `profile`) |
| menus[] | `buttonType`, `weblink`, `feedinfoYn` |
| description, tel | 설명, 전화번호 |
| categoryId, categoryName, subCategoryId, subCategoryName, categoryOpt | 카테고리 정보, 검색 키워드 |
| zipCode, roadAddress, detailAddress, email, webSiteUrl | 주소·연락처 |
| approvalReason | 승인 사유 |

### 챗봇 객체 (4.x 응답)

| 필드 | 설명 |
|---|---|
| groupId | 그룹 ID (상세·수정 응답) |
| chatbotId | 챗봇(대화방) ID |
| brandId | 소속 브랜드 |
| isMainNum | 대표번호 여부. 목록은 `"Y"`, 상세는 불리언 `true` 로 예시가 다름 |
| subNum | 발신번호 |
| subTitle | 챗봇 이름 |
| service | 서비스 유형 (`a2p` 등) |
| display | 전시 설정 (`01` 기본, `00` 은 브랜드채널 노출·브랜드검색 불허·브랜드홈 비전시) |
| approvalResult | 승인 결과 (예시 `승인`) |
| registerDate, approvalDate, updateDate | 등록·승인·수정 시각 (`2023-05-15 14:30:45` 형식) |
| registerId, updateId | 등록자·수정자 |
| mediaUrl, approvalReason, status(`active`), rcsReply, searchWeight, webhook, botTcPage | 상세·수정 응답에만 있음 |

### 템플릿(메시지베이스) 객체 (목록, 5.3·5.5)

| 필드 | 설명 |
|---|---|
| groupId | 그룹 ID (null 가능) |
| messagebaseId | 템플릿(메시지베이스) ID. 브랜드 등록 템플릿은 `UBR.` 로 시작, 이통사 기본은 `OL…`·`CM…` 형태 |
| tmpltName | 템플릿명 |
| messagebaseformId | 템플릿 양식 ID |
| brandId | 브랜드 ID (이통사 기본은 `common`) |
| status | 상태. 예시 `ready` |
| approvalResult | 승인 결과 |
| approvalReason | 승인 사유 |
| registerDate, approvalDate, updateDate | 등록·승인·수정 시각 |
| registerId, updateId | 등록자·수정자 |

### 템플릿 상세 객체 (5.4·5.6 추가 필드)

| 필드 | 설명 |
|---|---|
| productCode | 상품 코드 (예 `mms`, `tmplt`) |
| spec | 규격 (`richcard`, `openrichcard`) |
| cardType | 카드 유형 (`carousel medium`, `description` 등) |
| agencyId, inputText, attribute[] | 대행사 ID, 입력 텍스트, 속성 태그 |
| guideInfo | `maxLineCount`, `maxDisplayText`, `maxDescriptionSize`, `imageWidth`, `imageHeight`, `detailInfo`(`summary`, `charactersPerLine{title,description,buttonName}`, `combinations[]{condition{mediaPhase,numberOfLinesOnTitle,numberOfButtons}, numberOfLinesOnDescription}`) |
| policyInfo (5.6) | `cardCount`, `maxMediaSize`, `maxTitleSize`, `maxButtonCount`, `maxDescriptionSize`, `adBodyAllowed`, `buttonsAllowed`, `adHeaderAllowed` |
| params[] (5.6) | `param`, `isMandatory`, `type`, `contentType`, `strSize`, `fileSize`, `strRegx`, `verification[]`, `imageWidth`, `imageHeight`, `couplingId`, `inputText`, `relationId` |
| formattedString (5.6) | 오픈리치카드 위젯 트리 `RCSMessage.openrichcardMessage{layout, suggestions, zoomAllowed, card}` + `trafficType`(예 `advertisement`) |

### 상태·승인 값

원문이 정식 enum 표를 주지 않는다. 예시와 설명에 나온 값만 모았다.

| 대상 | 값 | 의미·출처 |
|---|---|---|
| 템플릿 `approvalResult` | `승인` | 승인됨 (5.3·5.5·5.6 예시) |
| | `승인대기` | 검수 대기 (5.5 예시) |
| 템플릿 `approvalReason` | `승인완료`, null | 5.4·5.5 예시 |
| 템플릿 `status` | `ready` | 5.3~5.5 예시 |
| 템플릿 상태(5.10 설명) | `승인대기` | 취소하면 저장 상태로 변경 |
| | `승인대기(수정)` | 취소하면 직전 승인 상태·데이터로 롤백 |
| | `반려(수정)` | 취소하면 직전 승인 상태·데이터로 롤백 |
| | 그 외 | 취소 요청 시 에러 |
| 브랜드 `approvalStatus` (3.1) | `approved` | 예시 |
| 브랜드 `status` (3.2) | `검수완료` | 예시 |
| 챗봇 `approvalResult` | `승인` | 예시 |
| 챗봇 `status` | `active` | 예시 |
| 챗봇 `rcsReply` | `0` | SMS MO 수신 |
| | `1` | RCS Postback 수신 |
| 챗봇 `service` | `A2P`, `CHAT` | 서비스 유형 (응답 예시는 소문자 `a2p`) |
| 챗봇 `display` | `01` | 기본 |
| | `00` | 브랜드채널 노출, 브랜드검색 불허, 브랜드홈 비전시 |

> 원문 확인 필요: 위 표 외에 반려·삭제 등 다른 승인/검수 상태 값이 있는지, 상태 코드의 전체 목록은 원문에 없다. 템플릿 수정·삭제·챗봇 수정·삭제가 "승인 상태에 따라 처리 여부가 결정된다"고만 하고 어떤 상태에서 가능한지는 적혀 있지 않다.

### RCS 버튼(suggestions) 구조

템플릿 등록(5.7)의 `buttons` 와 템플릿 수정(5.8)의 `suggestions` 는 같은 `action` 구조를 쓴다. `buttons[].suggestions[].action` 에 `displayText`(버튼명), `postback.data`, 그리고 유형별 하위 객체가 들어간다.

| 버튼 유형 | postback.data | 유형별 하위 객체 |
|---|---|---|
| URL 링크 | `set_by_chatbot_open_url` | `urlAction.openUrl.url` |
| 복사하기 | `set_by_chatbot_copy_to_clipboard` | `clipboardAction.copyToClipboard.text` |
| 전화걸기 | `set_by_chatbot_dial_phone_number` | `dialerAction.dialPhoneNumber.phoneNumber` |
| 일정추가 | `set_by_chatbot_create_calendar_event` | `calendarAction.createCalendarEvent{title, description, startTime, endTime}` (시각은 ISO 8601 `…Z`) |
| 현재위치 공유 | `set_by_chatbot_request_location_push` | `mapAction.requestLocationPush` (빈 객체) |
| 지도(좌표) | `set_by_chatbot_show_location` | `mapAction.showLocation{fallbackUrl, location{latitude, longitude, label}}` |
| 지도(검색어) | `set_by_chatbot_search_locations` | `mapAction.showLocation{fallbackUrl, location{query}}` |

### 이미지 첨부 규격 (원문 Appendix)

RCS 공통: JPG, JPEG, PNG, BMP, GIF, 파일 크기 최대 1MB.

| 카드 유형 | 크기 |
|---|---|
| 이미지형(세로형) | 568x336px (권장) |
| 이미지형(이미지 강조) | 900x900px 또는 900x1200px (필수) |
| 썸네일형 | 이미지 900x560px (필수), 썸네일 이미지 300x300px (필수) |
| SNS형 | 900x900px (필수) |
| SNS형(중간버튼) | 900x560px (필수) |
| 슬라이드형(Small) | 360x336px (권장) / 360x1620px (최대) |
| 슬라이드형(Medium) | 696x504px (권장) / 696x1620px (최대) |

---

## 3. 브랜드 API

### 브랜드 목록 조회 (3.1)
`GET /rcs/v1/brand`
고객사에 등록된 모든 RCS 브랜드 목록을 조회한다.

**Headers**: `apiId`●, `apiSecret`● (공통 헤더 참조)

**Query**

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| offset | String | ● | | 기본 0 |
| limit | String | ● | | 기본 100, 최대 1000 |

**응답**: `result[]` 는 위 '브랜드 객체', 이어서 `pagination`.

```json
{ "code": "100000", "message": "성공",
  "result": [ { "brandId": "BR.q...5", "brandName": "테스트 브랜드", "agencyId": "AG.123456", "approvalStatus": "approved",
                "regDt": "2023-01-01T00:00:00Z" } ],
  "pagination": { "total": 1, "offset": 0, "limit": 100 } }
```

### 브랜드 상세 조회 (3.2)
`GET /rcs/v1/brand/{brandId}`
브랜드 ID 로 상세 정보를 조회한다.

**Headers**: `apiId`●, `apiSecret`●

**Path**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| brandId | String | ● | 브랜드 ID |

**응답**: `data[]` — 위 '브랜드 상세 객체'.

> 원문 확인 필요: curl 예시가 경로에 `brandId` 대신 `BK.…`(brandKey 형태) 값을 넣었다. 응답 `data` 는 배열로 표시된다.

### 브랜드 카테고리 조회 (3.3)
`GET /rcs/v1/brand/categories`
브랜드 등록에 쓸 카테고리 목록을 조회한다.

**Headers**: `apiId`●, `apiSecret`●

**응답 data[]**

| 필드 | 타입 | 설명 |
|---|---|---|
| categoryId | String | 카테고리 그룹 ID |
| categoryName | String | 카테고리 그룹 이름 |
| subCategories[] | Array | 하위 카테고리 |
| subCategories[].subCategoryId | String | 하위 카테고리 ID |
| subCategories[].subCategoryName | String | 하위 카테고리 이름 |

```json
{ "code": "10000", "message": "성공",
  "data": [ { "categoryId": "ITE", "categoryName": "IT",
              "subCategories": [ { "subCategoryId": "ITE001", "subCategoryName": "인터넷/컴퓨터" } ] } ] }
```

### 브랜드 등록 (3.4)
`POST /rcs/v1/brand`
새 RCS 브랜드를 등록한다.

**Headers**: `apiId`●, `apiSecret`●

**Body**

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| regBrand | Object | ● | | 브랜드 정보 (아래) |
| mainMdn | String | ● | | 대표 발신번호. `chatbots` 에 포함된 번호여야 함 |
| profileImgFilePath | String | ● | | 프로필 이미지 경로 |
| bgImgFilePath | String | | | 백그라운드 이미지 경로 |
| certiFilePath | String | | | 통신서비스이용증명원 파일 경로 |
| chatbots | Array | ● | | 등록할 챗봇(발신번호) 목록 |
| regBrand.name | String | ● | 최대 20자 | 브랜드 이름 |
| regBrand.description | String | ● | 최대 150자 | 브랜드 설명 |
| regBrand.tel | String | ● | 최대 12자 | 브랜드 전화번호 |
| regBrand.menus[] | Object | | | 메뉴. 최대 3개 등록(브랜드 홈에는 기본 chat 이 더해져 최대 4개 표시) |
| regBrand.menus[].buttonType | String | | 최대 20자 | 챗봇 버튼 타입 |
| regBrand.menus[].weblink | String | | 최대 128자 | `http://` 또는 `https://` 로 시작 |
| regBrand.categoryId | String | ● | | 카테고리 ID |
| regBrand.subCategoryId | String | ● | | 하위 카테고리 ID |
| regBrand.categoryOpt | String | | | 검색용 키워드 |
| regBrand.zipCode | String | | | 우편번호 |
| regBrand.roadAddress | String | | | 도로명 주소 |
| regBrand.detailAddress | String | | | 상세 주소 |
| regBrand.email | String | | | 이메일 |
| regBrand.webSiteUrl | String | | | 홈페이지 주소 |
| chatbots[].mdn | String | ● | | 등록할 발신번호 |
| chatbots[].rcsReply | String | ● | 1자 | `0` SMS MO 수신, `1` RCS Postback 수신 |
| chatbots[].subTitle | String | ● | | 챗봇 이름 |
| chatbots[].service | String | ● | | `A2P`/`CHAT` 서비스 유형 |
| chatbots[].display | String | | 2자 | 기본 `01`, `00` 은 브랜드채널 노출·검색 불허·홈 비전시 |

**응답**: `data.brandId` — 새 브랜드 ID.

```json
{ "regBrand": { "name": "브랜드명", "description": "브랜드설명", "tel": "0200000000",
                "categoryId": "ITE", "subCategoryId": "ITE001" },
  "mainMdn": "0200000000", "profileImgFilePath": "{프로필 이미지 경로}",
  "chatbots": [ { "mdn": "0200000000", "rcsReply": "1", "subTitle": "챗봇이름", "service": "A2P", "display": "01" } ] }
```

> 주의
> - 이미지·증명원은 파일 업로드가 아니라 경로 문자열로 전달한다. 경로를 얻는 방법은 원문에 없다.
> - `menus` 는 표에 Object 로 되어 있으나 예시는 배열이다.

### 브랜드 수정 (3.5)
`PUT /rcs/v1/brand/{brandId}`
기존 브랜드 정보를 수정한다.

**Headers**: `apiId`●, `apiSecret`●. **Path**: `brandId`●.

**Body**: 등록(3.4)과 같은 `regBrand`·`mainMdn`·`profileImgFilePath`·`bgImgFilePath` 구조. 수정에는 `certiFilePath`·`chatbots` 가 표에 없다. `regBrand` 하위 필드와 길이 제한은 등록과 동일.

**응답**: `{"code":"10000","message":"OK"}`

> 원문 확인 필요: 수정 가능 조건(승인 상태 등)은 적혀 있지 않다.

### 브랜드 삭제 (3.6)
`DELETE /rcs/v1/brand/{brandId}`
브랜드를 삭제한다.

**Headers**: `apiId`●, `apiSecret`●. **Path**: `brandId`●.
**응답**: `{"code":"10000","message":"성공"}`

---

## 4. 챗봇 API

### 챗봇 리스트 조회 (4.1)
`GET /rcs/v1/brand/{brandId}/chatbot`
브랜드에 등록된 챗봇 목록을 조회한다.

**Headers**: `brandKey`●. **Path**: `brandId`●(최대 13자). **Query**: offset●, limit●.
**응답**: `data.result[]`(챗봇 객체 목록 형태: `chatbotId`, `brandId`, `isMainNum`, `subNum`, `subTitle`, `service`, `display`, `approvalResult`, `registerDate`, `approvalDate`, `updateDate`, `registerId`, `updateId`), `data.pagination`.

### 챗봇 상세 조회 (4.2)
`GET /rcs/v1/brand/{brandId}/chatbot/{chatbotId}`
챗봇 하나의 상세 정보를 조회한다.

**Headers**: `brandKey`●(최대 18자). **Path**: `brandId`●(최대 13자), `chatbotId`●.
**응답**: `data[]` — '챗봇 객체' 전체 필드, `meta`.

> 원문 확인 필요: 원문의 기능 설명이 챗봇 등록 설명 문장을 그대로 붙여넣은 것으로 보인다.

### 챗봇 등록 요청 (4.3)
`POST /rcs/v1/brand/{brandId}/chatbot`
브랜드에 챗봇(발신번호)을 등록 요청한다.

**Path**: `brandId`●(최대 13자).

**Body**

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| subNumCertificate | String | ● | 최대 20MB | 통신서비스이용증명원 파일 경로 |
| chatbots | Object | ● | | 챗봇 정보 (아래) |
| chatbots.mdn | String | ● | 최대 40자 | 등록할 발신번호 |
| chatbots.rcsReply | String | ● | 1자 | `0` SMS MO 수신, `1` RCS Postback 수신 |
| chatbots.subTitle | String | ● | 최대 20자 | 챗봇 이름 |
| chatbots.service | String | ● | 최대 4자 | `A2P`/`CHAT` |
| chatbots.display | String | | 2자 | 기본 `01`, `00` 은 브랜드채널 노출·검색 불허·홈 비전시 |

**응답**: `data[]` 에 챗봇 객체(`groupId`, `chatbotId`, `brandId`, `subNum`, `isMainNum`, `subTitle`, `service`, `display`, `approvalResult`, `registerDate`, `approvalDate`, `updateDate`, `registerId`, `updateId`), `meta`.

```json
{ "subNumCertificate": "{증명원 파일 경로}",
  "chatbots": [ { "mdn": "0200000000", "rcsReply": "1", "subTitle": "챗봇이름", "service": "a2p", "display": "01" } ] }
```

> 주의
> - 등록 후 브랜드포털 관리자의 승인을 받아야 사용할 수 있다.
> - 표는 `chatbots` 를 Object 로 쓰지만 예시는 배열이다. 예시에 Authorization 외 헤더가 없다.

### 챗봇 수정 요청 (4.4)
`PUT /rcs/v1/brand/{brandId}/chatbot/{chatbotId}`
챗봇 정보를 수정 요청한다. 처리 여부는 승인 상태에 따라 결정된다.

**Path**: `brandId`●(최대 13자), `chatbotId`●.
**Body**: 4.3 과 같은 필드(`subNumCertificate`, `chatbots.mdn/rcsReply/subTitle/service/display`, 길이 동일). 원문 표는 `subNumCertificate` 를 Object, `chatbots` 를 String 으로 적었는데 4.3 과 반대여서 오기로 보인다.
**응답**: `data[]` — '챗봇 객체' 상세 필드 전체.

> 원문 확인 필요: 타입 표기 불일치(위), 수정 가능한 승인 상태 목록.

### 챗봇 삭제 요청 (4.5)
`DELETE /rcs/v1/brand/{brandId}/chatbot/{chatbotId}`
챗봇을 삭제 요청한다. 처리 여부는 승인 상태에 따라 결정된다.

**Path**: `brandId`●(최대 13자), `chatbotId`●.
**응답**: `{"code":"10000","message":"성공","data":{}}`

### 대화방ID 등록 가능 여부 조회 (4.6)
`GET /rcs/v1/usableQuery/chatbotId/{chatbotId}`
대화방(챗봇) ID 를 등록할 수 있는지 확인한다. 가능하면 200 OK, 형식이 틀렸거나 이미 등록된 ID 면 400 에러가 온다.

**Path**: `chatbotId`●.

```json
{ "code": "10000", "message": "성공",
  "data": { "httpStatus": "OK", "status": "200", "code": "20000000", "desc": "registration available",
            "result": { "chatbotId": "11...47" } } }
```
등록 불가 예:
```json
{ "code": "21399", "message": "RCS Biz Center 처리 실패",
  "data": { "code": "64348", "message": "1....3 is already registered." } }
```

> 원문 확인 필요: curl 예시 경로가 `/rcs/v1/rcs/v1/usableQuery/...` 로 중복돼 있다. 표의 경로 `/rcs/v1/usableQuery/chatbotId/{chatbotId}` 를 따랐다.

---

## 5. 템플릿 API

### 템플릿 양식 목록 조회 (5.1)
`GET /rcs/v1/messagebase/messagebaseform`
템플릿 양식 목록을 조회한다.

**Query**: offset●, limit●.
**응답** `data.result[]`

| 필드 | 설명 |
|---|---|
| messagebaseformId | 양식 ID (예 `CLT00004`) |
| formName | 양식명 |
| cardType | 카드 유형 (예 `descriptionNew`) |
| bizCondition[], bizCategory, bizService | 업종 조건·카테고리·서비스 (null 가능) |
| registerDate, updateDate | 등록·수정 시각 |

### 템플릿 유형 상세 조회 (5.2)
`GET /rcs/v1/messagebase/messagebaseform/{messagebaseformId}`
양식 상세를 조회한다. 응답의 `formattedString`(가이드 정보)을 이용해 브랜드용 템플릿을 작성한다.

**Query**: offset●, limit●. (Path 의 `messagebaseformId` 는 경로에 포함, 원문 표에는 없음)
**응답** `data[]`: 5.1 의 필드 + `mediaUrl[]`(`fileId`, `fileName`, `url`, `typeName`), `productCode`(`tmplt`), `spec`(`openrichcard`), `guideInfo{…}`.

> 원문 확인 필요: curl 예시 경로가 `/rcs/v1/messagebaseform/…` 로 표의 경로와 다르다.

### 이통사 기본 템플릿 목록 조회 (5.3)
`GET /rcs/v1/messagebase/common`
이통사가 기본 제공하는 템플릿을 조회한다.

**Query**(예시): offset, limit. 원문 표에는 Path Parameter `messagebaseformId●` 만 적혀 있으나 경로에는 변수가 없고 curl 은 offset/limit 을 쓴다.
**응답** `data.result[]` — '템플릿 객체'(`brandId` 는 `common`).

### 이통사 기본 템플릿 상세 조회 (5.4)
`GET /rcs/v1/messagebase/common/{messagebaseId}`
이통사 기본 리치카드별 상세를 조회한다. **Path**: 원문 표에는 `messagebaseformId●(템플릿 유형 ID)` 로 적혀 있으나 경로 변수는 `{messagebaseId}` 이다.
**응답** `data[]` — '템플릿 객체' + '템플릿 상세 객체'(`productCode`, `spec`, `cardType`, `guideInfo` 등).

> 원문 확인 필요: 5.3·5.4 의 파라미터 표가 경로와 맞지 않는다.

### 템플릿 리스트 조회 (5.5)
`GET /rcs/v1/brand/{brandId}/messagebase`
브랜드에 등록된 메시지베이스 목록을 조회한다.

**Headers**: `brandKey`●(최대 18자). **Path**: `brandId`●(최대 13자). **Query**: offset●, limit●.
**응답**: `data.result[]` '템플릿 객체', `data.pagination`.

### 템플릿 상세 조회 (5.6)
`GET /rcs/v1/brand/{brandId}/messagebase/{messagebaseId}`
등록된 메시지베이스 하나의 상세를 조회한다.

**Headers**: `brandKey`●(최대 18자). **Path**: `brandId`●(최대 13자), `messagebaseId`●.
**응답** `data[]`: '템플릿 객체' + '템플릿 상세 객체'(`guideInfo`, `policyInfo`, `params[]`, `formattedString`).

### 템플릿 등록 요청 (5.7)
`POST /rcs/v1.1/{brandId}/messagebase`
오픈리치카드 템플릿(메시지베이스)을 등록한다. 경로 버전이 `v1.1` 인 점에 주의.

**Path**: `brandId`●(최대 13자).

**Body**

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| messagebaseformId | String | ● | 최대 10자 | 템플릿 양식 ID |
| custTmpltId | String | ● | 최대 25자 | 사용자 지정 템플릿 ID. 영문/숫자만 |
| tmpltName | String | ● | 최대 40자 | 템플릿명 |
| brandId | String | ● | 최대 13자 | 브랜드 ID |
| agencyId | String | | 최대 20자 | 대행사 ID |
| formattedString | Object | ● | | 오픈리치카드 Widget 속성 객체 |
| body[] | Array | | | 예시에서 쓰는 파라미터 목록 `{param, value}` |
| buttons[] | Array | | | 예시에서 쓰는 버튼 목록 (공통 개념의 버튼 구조) |

**양식별 `body` 파라미터** (예시 기준, `media*` 값은 `maapfile://…` 형태의 업로드 파일 참조)

| 양식 | messagebaseformId | body.param |
|---|---|---|
| 이미지 강조형 | `ITHIMS` | `description`, `title`, `media` |
| 썸네일 세로형 | `ITTBNV` | `media`, `title`, `description`, `subDesc1~3`, `subMedia1~3` |
| 썸네일 가로형 | `ITTBNH` | `media`, `title`, `description`, `subMedia1~3` |
| 이미지&타이틀 강조형 | `ITHITS`(이미지 1:1) / `ITHITV`(이미지 3:4) | `media`, `title`, `subTitle1~3`, `subDesc1~3` |
| SNS형 | `ITSNSH`(중간버튼형) / `ITSNSS`(하단버튼형) | `media`, `title`, `description` |
| 슬라이드형 | `ITCRM2` ~ `ITCRM6` (슬라이드 개수에 맞춤) | `media1~N`, `title1~N`, `description1~N` |

본문 문구에 `{{고객}}` 처럼 이중 중괄호 치환 변수를 쓸 수 있다(예시).

```json
{ "messagebaseformId": "ITHIMS", "tmpltName": "템플릿명", "brandId": "BR.W.....D",
  "custTmpltId": "Test0001", "agencyId": "uplus",
  "body": [ { "param": "description", "value": "{{고객}}님 RCS 테스트 발송입니다." },
            { "param": "title", "value": "제목입력" },
            { "param": "media", "value": "maapfile://LT-BR.W.....2" } ],
  "buttons": [ { "suggestions": [ { "action": { "displayText": "URL 링크 버튼명",
                 "postback": { "data": "set_by_chatbot_open_url" },
                 "urlAction": { "openUrl": { "url": "https://www.naver.com/" } } } } ] } ] }
```
**응답**: `{"code":"100000","message":"성공"}`

> 주의
> - 한 번 삭제한 템플릿은 같은 ID 로 다시 만들 수 없다(5.9 참조).
> - 등록 후 승인 절차를 거치는 것으로 보이나 원문에 명시되지 않았다.
> - 원문 확인 필요: 요청 표에는 `formattedString` 이 필수인데 실제 curl 예시는 `body`/`buttons` 구조를 쓰고 `formattedString` 이 없다. 두 방식의 관계는 설명이 없다.

### 템플릿 수정 요청 (5.8)
`PUT /rcs/v1/brand/{brandId}/messagebase/{messagebaseId}`
템플릿을 수정한다. 처리 여부는 승인 상태에 따라 결정된다.

**Path**: `brandId`●(최대 13자), `messagebaseId`●.
**Body**: 5.7 과 같은 필드(`messagebaseformId`●, `custTmpltId`●, `tmpltName`●, `brandId`●, `agencyId`, `formattedString`●). 예시는 `formattedString.RCSMessage{trafficType, openrichcardMessage{card, layout, suggestions, zoomAllowed}}` 를 직접 보낸다.

```json
{ "messagebaseformId": "EE001D", "custTmpltId": "TEST0001", "tmpltName": "TEST0001 수정", "brandId": "BR.v...h",
  "agencyId": "uplus",
  "formattedString": { "RCSMessage": { "trafficType": "advertisement",
    "openrichcardMessage": { "card": "open_rich_card", "zoomAllowed": true,
      "layout": { "widget": "LinearLayout", "orientation": "vertical", "width": "284dp", "height": "content", "children": [] },
      "suggestions": [] } } } }
```
> 원문 확인 필요: 응답 예시가 템플릿이 아니라 브랜드 목록 응답(`brandId`, `brandName`, `pagination`…)을 그대로 붙인 것으로 보인다. 실제 성공 응답 형태 확인 필요.

### 템플릿 삭제 요청 (5.9)
`DELETE /rcs/v1/brand/{brandId}/messagebase/{messagebaseId}`
템플릿을 삭제한다. 처리 여부는 승인 상태에 따라 결정된다.

**Path**: `brandId`●(최대 13자), `messagebaseId`●. **응답**: `{"code":"10000","message":"성공"}`

> 주의: 삭제된 템플릿은 복원할 수 없고 같은 ID 로 다시 생성할 수 없다.

### 템플릿 승인 요청 취소 (5.10)
`PUT /rcs/v1/brand/{brandId}/messagebase/{messagebaseId}/cancel`
진행 중인 승인 요청을 취소한다.

**Path**: `brandId`●(최대 13자), `messagebaseId`●. **응답**: `{"code":"10000","message":"성공"}`

> 주의: 상태별 동작은 공통 개념의 '상태·승인 값' 표 참고(`승인대기`→저장 상태, `승인대기(수정)`·`반려(수정)`→직전 승인 상태로 롤백, 그 외 에러).

---

## 6. 대행사 API

6.1~6.8 은 `apiId`/`apiSecret` 헤더(●)가 표에 있고, 6.9~6.11 은 헤더 표 없이 Authorization 만 예시에 있다.

### 대행사 하위 고객사 프로젝트 목록 조회 (6.1)
`POST /rcs/v1/agency/brand/project`
계약된 고객사의 프로젝트 목록을 조회한다. 파라미터를 쿼리로 보낸다.

**Query**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| agencyId | String | ● | 대행사 ID |
| regnos | Array | ● | 조회 대상 고객사 사업자등록번호 목록 |

**응답** `data.result[]`: `corpId`, `corpRegNum`, `brandId`, `brandName`, `agencyId`, `contracts[]`, `registerDate`, `updateDate`, `brandDate`, `chatbotDate`, `messagebaseDate`.

### 대행사 하위 고객사 프로젝트 연결 (6.2)
`POST /rcs/v1/agency/subCorp/subBrandProjectReg`
고객사 프로젝트에 브랜드를 연결한다. 쿼리 파라미터를 쓴다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| projectId | String | ● | 연결할 프로젝트 ID |
| corpId | String | ● | 연결할 회사 ID |
| userId | String | ● | 연결 등록자 ID |
| subBrands | Array | ● | 연결할 브랜드 ID 목록 |

**응답**: `{"code":"10000","message":"성공"}`
> 원문 확인 필요: 기능 설명이 6.1 과 같은 문장(프로젝트 목록 조회)이라 오기로 보인다.

### 대행사 하위 브랜드 조회 (6.3)
`GET /rcs/v1/agency/{agencyId}/corp/{corpRegNum}/brand`
계약된 브랜드를 기업 단위로 조회한다.

**Path**: `agencyId`●, `corpRegNum`●(사업자등록번호 10자리). **Query**: offset●, limit●.
**응답** `data.result[]`: 6.1 과 같은 필드.

### 대행사 하위 브랜드 상세 조회 (6.4)
`GET /rcs/v1/agency/{agencyId}/brand/{brandId}`
하위 브랜드 상세를 조회한다. **Path**: `agencyId`●, `brandId`●.
**응답** `data[]`: `categoryId`, `categoryName`, `subCategories[]{subCategoryId, subCategoryName}`, `updateDate`, `meta`.
> 원문 확인 필요: 응답 예시가 브랜드 상세가 아닌 카테고리 구조로 보인다.

### 대행사 하위고객 브랜드 수신 등록 목록 조회 (6.5)
`POST /rcs/v1/agency/subCorp/brandRegList`

| 필드(Query) | 타입 | 필수 | 설명 |
|---|---|---|---|
| regno | String | ● | 사업자번호 |
| brandId | String | | 브랜드 ID |

**응답** `data[]`: `regno`, `brandId`, `regId`(등록자 ID), `regDt`(등록일자).

### 대행사 하위고객 브랜드 수신 등록 설정/해제 (6.6)
`POST /rcs/v1/agency/subCorp/brand`

| 필드(Query) | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| confYn | String | ● | 1자 | 수신 제외 브랜드 등록/삭제 (`Y` 등록, `N` 삭제) |

**응답**: `data: {}`. > 원문 확인 필요: 대상 브랜드를 지정하는 파라미터가 표에 없다.

### 대행사 하위고객 브랜드 수신 등록/제외 (6.7)
`POST /rcs/v1/agency/subCorp/brandReg`

| 필드(Query) | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| subBrandsReg | String | ● | 1자 | 수신 제외 브랜드 등록/삭제 (`Y` 등록, `N` 삭제) |
| subBrands | Array | ● | | 하위 브랜드 목록 |

**응답**: `data: {}`. > 원문 확인 필요: 기능 설명이 6.6 과 같은 문장이다. 6.6 과의 차이는 원문에 없다.

### 대행사 브랜드 동기화 (6.8)
`POST /rcs/v1/agency/brand/sync`
대행사 브랜드·메시지베이스·챗봇의 동기화를 요청한다. 요청 파라미터 없음. **응답**: `data: {}`.

### 대행사 양방향 청약 고객 목록 조회 (6.9)
`GET /rcs/v1/agency/bi/corpUnitList`
파라미터 없음. **응답** `data[]`: `regNo`(사업자번호), `corpName`(회사명), `regDate`(등록일시).

### 대행사 양방향 청약 고객 등록 (6.10)
`POST /rcs/v1/agency/bi/corpUnit`

| 필드(Body) | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| regNo | String | ● | 최대 20자 | 사업자번호 |
| corpName | String | ● | 최대 50자 | 사업자명 |

**응답**: `{"code":"10000","message":"성공","data":{},"meta":{}}`

### 대행사 양방향 청약 고객 삭제 (6.11)
`DELETE /rcs/v1/agency/bi/corpUnit/{regNo}`
**Path**: `regNo`●(최대 20자, 사업자번호). **응답**: 6.10 과 같다.

---

## 7. 고객반응 통계 API

세 API 모두 POST 이고 입력은 쿼리 파라미터다. 집계 기준은 다음과 같다.

- 7.1·7.2: 같은 Group ID 에 대해 발송일 기준 3일간(D+3) 집계. 이통사별 발송 성공 건수가 100건 이상인 경우만 집계.
- 7.3: 대화방별로 사용자 선택이 1건 이상 있었던 경우만 집계.
- 조회 기간: 데이터가 있으면 최근 1년 6개월 이내에서 최대 31일.

공통 요청 필드 (7.1~7.3, Path `brandId`●(최대 13자))

| 필드(Query) | 타입 | 필수 | 설명 |
|---|---|---|---|
| brandKey | String | ● | RCS Biz Center 에서 브랜드 등록 시 자동 생성되는 Key |
| startDate | String | ● | 요청 시작일자 (예 `20250501`) |
| endDate | String | ● | 요청 종료일자 (예 `20250530`) |
| campaignId | String | ●(7.1·7.2) | 발송 캠페인 구분 ID. 7.3 에는 없음 |
| chatbotId | String | | 대화방 ID |

### 캠페인 메시지 발송/읽음확인 통계 조회 (7.1)
`POST /rcs/v1/statQuery/message/{brandId}`
**응답** `data{status, code, result[]}`, `result[]`: `statDate`, `corpId`, `corpRegNum`, `brandId`, `chatbotId`, `groupId`(발송 캠페인 구분 ID), `deliveredCount`(발송 건수), `displayedCount`(읽음확인 건수).

### 캠페인 메시지 버튼 클릭 통계 조회 (7.2)
`POST /rcs/v1/statQuery/messageButton/{brandId}`
**응답** `result[]`: `statDate`, `corpId`, `corpRegNum`, `brandId`, `chatbotId`, `groupId`, `buttonList[]{buttonType, buttonName, clickCount}`.
> 원문 확인 필요: curl 예시 경로가 `/statQuery/message/…`(7.1 경로)로 되어 있다. 표의 경로를 따랐다.

### 대화방 메뉴 클릭 통계 조회 (7.3)
`POST /rcs/v1/statQuery/persistentMenu/{brandId}`
**응답** `result[]`: `statDate`, `corpId`, `corpRegNum`, `brandId`, `chatbotId`, `menuList[]`.

| menuList 필드 | 설명 |
|---|---|
| postbackId | 메뉴 postback ID |
| menuType | `action`, `reply`, `autoreply`, `menu` |
| actionType | menuType 이 `action` 일 때 액션 유형 (예 `urlAction`) |
| title | 메뉴명 |
| clickCount | 클릭수 |
| subList[] | 하위 메뉴. 같은 구조 + `subActionList[]{postbackId, actionType, title, clickCount}` |
