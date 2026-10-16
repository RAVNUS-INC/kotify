# 5.3 반응형 URL (단축 URL)
> 원문: https://doc.msghub.uplus.co.kr/rest-api/05부가서비스/0503shorturl/ · 확인일 2026-10-16

## 한눈에 보기

원문 제목은 "반응형 URL". 메시지에 넣을 추적용 URL 을 만들고 클릭 통계를 본다. 모두 api 호스트.

| 기능 | Method | 경로 | 호스트 |
|---|---|---|---|
| 반응형 URL 생성 | POST | `/msg/v1/createClickUrl` | api |
| 반응형 URL 삭제 | POST | `/msg/v1/deleteClickUrl` | api |
| 반응형 URL 목록 조회 | GET | `/msg/v1/getClickUrl` | api |
| 반응형 URL 통계 | POST | `/msg/v1/stat/url/msg` | api |
| 유입채널별 통계 | POST | `/msg/v1/stat/url/channel` | api |
| 클릭 수신자별 통계 | POST | `/msg/v1/stat/url/receiver` | api |
| 타임라인: 발송 기준 일별 | POST | `/msg/v1/stat/url/sendDay` | api |
| 타임라인: 발송 기준 시간별 | POST | `/msg/v1/stat/url/sendHour` | api |
| 타임라인: 클릭 기준 일별 | POST | `/msg/v1/stat/url/clickDay` | api |
| 타임라인: 클릭 기준 시간별 | POST | `/msg/v1/stat/url/clickHour` | api |

공통 Header: `Authorization`(●, 사용자 인증 토큰), `Content-Type: application/json`(●). 목록 조회는 `Authorization` 만 표기.

## 반응형 URL 생성

`POST /msg/v1/createClickUrl`

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| urlTitle | String | ● | - | 반응형 URL 제목 |
| orgUrl | String | ● | - | 원본 URL (`http://` 또는 `https://` 로 시작) |
| expDt | String | ● | - | 만료일 `YYYY-MM-DD HH:mm:ss` |

요청 예시

```json
{ "urlTitle": "봄맞이 프로모션", "orgUrl": "https://example.com/promotion/spring", "expDt": "2026-12-31 23:59:59" }
```

응답 예시

```json
{ "code": "10000", "message": "성공", "data": 1 }
```

> 주의
> - 만료일이 지나면 자동 비활성화된다.
> - 제목은 식별하기 쉬운 이름을 쓰라는 권고가 있다.
> - 원문 확인 필요: 응답 표는 `code`·`message` 만 적지만 예시는 `data: 1` 이다. 생성된 `urlId` 가 응답에 오지 않으므로, ID 는 목록 조회로 확인해야 하는 것으로 보인다.

## 반응형 URL 삭제

`POST /msg/v1/deleteClickUrl`

| 구분 | 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|---|
| Query | urlId | String | ● | 반응형 URL ID |

요청 예시

```
POST https://api.msghub.uplus.co.kr/msg/v1/deleteClickUrl?urlId=URL_ID_EXAMPLE
```

응답 예시

```json
{ "code": "10000", "message": "성공", "data": 0 }
```

> 주의
> - 복구할 수 없다.
> - 이미 발송된 메시지에 들어간 URL 은 삭제해도 계속 동작한다.
> - 원문 확인 필요: 응답 표는 `data` 를 "빈 객체"로 적지만 예시는 `0` 이다.

## 반응형 URL 목록 조회

`GET /msg/v1/getClickUrl`

| 구분 | 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|---|
| Query | page | Integer | ● | 페이지 번호 (1부터) |

응답 data[] (표에는 `data.` 로 적혀 있으나 예시는 배열)

| 필드 | 타입 | 설명 |
|---|---|---|
| no | Integer | 번호 |
| title | String | 반응형 URL 제목 |
| urlId | String | 반응형 URL ID |
| orgUrl | String | 원본 URL |
| expDt | String | 만료일 |
| regDt | String | 등록일 |

응답 예시

```json
{ "code": "10000", "message": "성공",
  "data": [ { "no": 1, "title": "테스트", "urlId": "URL_ID_EXAMPLE", "orgUrl": "https://example.com",
              "expDt": "2026-12-31 23:59:59", "regDt": "2026-10-01 11:12:26" } ] }
```

> 주의
> - 한 페이지에 최대 100건.
> - 만료된 URL 은 포함, 삭제된 URL 은 제외.

## 반응형 URL 통계

`POST /msg/v1/stat/url/msg`

URL 별 발송 건수·클릭 건수·클릭률.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| from | String | ● | 조회 시작일 `YYYY-MM-DD` |
| to | String | ● | 조회 종료일 `YYYY-MM-DD` |
| urlId | String | - | 반응형 URL ID |
| title | String | - | 반응형 URL 제목 |
| orgUrl | String | - | 원본 URL |

응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| urlId | String | 반응형 URL ID |
| title | String | 제목 |
| orgUrl | String | 원본 URL |
| regDt | String | 등록일 |
| totCnt | String | 총 발송 건수 |
| conCnt | String | 총 클릭 건수 |
| clickThroughRate | String | 클릭률 (%) |

```json
{ "code": "10000", "message": "성공",
  "data": { "urlId": "URL_ID_EXAMPLE", "title": "봄맞이 프로모션", "orgUrl": "https://example.com/promotion/spring",
            "regDt": "2026-01-01", "totCnt": "1000", "conCnt": "350", "clickThroughRate": "35.0" } }
```

> 주의
> - 조회 기간 최대 31일, 등록일 기준.
> - `urlId`, `title`, `orgUrl` 중 하나 이상을 조건으로 줄 수 있다.
> - 원문 확인 필요: 여러 URL 이 조건에 걸릴 때 `data` 가 배열인지(예시는 단일 객체).

## 유입채널별 통계

`POST /msg/v1/stat/url/channel`

채널(SMS, MMS, RCS 등)별 발송·클릭 현황.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| from | String | ● | 조회 시작일 `YYYY-MM-DD` |
| to | String | ● | 조회 종료일 `YYYY-MM-DD` |
| urlId | String | ● | 반응형 URL ID |

응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| ch | String | 채널 |
| totCnt | String | 총 발송 건수 |
| conCnt | String | 총 클릭 건수 |
| clickThroughRate | String | 클릭률 (%) |

```json
{ "code": "10000", "message": "성공", "data": { "ch": "SMS", "totCnt": "1000", "conCnt": "350", "clickThroughRate": "35.0" } }
```

> 주의
> - 조회 기간 최대 31일, 발송일 기준. `urlId` 필수.
> - 원문 확인 필요: 채널이 여럿이면 `data` 가 배열일지(예시는 단일 객체).

## 클릭 수신자별 통계

`POST /msg/v1/stat/url/receiver`

URL 을 클릭한 수신자별 상세(클릭 시각·채널·단말).

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| from | String | ● | 조회 시작일 `YYYY-MM-DD` |
| to | String | ● | 조회 종료일 `YYYY-MM-DD` |
| urlId | String | ● | 반응형 URL ID |
| phone | String | - | 특정 수신자만 조회 |
| page | Integer | ● | 페이지 번호 |

응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| urlId | String | 반응형 URL ID |
| totCnt | Integer | 총 클릭 건수 |
| recvlst[].conYmd | String | 클릭 일시 (예시: `2024-01-25T14:30:00.000Z`) |
| recvlst[].urlId | String | 반응형 URL ID |
| recvlst[].phone | String | 수신자 전화번호 |
| recvlst[].sndYmd | String | 발송 일시 (예시 형식 동일) |
| recvlst[].ch | String | 채널 |
| recvlst[].isMobile | String | 모바일 여부 (Y/N) |

```json
{ "code": "10000", "message": "성공",
  "data": { "urlId": "URL_ID_EXAMPLE", "totCnt": 150,
            "recvlst": [ { "conYmd": "2024-01-25T14:30:00.000Z", "urlId": "URL_ID_EXAMPLE",
                           "phone": "01000000000", "sndYmd": "2024-01-25T10:30:00.000Z",
                           "ch": "SMS", "isMobile": "Y" } ] } }
```

> 주의
> - 조회 기간 최대 31일, 접속일 기준. 한 페이지 최대 100건.
> - 원문 확인 필요: 일시 필드가 `Z`(UTC) 형식으로 예시되어 있는데 실제 값이 UTC 인지 KST 인지 불명.

## 타임라인 통계 (4종)

발송 기준 / 클릭 기준 × 일별 / 시간별. 4개 API 가 요청 Body 를 공유한다.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| from | String | ● | 조회 시작일 `YYYY-MM-DD` |
| to | String | ● | 조회 종료일 `YYYY-MM-DD` |
| urlId | String | ● | 반응형 URL ID |

| 기능 | 경로 |
|---|---|
| 발송 기준 일별 | `POST /msg/v1/stat/url/sendDay` |
| 발송 기준 시간별 | `POST /msg/v1/stat/url/sendHour` |
| 클릭 기준 일별 | `POST /msg/v1/stat/url/clickDay` |
| 클릭 기준 시간별 | `POST /msg/v1/stat/url/clickHour` |

응답은 원문에 필드 표 없이 예시만 있다. 예시 기준 필드:

| 필드 | 예시 값 | 포함 API |
|---|---|---|
| urlId | `URL12345` | 4종 모두 |
| ymd | `2024-01-25` | 4종 모두 |
| ch | `SMS` | 4종 모두 |
| conDt | `2024-01-25` | 4종 모두 |
| sumCnt | `350` (문자열) | 4종 모두 |
| avgCnt | `23.3` (문자열) | 4종 모두 |
| hour | `14` | 시간별 2종(sendHour, clickHour) |

```json
{ "code": "10000", "message": "성공",
  "data": { "urlId": "URL_ID_EXAMPLE", "ymd": "2024-01-25", "ch": "SMS", "hour": "14",
            "conDt": "2024-01-25", "sumCnt": "150", "avgCnt": "12.5" } }
```

> 주의
> - 발송 기준·클릭 기준 모두 최대 15일까지 조회 가능. `urlId` 필수.
> - 원문 확인 필요: 응답 필드 의미(`conDt`, `sumCnt`, `avgCnt`)와 배열 여부, 이 4개 API 의 Header 표(원문에 없음, 위 공통 Header 로 보임).
