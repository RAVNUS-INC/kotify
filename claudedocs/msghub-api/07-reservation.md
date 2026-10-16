# 2.7 예약발송 관리
> 원문: https://doc.msghub.uplus.co.kr/rest-api/02메시지발송/0207resvmsg/ · 확인일 2026-10-16

예약 발송(resvYn=Y) 건의 목록을 조회하고, 발송 전인 예약을 취소한다. 예약 등록 시 받은 `webReqId` 가 식별자다.

## 한눈에 보기

| 기능 | Method | 경로 | 호스트 |
|---|---|---|---|
| 예약 발송 조회 | GET | `/msg/v1.1/resv/sendList` | api |
| 예약 발송 취소 | POST | `/msg/v1/resv/sendCancel` | api |

## 예약 발송 조회

`GET /msg/v1.1/resv/sendList` — 예약된 발송 목록과 상태를 조회한다.

요청 Header

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| Authorization | String | ● | `Bearer {token}` |
| Content-Type | String | ● | application/json |

쿼리 파라미터는 원문에 없다.

응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| data.resvSendList | Array | 예약 발송 목록 |
| data.resvSendList[].webReqId | String | 웹 요청 아이디 |
| data.resvSendList[].ch | String | 채널 |
| data.resvSendList[].senderCnt | String | 발송 건수 |
| data.resvSendList[].callback | String | 발신번호 |
| data.resvSendList[].status | String | 예약 상태(아래 코드표) |
| data.resvSendList[].resvSenderYn | String | 예약 발송 여부 |
| data.resvSendList[].delYn | String | 삭제 여부 |
| data.resvSendList[].resvCnclReason | String | 예약 취소 사유 |
| data.resvSendList[].reqDt | String | 예약 등록 일시 |

예시 응답

```json
{
  "code": "10000", "message": "성공",
  "data": { "resvSendList": [
    { "webReqId": "{webReqId}", "ch": "SMS", "senderCnt": "1", "callback": "0100000000",
      "status": "SEND_WAIT", "resvSenderYn": "N", "delYn": "N",
      "resvCnclReason": "", "reqDt": "2025-07-03T03:05:22" } ] }
}
```

> 주의
> - 조회는 최대 90일 이내 데이터만 가능하다.
> - 예약 시간은 서버 시간 기준으로 처리된다.
> - 원문 확인 필요: "발송 완료된 메시지는 조회 결과에서 제외"라고 하면서 상태값에 COMPLETED(발송 완료)가 있고 원문 응답 예시도 `COMPLETED` 한 건이다. 완료 건이 목록에 나오는지 모순.
> - 원문 확인 필요: 예시의 resvSenderYn 이 `N` 인데 의미(예약 발송 여부)가 직관과 다를 수 있다. 값 의미는 원문에 설명이 없다.
> - 원문 확인 필요: 조회 기간·페이징을 지정하는 쿼리 파라미터가 없다.

## 예약 발송 취소

`POST /msg/v1/resv/sendCancel` — 발송 전인 예약 건을 취소한다. 경로 버전이 조회(v1.1)와 달리 v1 이다.

요청 Header: Authorization(●), Content-Type `application/json`(●).

요청 Body

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| webReqId | String | ● | 예약 등록 시 받은 웹 요청 아이디 |
| resvCnclReason | String | ● | 예약 취소 사유 |

응답은 공통 래퍼 `{code, message}` 만 있고 data 는 없다.

예시

```json
{ "webReqId": "{webReqId}", "resvCnclReason": "마케팅 일정 변경으로 인한 발송 취소" }
```

> 주의
> - 이미 발송이 시작된 메시지는 취소할 수 없다.
> - 취소 사유는 필수.
> - 취소된 메시지는 재발송할 수 없다.
> - 취소 결과는 즉시 조회에 반영된다.

## 코드값

### 예약 상태 코드(status)

| 코드 | 설명 |
|---|---|
| SEND_WAIT | 발송 대기 |
| ING | 처리중 |
| FAIL | 실패 |
| COMPLETED | 발송 완료 |

> 원문 확인 필요: 취소된 예약을 나타내는 status 값은 표에 없다. 취소 여부는 resvCnclReason, delYn 으로 판단하는 것으로 보이나 원문에 명시는 없다.
