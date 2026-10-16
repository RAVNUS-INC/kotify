# 2.5 Push 메시지
> 원문: https://doc.msghub.uplus.co.kr/rest-api/02메시지발송/0205push/ · 확인일 2026-10-16

iOS/Android 앱 푸시를 발송한다. 푸시 실패 시 SMS/MMS 로 대체발송(fallback) 할 수 있다.

## 한눈에 보기

| 기능 | Method | 경로 | 호스트 |
|---|---|---|---|
| Push 발송 | POST | `/push/v1` | api-send |

## Push 발송

`POST /push/v1` — 앱 ID(appId)와 수신자(cuid/phone)를 지정해 푸시를 보낸다. serviceCode 가 `A`(전체 발송)이면 수신자 목록을 생략할 수 있다.

요청 Header

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| Authorization | String | ● | `Bearer {token}` |
| Content-Type | String | ● | application/json |

요청 Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| clickUrlYn | String | - | 1 | 단축URL 사용 여부(Y/N) |
| resvYn | String | - | 1 | 예약발송 여부(Y/N) |
| resvReqDt | String | - | - | 예약발송 시각 |
| agency | Object | - | - | 대행사 정보 |
| callback | String | - | 20 | 발신번호(fallback 용) |
| campaignId | String | - | 20 | 캠페인 ID |
| deptCode | String | - | 20 | 부서 코드 |
| msg | Object | ● | - | 푸시 메시지(아래 msg 객체) |
| msg.title | String | ● | - | 푸시 제목 |
| msg.body | String | ● | - | 푸시 내용 |
| appId | String | ● | 255 | 앱 아이디 |
| ext | Object | - | 1000B | 앱에서 처리할 확장 커스텀 데이터(키-값 문자열) |
| fileId | String | - | 20 | 파일 ID(이미지 등) |
| serviceCode | String | - | - | PUSH 발송 타입. `A` = 전체 발송 |
| recvInfoLst | Array | ● | 10개 | 수신자 목록(serviceCode=A 이면 생략 가능) |
| fbInfoLst | Array | - | - | 대체발송 목록 |

### recvInfoLst[] 객체

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| cliKey | String | ● | 30 | 클라이언트 키 |
| phone | String | ● | 20 | 수신번호. 국제문자 발송 시 맨 앞의 `0` 제외 |
| cuid | String | - | 50 | 푸시 사용자 아이디 |
| mergeData | Object | - | - | 채널별 개별화 머지 데이터 |
| userCustomFields | Object | - | - | 사용자 정의 필드 |

### fbInfoLst[] 객체

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| ch | String | ● | 대체 채널 |
| title | String | - | 제목. MMS 이면 필수 |
| msg | String | ● | 메시지 |
| fileId | String | - | 파일 ID. fileId 와 fileIdLst 중 하나만 |
| fileIdLst | Array | - | 파일 ID 목록(최대 3개) |

agency 객체는 `kisaOrigCode`(재판매사 KISA 최초식별코드, 선택) 하나다.

응답 data[] (수신자별)

| 필드 | 타입 | 설명 |
|---|---|---|
| cliKey | String | 클라이언트 키 |
| msgKey | String | 메시지 키 |
| phone | String | 수신번호 |
| code | String | 결과 코드 |
| message | String | 결과 메시지 |

예약발송이면 `data` 가 `{ "regDt": "...", "webReqId": "..." }` 객체로 온다.

예시

```json
{
  "callback": "0200000000",
  "msg": { "title": "서비스 알림", "body": "안녕하세요. #{name} 고객님, 사용량(#{usage}) 초과입니다." },
  "appId": "APP_ID_EXAMPLE",
  "ext": { "type": "usage_alert", "limit": "1000" },
  "recvInfoLst": [
    { "cliKey": "test001", "cuid": "user123", "phone": "01000000000",
      "mergeData": { "name": "홍길동", "usage": "1,000건" } }
  ],
  "fbInfoLst": [ { "ch": "SMS", "msg": "서비스 알림. 사용량 초과입니다." } ]
}
```

> 주의
> - 동보발송은 1건에 최대 10명, TPS 는 수신자 수 기준(5명이면 TPS 5).
> - 예약발송은 현재 시점부터 최대 30일. 단축URL 사용 시 메시지 길이가 제한될 수 있다.
> - fallback 대체발송을 쓰려면 발신번호(callback)가 필수다. callback 은 필수 열이 `-` 로 되어 있지만 fallback 시에는 반드시 넣는다.
> - ext 는 앱이 해석하는 커스텀 데이터이며 최대 1000B.
> - 원문 확인 필요: serviceCode 의 허용값은 `A`(전체 발송)만 본문에 언급되며 다른 값 목록은 없다.
> - 원문 확인 필요: ext 객체 표는 `key`/`value` 두 필드로 적혀 있으나 예시는 임의 키-값을 직접 나열한다. 예시 형태를 따랐다.
> - 원문 확인 필요: 원문 예시의 JSON 에 쉼표 누락이 있고, 응답 예시의 phone 이 `00000000000` 으로 되어 있다.
> - 원문 확인 필요: fbInfoLst 의 ch 허용값은 이 페이지에 명시가 없다(푸시 대체발송 채널이 SMS/MMS 로 한정되는지 불명).
