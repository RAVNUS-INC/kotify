# 2.8 메시지 리포트
> 원문: https://doc.msghub.uplus.co.kr/rest-api/02메시지발송/0208report_v12/ · 확인일 2026-10-16

발송 결과(리포트)를 받는 방법은 두 가지다. polling 은 우리가 주기적으로 가져가고, webhook 은 msghub 가 등록된 URL 로 밀어준다. 별도로 cliKey 기준 조회 API 가 있다.

## 한눈에 보기

| 기능 | Method | 경로 | 호스트 |
|---|---|---|---|
| 리포트 요청(Polling) | GET | `/msg/v1.2/report` | api |
| 리포트 처리 결과 전달(Polling) | POST | `/msg/v1.2/report/result` | api |
| 리포트 전달(Webhook) | POST | `{WEBHOOK_URL}` (msghub → 고객사) | 고객사 서버 |
| 리포트 조회 | POST | `/msg/v1/sent` | api |

## 공통 개념

### 수신 방식 비교

| 항목 | Polling | Webhook |
|---|---|---|
| 방향 | 고객사 → msghub 가 가져감 | msghub → 고객사 URL 로 전달 |
| 한 번에 받는 건수 | 최대 100 | 최대 100(rptCnt) |
| 전달 횟수 | 결과는 한 번만 전달 | 한 번만 전달, 실패 시 재시도 |
| 완료 확인 | report key 를 120초 안에 `/report/result` 로 전달 | HTTP 응답 코드(200/204/400) |
| 미확인 시 | 120초 후 같은 리포트 재전달(중복 방지 필요) | 기본 10초 간격 재시도 |
| 보관·만료 | 요청하지 않으면 81시간 후 자동 만료 | 72시간 보관 |

### 수치 요약
- Polling 빈 응답 시 최소 요청 간격 10초. 10초 이내 재요청은 실패 처리.
- Polling 응답 1건이라도 있으면 즉시 다음 요청, 없으면 대기 후 재요청.
- report key 처리 완료 전달 제한 시간 120초, 초과 시 같은 리포트 재전달.
- Polling 리포트 만료 81시간 / Webhook 보관 72시간.
- Webhook 재시도 기본 10초(추후 변경 가능, 원문 표현).
- 리포트 조회(`/msg/v1/sent`)는 최대 90일 이내, 한 번에 cliKey 10건.

### 브랜드톡·친구톡 상품 코드(productCode)
2025년까지 브랜드톡의 productCode 는 친구톡 상품 코드로 표현되고, 2026년 이후에는 친구/비친구 상품 코드로 표현된다.

| 코드 | 설명 |
|---|---|
| KFRT1 | 친구톡 Text |
| KFRM2 | 친구톡 이미지 |
| KFRM3 | 친구톡 와이드 |
| KFRM4 | 친구톡 아이템리스트 |
| KFRM5 | 친구톡 캐러셀 |
| KFRM6 | 친구톡 프리미엄 |
| KFRM7 | 친구톡 커머스 |
| KFRM8 | 친구톡 캐러셀 커머스 |
| BRDF | 브랜드톡 친구 |
| BRDNF | 브랜드톡 비친구 |

> 원문 확인 필요: SMS, LMS 등 문자 상품 코드 목록은 이 페이지에 없고, 예시에서 `SMS`, `LMS` 값이 쓰인다.

### 이통사/딜러사(telco)
xMS, RCS 는 이통사(예 SKT, KT, LGU), 알림톡·친구톡은 API Key 설정에서 "결과 딜러사 정보 제공 Y" 인 경우 카카오 딜러사가 들어간다. 최상위 `telco` 는 xMS, RCS 만 해당한다.

## 리포트 요청 (Polling)

`GET /msg/v1.2/report` — 처리 완료된 메시지 결과를 최대 100건 배열로 받는다. 같은 결과는 한 번만 내려간다.

요청 Header: Authorization(●), Content-Type `application/json`(●). 쿼리·본문 없음.

응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| data.rptKey | String | 리포트 키. 처리 후 `/report/result` 로 되돌려 보낸다 |
| data.rptCnt | Integer | 리포트 개수 |
| data.rptLst | Array | 리포트 목록 |
| data.rptLst[].msgKey | String | 메시지 고유 키 |
| data.rptLst[].cliKey | String | 클라이언트 키 |
| data.rptLst[].ch | String | 채널 |
| data.rptLst[].resultCode | String | 발송 결과 코드 |
| data.rptLst[].resultCodeDesc | String | 결과 코드 설명 |
| data.rptLst[].fbReasonLst | Array | fallback 사유 목록 |
| data.rptLst[].fbReasonLst[].ch | String | 채널 |
| data.rptLst[].fbReasonLst[].fbResultCode | String | fallback 결과 코드 |
| data.rptLst[].fbReasonLst[].fbResultDesc | String | fallback 결과 설명 |
| data.rptLst[].fbReasonLst[].telco | String | 이통사(xMS, RCS) 또는 카카오 딜러사 |
| data.rptLst[].telco | String | 이통사(xMS, RCS만) |
| data.rptLst[].rptDt | String | 결과 수신 일시 |
| data.rptLst[].productCode | String | 상품 코드 |

예시 응답

```json
{
  "code": "10000", "message": "성공",
  "data": {
    "rptKey": "{rptKey}", "rptCnt": 1,
    "rptLst": [
      { "msgKey": "{msgKey}", "cliKey": "test001", "ch": "MMS",
        "resultCode": "10000", "resultCodeDesc": "성공",
        "fbReasonLst": [ { "ch": "RCS", "fbResultCode": "54002",
                           "fbResultDesc": "No Rcs Capability", "telco": "KT" } ],
        "telco": "SKT", "rptDt": "2025-07-15T16:51:43", "productCode": "LMS" } ]
  }
}
```

> 주의
> - 1건 이상 받았으면 즉시 다음 요청을 보낸다. 없으면 잠시 대기한 뒤 재요청한다. 한 번에 최대 100건.
> - 리포트가 없을 때 무한 루프를 막기 위해 최소 10초 간격을 지킨다. 10초 안에 재요청하면 실패 처리된다.
> - 응답의 report key 는 처리 후 `/report/result` 로 보낸다. 120초 안에 보내지 않으면 같은 리포트가 다시 내려오므로 클라이언트가 중복 수신을 걸러야 한다.
> - 리포트를 아예 요청하지 않으면 81시간 후 자동 만료된다.
> - 원문 확인 필요: 응답이 단일 `rptKey` 하나이고 `/report/result` 의 요청은 `rptKeyLst` 배열이다. 한 응답의 모든 리포트가 rptKey 하나에 묶이는지, 건별 키가 있는지 불명.
> - 원문 확인 필요: 응답 data 에 리포트가 없을 때의 형태(빈 rptLst 또는 별도 code)가 원문에 없다.

## 리포트 처리 결과 전달 (Polling)

`POST /msg/v1.2/report/result` — 받아 처리한 리포트 키를 완료 처리한다.

요청 Header: Authorization(●), Content-Type `application/json`(●).

요청 Body

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| rptKeyLst | Array | - | 완료 처리할 리포트 키 목록 |

응답은 공통 래퍼 `{code, message}` 만 있다.

예시

```json
{ "rptKeyLst": ["{rptKey1}", "{rptKey2}"] }
```

> 주의
> - 120초 안에 전달하지 않으면 리포트가 다시 전달된다. 클라이언트는 중복 방지를 위해 확인 처리를 해야 한다.
> - 원문 확인 필요: rptKeyLst 의 필수 여부 열이 비어 있다(위 표의 `-` 는 원문 공란을 뜻함).

## 리포트 전달 (Webhook)

`POST {WEBHOOK_URL}` — msghub 가 고객사가 등록한 웹훅 URL 로 처리 완료된 리포트를 보낸다. 우리가 구현할 수신 엔드포인트의 규격이다.

요청 Header(msghub → 고객사): `Content-Type: application/json`.

요청 Body

| 필드 | 타입 | 설명 |
|---|---|---|
| rptCnt | Integer | 리포트 개수(최대 100) |
| rptLst | Array | 리포트 목록 |
| rptLst[].isBi | Boolean | RCS 양방향 메시지 여부 |
| rptLst[].msgKey | String | 메시지 고유 키 |
| rptLst[].cliKey | String | 클라이언트 키 |
| rptLst[].ch | String | 채널 |
| rptLst[].resultCode | String | 발송 결과 코드 |
| rptLst[].resultCodeDesc | String | 결과 코드 설명 |
| rptLst[].productCode | String | 상품 코드 |
| rptLst[].fbReasonLst | Array | fallback 사유 목록 |
| rptLst[].fbReasonLst[].ch | String | 채널 |
| rptLst[].fbReasonLst[].fbResultCode | String | fallback 결과 코드 |
| rptLst[].fbReasonLst[].fbResultDesc | String | fallback 결과 설명 |
| rptLst[].fbReasonLst[].telco | String | 이통사(xMS, RCS) 또는 카카오 딜러사 |
| rptLst[].rptDt | String | 결과 수신 일시 |
| rptLst[].rptRegDt | String | 결과 등록 일시 |
| rptLst[].phone | String | 수신번호 |
| rptLst[].userCustomFields | Object | 사용자 정의 필드 |
| rptLst[].recvDt | String | 발송 요청 일시 |

고객사 응답 규칙(HTTP 상태)

| HTTP | 의미 | 비고 |
|---|---|---|
| 200 | 성공 | 정상 수신 확인 |
| 204 | 성공 | 응답하거나 처리할 리포트가 없음 |
| 400 | 실패 | 실패로 응답하면 재처리(재전달) 가능 |

예시 수신 payload

```json
{
  "rptCnt": 1,
  "rptLst": [
    { "isBi": false, "msgKey": "{msgKey}", "cliKey": "test001", "ch": "SMS",
      "resultCode": "10000", "resultCodeDesc": "성공", "productCode": "SMS",
      "fbReasonLst": [ { "ch": "RCS", "fbResultCode": "54002",
                         "fbResultDesc": "No Rcs Capability", "telco": "KT" } ],
      "rptDt": "2025-04-19T15:01:40", "rptRegDt": "2025-04-19T15:01:40",
      "phone": "01000000000", "userCustomFields": { "key1": "value1", "key2": 123 },
      "recvDt": "2025-04-18T15:01:40" } ]
}
```

> 주의
> - 메시지는 한 번만 전달되고, 실패하면 재시도한다(기본 10초 간격, 추후 변경 가능). 리포트는 72시간 보관된다.
> - msghub 로 성공적인 수신을 알리려면 HTTP 200 OK 를 응답해야 한다. 400 은 실패로 보고 재처리 대상이 된다.
> - userCustomFields 를 받으려면 콘솔 설정이 필요하다: 메시지허브 관리자콘솔 > 프로젝트 > 프로젝트 상세 > API KEY > 해당 apiKey 선택 > 수정 > 결과수신 방법 `Webhook` 선택 > `추가 필드 사용` 선택.
> - 원문 확인 필요: 재시도 횟수·총 재시도 기간, 200/204 외 코드(5xx, 타임아웃)의 취급이 원문에 없다. 400 만 "재처리 가능"으로 적혀 있다.
> - 원문 확인 필요: 원문 예시 JSON 은 `rptLst` 가 배열 형식이 아니고 msgKey 가 중복되며 `"ch": "SMS",001` 같은 깨진 문자가 섞여 있다. 필드 표를 근거로 예시를 재구성했다.
> - 원문 확인 필요: 웹훅 인증(서명·IP 허용 목록) 관련 설명이 없다.

## 리포트 조회

`POST /msg/v1/sent` — cliKey 와 발송일로 최대 90일 이내 메시지 상태를 조회한다.

요청 Header: Authorization(●), Content-Type `application/json`(●).

요청 Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| cliKeyLst | Array | - | 최대 10건 | 조회할 항목 목록 |
| cliKeyLst[].cliKey | String | ● | - | 고객이 부여한 메시지 키 |
| cliKeyLst[].reqDt | String | ● | - | 발송 일자 `YYYY-MM-DD` |

응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| data.cliKeyLst | Array | 결과 목록 |
| data.cliKeyLst[].msgKey | String | 메시지 고유 키 |
| data.cliKeyLst[].cliKey | String | 클라이언트 키 |
| data.cliKeyLst[].ch | String | 채널 |
| data.cliKeyLst[].status | String | 상태(아래 코드표) |
| data.cliKeyLst[].resultCode | String | 결과 코드 |
| data.cliKeyLst[].resultCodeDesc | String | 설명 |
| data.cliKeyLst[].telco | String | 이통사(xMS, RCS) 또는 카카오 딜러사 |
| data.cliKeyLst[].fbReasonLst | Array | fallback 사유 목록 |
| data.cliKeyLst[].fbReasonLst[].ch | String | 채널 |
| data.cliKeyLst[].fbReasonLst[].fbResultCode | String | fallback 결과 코드 |
| data.cliKeyLst[].fbReasonLst[].fbResultDesc | String | fallback 결과 설명 |
| data.cliKeyLst[].fbReasonLst[].telco | String | 이통사 또는 카카오 딜러사 |
| data.cliKeyLst[].rptDt | String | 결과 수신 일시 |
| data.cliKeyLst[].productCode | String | 상품 코드 |

예시

```json
{ "cliKeyLst": [ { "cliKey": "test001", "reqDt": "2025-07-02" } ] }
```

```json
{
  "code": "10000", "message": "성공",
  "data": { "cliKeyLst": [
    { "msgKey": "{msgKey}", "cliKey": "test001", "ch": "SMS", "status": "DONE",
      "resultCode": "10000", "resultCodeDesc": "성공", "telco": "LGU",
      "rptDt": "2025-07-02T13:46:03", "productCode": "SMS" } ] }
}
```

> 주의
> - 최대 90일 이내 데이터만 조회되며, 이를 넘으면 status 가 `OVER_DATE` 로 온다. 한 번에 cliKey 10건까지.
> - 원문 확인 필요: cliKeyLst 의 필수 여부 열이 비어 있다(비고에 "최대 10건"만). 객체 내부 cliKey, reqDt 는 필수.
> - 원문 확인 필요: 같은 cliKey 로 여러 번 발송한 경우(대체발송 등) reqDt 와의 매칭·응답 건수 규칙이 없다.

## 코드값

### 메시지 상태 코드(status)

| 코드 | 설명 |
|---|---|
| REG | 접수 완료 |
| ING | 처리중 |
| DONE | 완료 |
| OVER_DATE | 조회 기간 초과(90일) |
| INVALID_KEY | 키 오류 |

> 원문 확인 필요: resultCode(`10000` 성공 등)·fbResultCode 의 전체 코드 목록은 이 페이지에 없고 별도 페이지(2.9 결과코드)에 있다. 이 문서의 code `10000` 은 예시에서 확인된 성공 값이다.
