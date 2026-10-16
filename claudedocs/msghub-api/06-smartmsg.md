# 2.6 통합발송 (스마트 메시지)
> 원문: https://doc.msghub.uplus.co.kr/rest-api/02메시지발송/0206smartmsg/ · 확인일 2026-10-16

사전 승인된 스마트 템플릿 하나와 Key-Value 데이터로 여러 채널(SMS, LMS, MMS, 알림톡, 친구톡, Push 등)에 순차 발송한다. 채널별 발송이 실패하면 다음 채널로 자동 전환된다.

## 한눈에 보기

| 기능 | Method | 경로 | 호스트 |
|---|---|---|---|
| 통합발송 | POST | `/send/v1.1` | api-send |

## 통합발송

`POST /send/v1.1` — 템플릿 코드(tmpltCode)와 수신자별 kvData 로 발송한다.

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
| tmpltCode | String | ● | 20 | 스마트 템플릿 코드 |
| campaignId | String | - | 20 | 캠페인 ID |
| deptCode | String | - | 20 | 부서 코드 |
| recvInfoLst | Array | ● | 10개 | 수신자별 정보 |

### agency 객체

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| kisaOrigCode | String | - | 재판매사 KISA 최초식별코드 |
| rcsAgencyId | String | - | RBC 에 등록된 대행사 ID |
| rcsAgencyKey | String | - | RBC 에서 발급된 대행사 키 |

### recvInfoLst[] 객체

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| cliKey | String | ● | 30 | 클라이언트 키 |
| callback | String | - | 100 | 발신번호 |
| phone | String | ● | 20 | 수신번호. 국제문자 발송 시 맨 앞의 `0` 제외 |
| cuid | String | - | 50 | 푸시 사용자 아이디 |
| kvData | Object | - | - | 개별화 메시지 머지 데이터(템플릿 변수명 → 값) |
| userCustomFields | Object | - | - | 사용자 정의 필드 |

### fbInfoLst 객체(참고)
원문 Appendix 에 fbInfoLst 표(ch, title, msg, fileId, fileIdLst)가 있으나 요청 Body 표에는 fbInfoLst 가 없다.

> 원문 확인 필요: 통합발송 요청에 fbInfoLst 를 넣을 수 있는지 불명. 채널 순서·대체 규칙은 템플릿에 정의된 것으로 보이며 이 페이지에는 설명이 없다.

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
  "tmpltCode": "TEMPLATE_CODE_EXAMPLE",
  "deptCode": "MARKETING",
  "recvInfoLst": [
    {
      "cliKey": "test001",
      "callback": "0212345678",
      "phone": "01000000000",
      "kvData": { "이름": "홍길동", "사용량": "1,000건" }
    }
  ]
}
```

> 주의
> - 동보발송은 1건에 최대 10명, TPS 는 수신자 수 기준. 예약발송은 현재 시점부터 최대 30일. 단축URL 사용 시 메시지 길이 제한 가능.
> - 템플릿 코드는 사전에 승인된 것만 쓸 수 있다.
> - kvData 의 키는 템플릿에 정의된 변수와 일치해야 한다.
> - 채널별 발송 실패 시 다음 채널로 자동 전환(순차 발송).
> - 원문 확인 필요: 예시의 `rcsAgencyId`/`rcsAgencyKey` 가 RCS 채널을 쓸 때만 필요한지 설명이 없다.
> - 원문 확인 필요: recvInfoLst 안의 callback(100자)이 요청 최상위 callback 과 어떻게 구분되는지(통합발송은 최상위 callback 없음) — 수신자별 발신번호로 해석했다.
