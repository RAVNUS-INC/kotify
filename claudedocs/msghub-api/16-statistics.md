# 4.1 통계
> 원문: https://doc.msghub.uplus.co.kr/rest-api/04통계/0401statistics/ · 확인일 2026-10-16

## 한눈에 보기

| 기능 | Method | 경로 | 호스트 |
|---|---|---|---|
| 발송통계 조회 | POST | `/msg/v1/stat` | mnt-api |

## 발송통계 조회

`POST /msg/v1/stat`

특정 일자의 채널별 전체·성공·실패 발송 건수를 조회한다.

요청 Header

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| Authorization | String | ● | 사용자 인증 토큰 (`Bearer {token}`) |
| Content-Type | String | ● | `application/json` |

요청 Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| ymd | String | ● | - | 조회 일자 (예시 값은 `20250710` 형식) |
| projectId | String | ● | - | 프로젝트 ID |

응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| data.ymd | String | 발송일자 (yyyy-mm-dd) |
| data.projectId | String | 프로젝트 ID |
| data.apiKey | String | apiKey |
| data.ch | String | 발송 채널 |
| data.totalCnt | Integer | 전체 발송 건수 |
| data.succCnt | Integer | 성공 건수 |
| data.failCnt | Integer | 실패 건수 |

요청 예시

```json
{ "ymd": "20250710", "projectId": "PROJECT_ID_EXAMPLE" }
```

응답 예시

```json
{
  "code": "10000",
  "message": "성공",
  "data": [
    { "ymd": "2025-07-10", "projectId": "PROJECT_ID_EXAMPLE", "apiKey": "API_KEY_EXAMPLE",
      "ch": "SMS", "totCnt": "12", "succCnt": "11", "failCnt": "1" },
    { "ymd": "2025-07-10", "projectId": "PROJECT_ID_EXAMPLE", "apiKey": "API_KEY_EXAMPLE",
      "ch": "FRIENDTALK", "totCnt": "5", "succCnt": "4", "failCnt": "1" }
  ]
}
```

> 주의
> - 원문 확인 필요: 응답 표는 `data` 를 단일 객체로 적고 건수 필드명을 `totalCnt`(Integer) 로 쓰지만, 예시 응답은 `data` 가 채널별 배열이고 필드명이 `totCnt`, 값이 문자열이다. 실제 응답으로 확인할 것.
> - 원문 확인 필요: `ymd` 입력 형식을 표에서 "년월일"로만 적었다(예시는 `yyyyMMdd`).
> - 채널별로 한 행씩 오는 것으로 보인다(예시 기준).
