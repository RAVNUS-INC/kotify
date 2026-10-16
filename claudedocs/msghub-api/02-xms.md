# 2.2 문자 메시지 (SMS/MMS)
> 원문: https://doc.msghub.uplus.co.kr/rest-api/02메시지발송/0202xms/ · 확인일 2026-10-16

SMS(90 byte 단문), LMS/MMS(제목·긴 본문·첨부) 를 발송한다. LMS 와 MMS 는 같은 엔드포인트를 쓴다(첨부 유무로 구분).

## 한눈에 보기

| 기능 | Method | 경로 | 호스트 |
|---|---|---|---|
| SMS 발송 | POST | `/xms/sms/v1` | api-send |
| LMS/MMS 발송(파일ID 사용) | POST | `/xms/mms/v1` | api-send |
| MMS 발송(파일 직접 첨부) | POST | `/xms/mms/file/v1` | api-send |

## 공통 개념

### 동보발송과 TPS
- 1건의 요청에 같은 내용을 최대 10명(recvInfoLst 10개)에게 보낼 수 있다.
- TPS 는 수신자 수 기준이다. 수신자 5명짜리 SMS 1건은 TPS 5 로 계산한다.

### 공통 제약
- 발신번호(callback)는 사전 등록된 번호만 사용한다.
- 예약발송은 현재 시점부터 최대 30일까지.
- 단축URL(clickUrlYn=Y) 사용 시 메시지 길이가 제한될 수 있다.
- 첨부파일은 사전에 업로드한 파일만 쓸 수 있고 최대 3개.
- fbInfoLst 는 발송 실패 시 대체발송 정보다. 대체 채널은 SMS, MMS 만 가능하며 메인 채널과 같을 수 없다.

### agency 객체

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| agency.kisaOrigCode | String | - | 재판매사 KISA 최초식별코드 |

### recvInfoLst[] 객체

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| cliKey | String | ● | 30 | 클라이언트(고객사) 메시지 키 |
| phone | String | ● | 20 | 수신번호. 국제문자 발송 시 맨 앞의 `0` 을 빼야 한다 |
| mergeData | Object | - | - | 개별화 메시지용 머지 데이터. 본문의 `#{이름}` 같은 변수에 키 이름으로 치환 |
| userCustomFields | Object | - | - | 사용자 정의 필드(리포트 웹훅으로 되돌려 받는 값) |

### fbInfoLst[] 객체

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| ch | String | ● | 대체 채널(SMS 또는 MMS) |
| title | String | - | 제목. 채널이 MMS 이면 필수 |
| msg | String | ● | 대체 메시지 본문 |
| fileId | String | - | 파일 ID. fileId 와 fileIdLst 중 하나만 사용 |
| fileIdLst | Array | - | 파일 ID 목록(최대 3개) |

### 공통 응답
즉시 발송 응답의 `data` 는 수신자별 배열이다.

| 필드 | 타입 | 설명 |
|---|---|---|
| data[].cliKey | String | 요청에 넣은 클라이언트 키 |
| data[].msgKey | String | msghub 가 부여한 메시지 키 |
| data[].phone | String | 수신번호 |
| data[].code | String | 수신자별 결과 코드 |
| data[].message | String | 수신자별 결과 메시지 |

예약발송(resvYn=Y)이면 `data` 가 배열이 아니라 객체로 온다.

```json
{ "code": "10000", "message": "성공",
  "data": { "regDt": "2026-04-08T11:16:55", "webReqId": "{webReqId}" } }
```

webReqId 는 예약 취소에 쓴다([2.7 예약발송 관리](07-reservation.md)). 최종 전달 결과는 [2.8 리포트](08-report.md) 로 확인한다.

> 원문 확인 필요: 원문의 예약발송 응답 예시 JSON 은 끝에 `]` 가 남아 있는 등 문법이 깨져 있다. regDt, webReqId 두 필드만 근거로 삼았다.

## SMS 발송

`POST /xms/sms/v1` — 90 byte 이내 텍스트 문자를 발송한다.

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
| resvReqDt | String | - | - | 예약발송 시각. 예 `2025-07-13 13:15` |
| agency | Object | - | - | 대행사 정보 |
| callback | String | ● | 20 | 발신번호 |
| campaignId | String | - | 20 | 캠페인 ID |
| deptCode | String | - | 20 | 부서 코드 |
| msg | String | ● | 90 byte | 메시지 내용 |
| recvInfoLst | Array | ● | 10개 | 수신자 목록 |
| fbInfoLst | Array | - | - | 대체발송 목록 |

예시

```json
{
  "callback": "0212345678",
  "msg": "안녕하세요. #{이름}고객님",
  "recvInfoLst": [
    { "cliKey": "test001", "phone": "01000000000", "mergeData": { "이름": "홍길동" } }
  ],
  "fbInfoLst": [ { "ch": "MMS", "title": "제목", "msg": "MMS 메시지 내용" } ]
}
```

> 주의
> - 공통 제약(동보 10명, 30일 예약, 사전 등록 발신번호, 대체발송 규칙)을 따른다.
> - 원문 확인 필요: resvReqDt 형식은 예시(`yyyy-MM-dd HH:mm`)만 있고 시간대·초 단위 허용 여부 설명이 없다.
> - 원문 확인 필요: msg 90 byte 에 머지 치환 후 길이가 적용되는지, 인코딩(EUC-KR 기준 등)은 명시가 없다.

## LMS/MMS 발송 (파일ID 사용)

`POST /xms/mms/v1` — 제목·본문(최대 2000 byte)을 담은 장문/멀티미디어 문자를 JSON 으로 발송한다. fileIdLst 없이 보내면 LMS, 사전 업로드한 파일 ID 를 넣으면 MMS 다.

요청 Header: Authorization(●), Content-Type `application/json`(●).

요청 Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| clickUrlYn | String | - | 1 | 단축URL 사용 여부(Y/N) |
| resvYn | String | - | 1 | 예약발송 여부(Y/N) |
| resvReqDt | String | - | - | 예약발송 시각 |
| agency | Object | - | - | 대행사 정보 |
| callback | String | ● | 20 | 발신번호 |
| campaignId | String | - | 20 | 캠페인 ID |
| deptCode | String | - | 20 | 부서 코드 |
| title | String | - | 40 byte | MMS 제목 |
| msg | String | ● | 2000 byte | 메시지 내용 |
| fileIdLst | Array | - | 최대 3개 | 사전 업로드된 파일 ID 목록 |
| recvInfoLst | Array | ● | 10개 | 수신자 목록 |
| fbInfoLst | Array | - | - | 대체발송 목록 |

예시

```json
{
  "callback": "0212345678",
  "title": "MMS 테스트 제목",
  "msg": "안녕하세요. #{이름}고객님",
  "fileIdLst": ["mms0812"],
  "recvInfoLst": [
    { "cliKey": "test001", "phone": "01000000000", "mergeData": { "이름": "홍길동" } }
  ],
  "fbInfoLst": [ { "ch": "SMS", "msg": "SMS 메시지 내용" } ]
}
```

> 주의
> - 첨부는 사전에 업로드된 파일만 가능하고 최대 3개. 업로드 API 는 이 페이지에 없다.
> - 원문 확인 필요: title 이 필수 아님으로 표기되어 있으나 fbInfoLst 의 MMS 대체발송에서는 title 이 필수다. 본 요청에서 LMS 의 title 필요 여부는 원문에 명시가 없다.

## MMS 발송 (파일 직접 첨부)

`POST /xms/mms/file/v1` — 파일을 multipart 로 함께 올려 MMS 를 발송한다.

요청 Header

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| Authorization | String | ● | `Bearer {token}` |
| Content-Type | String | ● | multipart/form-data |

multipart 구성(원문 예시 기준)

| 파트 | 설명 |
|---|---|
| reqMsg | 위 "LMS/MMS 발송" Body 와 같은 JSON 문자열 |
| parts | 첨부 파일(파일명과 `type=image/jpeg` 같은 MIME 지정) |

예시

```bash
curl -X POST "https://api-send.msghub-qa.uplus.co.kr/xms/mms/file/v1" \
  -H "Authorization: Bearer {token}" \
  -F 'reqMsg={"callback":"0212345678","title":"제목","msg":"본문","recvInfoLst":[{"cliKey":"test001","phone":"01000000000"}]}' \
  -F "parts=@image.jpg;type=image/jpeg"
```

> 주의
> - 원문 확인 필요: 파트 이름(reqMsg, parts)과 JSON 파트의 Content-Type 지정 방법, 파일 형식·용량·개수 제한이 원문에 상세히 없다(첨부 3개 제한만 공통 문구에 있음).
> - 원문 확인 필요: 이 엔드포인트에서도 Content-Type 이 `application/json 또는 multipart/form-data` 로 같이 표기되어 있다. 파일 직접 첨부는 multipart 만 해당하는 것으로 해석했다.
