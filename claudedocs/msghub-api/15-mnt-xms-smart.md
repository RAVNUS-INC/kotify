# 3.6 문자 메시지 / 통합발송 템플릿 관리
> 원문: https://doc.msghub.uplus.co.kr/rest-api/03채널/0306api-xms-smart/ · 확인일 2026-10-16

문자·통합발송(스마트메시지) 채널에 사전 등록한 템플릿을 조회하는 API 2개다. 호스트는 `api` 이고 인증은 일반 API 와 같은 Bearer 토큰이다. 상용·검수 URL 은 00-README 를 본다.

## 한눈에 보기

| 기능 | Method | 경로 | 호스트 |
|---|---|---|---|
| 템플릿 목록 조회 | GET | `/msg/v1/template/all` | api |
| 통합템플릿 상세 조회 | GET | `/msg/v1/template/get` | api |

공통 헤더(두 API 모두)

| 헤더 | 타입 | 필수 | 설명 |
|---|---|---|---|
| Authorization | String | ● | 사용자 인증 토큰 (`Bearer {token}`) |
| Content-Type | String | ● | `application/json` |

## 템플릿 목록 조회
`GET /msg/v1/template/all`
사전에 등록한 템플릿 목록을 채널별로 조회한다.

**Query**

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| ch | String | ● | | 채널. `mms` / `rcs` / `alimtalk` / `push` / `smart` |
| listCnt | int | ● | | 조회할 템플릿 목록 수 |
| pageIdx | int | ● | | 페이지 번호 |

**응답 data[]**

| 필드 | 타입 | 설명 |
|---|---|---|
| data[].tmpltId | String | 템플릿 ID |
| data[].tmpltName | String | 템플릿명 |
| data[].senderType | String | 발송 유형 (예시 `통합`) |
| data[].msgKind | String | 메시지 구분 (예시 `광고성`, `정보성`) |
| data[].msgType | String | 메시지 타입 (예시 `기본`) |
| data[].tmpltStatus | String | 템플릿 상태 (예시 `완료`) |
| data[].regDt | String | 등록일자 (`2025-12-17 00:00:00` 형식) |
| data[].updDt | String | 수정일자 (null 가능) |

**예시**

```
GET /msg/v1/template/all?ch=mms&listCnt=10&pageIdx=1
Authorization: Bearer {token}
```
```json
{ "code": "10000", "message": "성공",
  "data": [ { "tmpltId": "TPL....g4O", "tmpltName": "통합발송테스트_02", "senderType": "통합", "msgKind": "광고성",
              "msgType": "기본", "tmpltStatus": "완료", "regDt": "2025-12-17 00:00:00", "updDt": null } ] }
```

> 주의
> - 이 목록 응답의 `msgKind`·`msgType`·`tmpltStatus` 는 한글 표시값이다. 상세 조회는 `A`/`BASE` 같은 코드값으로 내려온다(아래 참고).
> - 원문 확인 필요: `senderType`, `msgKind`, `msgType`, `tmpltStatus` 의 가능한 값 전체 목록은 원문에 없다. 위 값은 예시에 나온 것뿐이다.
> - 원문 확인 필요: 쿼리 `ch` 에 `smart` 외 `mms`, `rcs` 등을 줄 때 각 채널 템플릿을 모두 이 API 가 돌려주는지, 예시가 모두 통합(`senderType: 통합`)인 점 포함 동작 범위가 불명확하다.
> - 원문 확인 필요: 한 페이지 최대 `listCnt` 와 전체 건수(`total`) 응답 여부가 적혀 있지 않다.

## 통합템플릿 상세 조회
`GET /msg/v1/template/get`
통합발송 템플릿 하나의 상세를 조회한다. 응답에 채널별(RCS, 친구톡 등) 템플릿 정보가 들어 있다.

**Query**

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| tmpltId | String | ● | 템플릿 ID |

**응답 data**

| 필드 | 타입 | 설명 |
|---|---|---|
| data.tmpltCode | String | 템플릿 코드 |
| data.msgKind | String | 메시지 구분 (예시 `A`) |
| data.msgType | String | 메시지 타입 (예시 `BASE`) |
| data.tmpltTitle | String | 템플릿 제목 |
| data.tmpltInfo[] | Array | 채널별 템플릿 정보 |
| data.tmpltInfo[].ch | String | 채널 (예시 `RCS`, `FRIENDTALK`) |
| data.tmpltInfo[].data | Object | 채널별 템플릿 내용 (구조는 채널마다 다름) |
| data.tmpltInfo[].chTypeList | String | 템플릿에 포함된 채널 목록, 쉼표 구분 (예시 `RCS,KAKAO`) |

채널별 `data` 에서 예시에 나온 키:

| 채널 | 키 |
|---|---|
| RCS | `footer`, `header`, `brandNm`, `buttons[]`, `agencyId`, `callback`, `mergeData[]`(예 `{description}`), `rcsPrdType`(예 `SMS`), `copyAllowed`, `expiryOption`, `messagebaseId` |
| FRIENDTALK | `msg`, `image{}`, `adFlag`(`Y`/`N`), `buttons[]`, `kkoChId`, `callback`, `wideImageYn`, `senderKeyType` |

**예시**

```
GET /msg/v1/template/get?tmpltId=TPL....4O
Authorization: Bearer {token}
```
```json
{ "code": "10000", "message": "성공",
  "data": { "tmpltCode": "TPL....4O", "msgKind": "A", "msgType": "BASE", "tmpltTitle": "통합발송테스트_01",
    "tmpltInfo": [
      { "ch": "RCS", "data": { "agencyId": "uplus", "rcsPrdType": "SMS", "messagebaseId": "SS000000",
                               "mergeData": [ { "description": "통합발송 RCS 테스트입니다." } ] },
        "chTypeList": "RCS,KAKAO" },
      { "ch": "FRIENDTALK", "data": { "msg": "통합발송 친구톡 테스트입니다.", "adFlag": "Y", "buttons": [] },
        "chTypeList": "RCS,KAKAO" } ] } }
```

> 주의
> - 원문 확인 필요: 응답 표는 `data` 를 Array 로 적었지만 예시는 객체다. 예시를 따라 객체로 정리했다.
> - 원문 확인 필요: 요청 `tmpltId` 는 목록 응답의 `tmpltId` 이고 응답의 `tmpltCode` 와 같은 값으로 보이나 원문에 명시되지 않았다. `chTypeList` 는 `RCS,KAKAO` 인데 `ch` 는 `FRIENDTALK` 인 점도 설명이 없다.
> - 원문 확인 필요: 목록의 한글 `msgKind`/`msgType` 과 상세의 `A`/`BASE` 코드 대응표가 없다.
> - 원문 Appendix 의 "결과코드"는 링크로만 존재해 이 문서에 코드표가 없다.
