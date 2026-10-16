# 3.3 카카오 관리 V2 (발신프로필·템플릿)
> 원문: https://doc.msghub.uplus.co.kr/rest-api/03채널/0303mnt-kko_v2/ · 확인일 2026-10-16

카카오 채널(발신프로필) 등록·그룹 관리와 알림톡 템플릿의 생성·수정·검수·조회 API 모음. 모두 `mnt-api` 호스트이고 공통 헤더는 `Authorization: Bearer {token}` 과 `Content-Type: application/json`(템플릿 생성·수정에서 이미지를 올릴 때만 `multipart/form-data`)이다. 인증은 10-mnt-auth.md.

## 한눈에 보기

| # | 기능 | Method | 경로 | 호스트 |
|---|---|---|---|---|
| 1 | 템플릿 카테고리 코드 조회 | POST | `/kko/v2/channel/template/category/all` | mnt-api |
| 2 | 카카오 카테고리 정보 리스트(채널 카테고리) | POST | `/kko/v2/channel/category/all` | mnt-api |
| 3 | 카카오 채널로 그룹 목록 조회 | POST | `/kko/v2/channel/group/list` | mnt-api |
| 4 | 카카오 그룹에 채널 등록 | POST | `/kko/v2/channel/group/add` | mnt-api |
| 5 | 카카오 그룹에 포함된 채널 조회 | GET | `/kko/v2/channel/group/{groupKey}` | mnt-api |
| 6 | 카카오 그룹 목록 조회 | GET | `/kko/v2/channel/group/all` | mnt-api |
| 7 | 카카오 그룹에서 채널 삭제 | DELETE | `/kko/v2/channel/group/remove` | mnt-api |
| 8 | 고객사 카카오 채널 기간별 조회 | POST | `/kko/v2/kkoChannelList` | mnt-api |
| 9 | 알림톡 인증 토큰 요청 | POST | `/kko/v2/channel/token` | mnt-api |
| 10 | 알림톡 채널등록 사전정보 요청(relay 목록) | POST | `/kko/v2/channel/relayinfo` | mnt-api |
| 11 | 미사용 프로필 휴면 해제 | POST | `/kko/v2/channel/recover` | mnt-api |
| 12 | 카카오 채널 조회 | POST | `/kko/v2/channel/get` | mnt-api |
| 13 | 카카오 채널 등록 | POST | `/kko/v2/channel/create` | mnt-api |
| 14 | 템플릿 (재)검수요청 | POST | `/kko/v2/channel/template/request` | mnt-api |
| 15 | 템플릿 삭제 | POST | `/kko/v2/channel/template/delete` | mnt-api |
| 16 | 템플릿 문의하기 | POST | `/kko/v2/channel/template/comment` | mnt-api |
| 17 | 템플릿 목록 조회 | POST | `/kko/v2/channel/template/all` | mnt-api |
| 18 | 템플릿 생성 | POST | `/kko/v2/channel/template/create` | mnt-api |
| 19 | 템플릿 수정 | POST | `/kko/v2/channel/template/update` | mnt-api |
| 20 | 템플릿 조회 | POST | `/kko/v2/channel/template/get` | mnt-api |

## 공통 개념

### 발신프로필 유형 (`senderType` / `senderKeyType`)

| 값 | 의미 |
|---|---|
| S | 카카오 채널(일반, 기본값) |
| G | 그룹 |

단일 채널이면 `kkoChId`, 그룹 채널이면 `kkoGrpId` 를 넣는다(템플릿 계열 API 공통).

> 원문 확인 필요: 같은 의미의 필드명이 API 마다 `senderKeyType`(#14, #15, #20), `senderType`(#16, #17, #18, #19)로 다르게 적혀 있다. 원문 표기를 그대로 따랐다.

### 템플릿 상태 코드 (`templateStatusCode`)

| 코드 | 의미 |
|---|---|
| T | 등록완료 |
| R | 검수요청완료(딜러사 검수중) |
| Q | 카카오 검수중 |
| A | 템플릿 승인 완료 |
| S | 템플릿 반려 |

검수 중 상태 전이: `T → R → Q → S 또는 A`.

### 버튼 타입 (`buttons[].linkType`)

| 링크타입 | 설명 |
|---|---|
| WL | 웹링크 |
| AL | 앱링크 |
| DS | 배송조회 |
| BK | 봇키워드 |
| MD | 메시지전달 |
| BC | 상담톡 전환 |
| BT | 봇전환 |
| AC | 채널추가 |
| BF | 비즈니스폼 |

### 템플릿 주요 코드값

| 필드 | 값 |
|---|---|
| templateMessageType | BA 기본형 / EX 부가 정보형 / AD 광고 추가형 / MI 복합형 |
| templateEmphasizeType | NONE 선택안함 / TEXT 강조표기형 / IMAGE 이미지형 / ITEM_LIST 아이템리스트형 |
| comments[].status | INQ 문의 / APR 승인 / REJ 반려 / REP 답변 |

---

## 1. 템플릿 카테고리 코드 조회

`POST /kko/v2/channel/template/category/all` — 템플릿 생성 시 지정해야 하는 템플릿 카테고리 목록(코드·이름·그룹·포함/제외 예시)을 조회한다. 요청 본문은 없다.

응답 data (Array)

| 필드 | 타입 | 설명 |
|---|---|---|
| data[].code | String | 카테고리 코드 |
| data[].name | String | 카테고리 이름 |
| data[].groupName | String | 카테고리 그룹 이름 |
| data[].iclusion | String | 포함 예시(원문 필드명 철자 그대로) |
| data[].exclusion | String | 제외 예시 |

예시 응답

```json
{
  "code": "10000",
  "message": "성공",
  "data": [
    {
      "code": "003001",
      "name": "예약완료/예약내역",
      "groupName": "예약",
      "iclusion": "예약한 서비스의 확정된 예약 정보를 안내",
      "exclusion": "예약한 서비스의 이용안내는 서비스 이용안내(004001)로 분류 합니다."
    }
  ]
}
```

> 주의
> - 카테고리 코드는 템플릿 생성 시 필수다. 6자리이며 그룹 코드와 세부 코드로 구분된다.
> - 포함/제외 예시를 보고 맞는 카테고리를 골라야 한다.

## 2. 카카오 카테고리 정보 리스트

`POST /kko/v2/channel/category/all` — 카카오 채널 등록(#13)에 필요한 **채널** 카테고리 목록을 조회한다. 요청 본문은 없다.

응답 data (Array)

| 필드 | 타입 | 설명 |
|---|---|---|
| data[].code | String | 카테고리 코드(예: `00100010001`, 11자리) |
| data[].name | String | 카테고리 정보(예: `건강,병원,종합병원`) |

> 주의: #1 의 템플릿 카테고리(6자리)와 다른 코드 체계다. 채널 등록의 `categoryCode` 에는 이 목록의 값을 쓴다.

## 3. 카카오 채널로 그룹 목록 조회

`POST /kko/v2/channel/group/list` — 특정 카카오 채널이 속한 그룹들을 조회한다.

Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| kkoChId | String | ● | 61자 | 카카오 채널 ID |

응답 data (Array)

| 필드 | 타입 | 설명 |
|---|---|---|
| data[].chGrpKey | String | 채널 그룹 키 |
| data[].chGrpName | String | 채널 그룹 이름 |
| data[].regDt | String | 채널 그룹 등록일시 |

```json
{ "kkoChId": "@myservice" }
```

## 4. 카카오 그룹에 채널 등록

`POST /kko/v2/channel/group/add` — 기존 그룹에 채널을 추가한다.

Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| chGrpKey | String | ● | - | 채널 그룹 고유 키 |
| kkoChId | String | ● | 61자 | 카카오 채널 ID |

응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| data.chGrpKey | String | 채널 그룹 고유 키 |
| data.kkoChId | String | 카카오 채널 ID |

```json
{ "chGrpKey": "GROUP_001", "kkoChId": "@myservice" }
```

> 주의
> - 이미 그룹에 등록된 채널은 중복 등록할 수 없다.
> - 등록 후 #5(그룹에 포함된 채널 조회)로 반영 여부를 확인할 수 있다.

## 5. 카카오 그룹에 포함된 채널 조회

`GET /kko/v2/channel/group/{groupKey}` — 그룹에 속한 채널 목록을 조회한다.

Path

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| groupKey | String | ● | 조회할 채널 그룹 키 |

응답 data (Array)

| 필드 | 타입 | 설명 |
|---|---|---|
| data[].chGrpKey | String | 채널 그룹 고유 키 |
| data[].kkoChId | String | 카카오 채널 ID |
| data[].regDt | String | 등록일시 |

## 6. 카카오 그룹 목록 조회

`GET /kko/v2/channel/group/all` — 전체 카카오 채널 그룹 목록을 조회한다. 요청 파라미터는 없다.

응답 data (Array)

| 필드 | 타입 | 설명 |
|---|---|---|
| data[].chGrpKey | String | 채널 그룹 키 |
| data[].chGrpName | String | 채널 그룹 이름 |
| data[].chGrpStatCd | Number | 채널 그룹 상태 코드(요청 R / 승인 A / 거절 C) |
| data[].regDt | String | 생성일시 |
| data[].updDt | String | 수정일시(예시에서 `null` 가능) |

> 원문 확인 필요: `chGrpStatCd` 타입이 Number 로 적혀 있으나 값은 문자 `R`/`A`/`C` 이고 예시도 문자열이다.

## 7. 카카오 그룹에서 채널 삭제

`DELETE /kko/v2/channel/group/remove` — 그룹에서 채널을 제거한다. DELETE 이지만 파라미터를 JSON 본문으로 보낸다.

Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| chGrpKey | String | ● | - | 채널 그룹 고유 키 |
| kkoChId | String | ● | - | 카카오 채널 ID |

응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| data.chGrpKey | String | 채널 그룹 고유 키 |
| data.kkoChId | String | 카카오 채널 ID |

> 주의: 그룹에서 빼도 채널 자체는 삭제되지 않는다.

## 8. 고객사 카카오 채널 기간별 조회

`POST /kko/v2/kkoChannelList` — 기준 일시 이후에 등록된 카카오 채널 목록을 조회한다.

Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| standardDateTime | String | ● | 14자 | 검색 기준 일시(`YYYYMMDDHHMMSS`) |
| page | Integer | - | - | 페이지 번호 |
| pageSize | Integer | - | - | 페이지 크기 |

응답 data (Array)

| 필드 | 타입 | 설명 |
|---|---|---|
| data[].kkoChId | String | 카카오 채널 ID |
| data[].kkoChStat | String | 채널 상태: A 활성화 / C 비활성화 / B 차단 / E 삭제 중 / D 삭제됨 |
| data[].createDate | String | 등록 일자(`YYYY-MM-DD HH:MM:SS`) |
| data[].categoryCode | String | 카테고리 코드 |

```json
{ "standardDateTime": "20240912000000", "page": 1, "pageSize": 1000 }
```

> 주의
> - 원문 설명은 "특정 기간 동안 등록된 채널"이지만 요청에는 기준 일시 하나만 있다. 기준 일시 이후인지 이전인지, 종료 시점은 어떻게 정해지는지 원문에 없다. 원문 확인 필요.
> - `page`·`pageSize` 를 생략했을 때의 기본값·최대값은 원문에 없다(예시는 1, 1000).
> - 상태 코드 체계가 #12(A 정상 / B 차단 / P 휴면 / D 삭제)와 다르다.

## 9. 알림톡 인증 토큰 요청

`POST /kko/v2/channel/token` — 알림톡 채널 등록(#13)에 필요한 인증 토큰(인증번호)을 플러스친구 관리자 단말로 보낸다.

Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| phoneNumber | String | ● | 최대 11자 | 플러스친구 관리자 번호(숫자만) |
| kkoChId | String | ● | 최대 61자 | 카카오채널 검색용 ID |
| relay | String | ● | - | 카카오채널 등록 relay ID(LGCNS, LMESSAGE, MTS, r01, r02, …) |

응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| data.phoneNumber | String | 플러스친구 관리자 번호 |
| data.yellowId | String | 카카오 채널 ID |
| data.kkoChId | String | 카카오 채널 ID |
| data.relay | String | 카카오채널 등록 relay ID |

```json
{ "phoneNumber": "01000000000", "kkoChId": "@myservice", "relay": "r01" }
```

> 주의
> - 사용 가능한 relay ID 는 #10 으로 조회한다.
> - 원문 확인 필요: 요청 예시의 relay 는 `LGCNS`, 응답 예시는 `r01` 이라 입력 relay 와 응답 relay 의 대응 관계가 불명확하다.

## 10. 알림톡 채널등록 사전정보 요청

`POST /kko/v2/channel/relayinfo` — 채널 등록에 쓸 수 있는 relay ID 목록을 받는다. 요청 본문은 없다.

응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| data.relay | Array | 사용 가능한 relay ID 목록(예: `["r01", "r02"]`) |

## 11. 미사용 프로필 휴면 해제

`POST /kko/v2/channel/recover` — 장기 미사용으로 휴면 상태가 된 카카오 채널 프로필을 활성화한다.

Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| kkoChId | String | ● | 최대 61자 | 카카오채널 검색용 ID |

응답은 `code`·`message` 만 있다.

## 12. 카카오 채널 조회

`POST /kko/v2/channel/get` — 등록된 카카오 채널의 상세 정보를 조회한다.

Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| kkoChId | String | ● | 최대 61자 | 카카오 채널 ID |

응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| data.kkoChId | String | 카카오 채널 ID |
| data.stat | String | 상태: A 정상 / B 차단 / P 휴면 / D 삭제 |
| data.createDate | String | 생성 일자 |
| data.categoryCode | String | 카테고리 코드 |

## 13. 카카오 채널 등록

`POST /kko/v2/channel/create` — 카카오 채널을 msghub 에 등록한다. 채널 자체의 생성은 카카오비즈센터에서 따로 해야 한다.

Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| tokens | Array | ● | - | relay 토큰 정보 |
| tokens[].rid | String | ● | - | relay ID |
| tokens[].token | Integer | ● | - | 인증 코드(#9 로 받은 번호) |
| tokens[].phoneNumber | String | ● | 11자 | 플러스친구 관리자 번호 |
| categoryCode | String | ● | 11자 | 카테고리 코드(#2 목록의 값) |
| kkoChId | String | ● | 61자 | 카카오채널 검색용 ID |
| memo | String | - | - | 메모 |

예시

```json
{
  "tokens": [
    { "rid": "r01", "token": 888999, "phoneNumber": "01000000000" }
  ],
  "categoryCode": "01800040001",
  "kkoChId": "@myservice",
  "memo": "비즈니스 채널"
}
```

응답은 `code`·`message` 만 있다.

> 주의: 등록 절차는 #10(relay 확인) → #9(인증 토큰 요청) → #13(등록) 순서로 이어지는 구조다(원문은 순서를 명시하지 않고 필드 설명으로 연결됨).

## 14. 템플릿 (재)검수요청

`POST /kko/v2/channel/template/request` — 템플릿 검수를 요청한다.

Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| kkoChId | String | - | 최대 61자 | 카카오채널 ID. 단일 채널이면 필수 |
| kkoGrpId | String | - | 최대 100자 | 카카오그룹 ID. 그룹 채널이면 필수 |
| templateCode | String | ● | 30자 | 템플릿 코드(공백 불가) |
| senderKeyType | String | - | 1자 | 채널 유형 S 일반 / G 그룹(기본 S) |
| comment | String | - | 500자 | 의견·문의사항 |

예시(단일 채널 / 그룹 채널)

```json
{ "kkoChId": "@myservice", "templateCode": "template_code_123", "senderKeyType": "S", "comment": "검수요청" }
```

```json
{ "kkoGrpId": "GrpKey", "templateCode": "template_code_123", "senderKeyType": "G", "comment": "검수요청" }
```

> 주의
> - 템플릿 상태가 `T`(등록완료)일 때만 요청할 수 있다. 내부승인 고객은 수정 후 반려(S) 상태여도 요청할 수 있다.

## 15. 템플릿 삭제

`POST /kko/v2/channel/template/delete` — 템플릿을 삭제한다.

Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| kkoChId | String | - | 최대 61자 | 카카오채널 ID. 단일 채널이면 필수 |
| kkoGrpId | String | - | 최대 100자 | 카카오그룹 ID. 그룹 채널이면 필수 |
| templateCode | String | ● | 최대 30자 | 템플릿 코드(공백 불가) |
| senderKeyType | String | - | 1자 | 채널 유형 S 일반 / G 그룹(기본 S) |
| comment | String | - | 500자 | 의견·문의사항 |

> 주의
> - 상태가 `T` 인 템플릿만 삭제할 수 있다.
> - 삭제한 템플릿은 API 로 조회할 수 없다.

## 16. 템플릿 문의하기

`POST /kko/v2/channel/template/comment` — 템플릿에 대한 문의(댓글)를 등록한다. 예: 반려 의견 문의.

Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| kkoChId | String | - | 최대 61자 | 카카오채널 ID. 단일 채널이면 필수 |
| kkoGrpId | String | - | 최대 100자 | 카카오그룹 ID. 그룹 채널이면 필수 |
| templateCode | String | ● | 최대 30자 | 템플릿 코드(공백 불가) |
| senderType | String | - | 1자 | 채널 유형 S 일반 / G 그룹(기본 S) |
| comment | String | ● | 최대 500자 | 문의 내용 |

## 17. 템플릿 목록 조회

`POST /kko/v2/channel/template/all` — 채널(또는 그룹)의 템플릿 목록을 조회한다.

Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| kkoChId | String | - | 최대 61자 | 카카오채널 ID. 단일 채널이면 필수 |
| kkoGrpId | String | - | 최대 100자 | 카카오그룹 ID. 그룹 채널이면 필수 |
| senderType | String | ● | 1자 | 발신프로필 유형 S 카카오채널(기본) / G 그룹 |
| updateDt | String | - | 14자 | 최종 갱신 일시(`YYYYMMDDHHMMSS`). 생략하면 전체 조회 |

응답 data (Array)

| 필드 | 타입 | 설명 |
|---|---|---|
| data[].kkoChId | String | 카카오 채널 ID |
| data[].templateName | String | 템플릿명 |
| data[].templateKey | String | 템플릿키 |
| data[].templateCode | String | 템플릿 코드 |
| data[].templateStatusCode | String | 템플릿 상태 코드(공통 개념 참고) |

```json
{ "kkoChId": "@myservice", "senderType": "S", "updateDt": "20230201120000" }
```

> 주의: 원문 설명은 "승인된 템플릿 목록"이지만 응답 예시에는 검수 중(`R`) 템플릿도 포함되어 있다. 원문 확인 필요: 승인(A) 템플릿만 나오는지 전 상태가 나오는지.

## 18. 템플릿 생성

`POST /kko/v2/channel/template/create` — 알림톡 템플릿을 만든다. 이미지가 없으면 `application/json`, 이미지가 있으면 `multipart/form-data` 로 보낸다. 템플릿 유형(메시지 유형·강조 유형)에 따라 필요한 필드가 다르다.

Body (multipart 일 때의 필드)

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| reqBody | Object(JSON 문자열) | ● | 템플릿 생성 요청 정보. 아래 표. JSON 요청이면 이 필드들을 본문 최상위에 직접 둔다 |
| image | binary | - | 알림톡 이미지(이미지형) 파일 |
| itemHighlightImage | binary | - | 아이템 하이라이트 이미지 파일 |

reqBody 객체

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| kkoChId | String | - | 최대 61자 | 카카오채널 ID. 단일 채널이면 필수 |
| kkoGrpId | String | - | 최대 100자 | 카카오그룹 ID. 그룹 채널이면 필수 |
| senderType | String | ● | 1자 | 발신프로필 유형 S 카카오채널(기본) / G 그룹 |
| templateCode | String | - | 최대 30자 | 템플릿 코드(공백 불가). 응답 예시에서는 생략 시 `templateKey` 와 같은 값이 채워짐 |
| templateName | String | ● | 최대 200자 | 템플릿명 |
| templateContent | String | ● | 최대 1000자 | 템플릿 내용 |
| categoryCode | String | ● | 최대 6자 | 템플릿 카테고리 코드(#1) |
| templateMessageType | String | ● | 2자 | BA / EX / AD / MI |
| templateExtra | String | - | 최대 500자 | 부가정보(EX·MI 에서 필수) |
| templateAd | String | - | 1000자 | 광고성 메시지(templateContent 글자수에 포함). AD·MI 에서 고정 문구 입력 |
| templateEmphasizeType | String | ● | 최대 9자 | NONE / TEXT / IMAGE / ITEM_LIST |
| itemHeader | String | - | 최대 16자 | 아이템리스트형 헤더 |
| itemHighlightTitle | String | - | 최대 30자 | 아이템 하이라이트 타이틀(썸네일 이미지 사용 시 21자 제한) |
| itemHighlightDescription | String | - | 최대 19자 | 아이템 하이라이트 설명(썸네일 이미지 사용 시 13자 제한, 타이틀 설정 시 필수) |
| itemList | Array | - | 2~10개 | 아이템리스트. 항목은 `title`, `description` (ITEM_LIST 에서 필수) |
| itemSummaryTitle | String | - | 최대 6자 | 아이템 요약 정보 타이틀(itemList 입력 시에만 사용) |
| itemSummaryDescription | String | - | 최대 14자 | 아이템 요약 정보 설명(itemList 입력 시에만 사용) |
| templateTitle | String | - | - | 강조표기 핵심 정보(TEXT 에서 필수) |
| templateSubtitle | String | - | - | 강조표기 보조 문구(TEXT 에서 필수) |
| securityFlag | Boolean | - | - | 보안 템플릿 여부(보안 메시지면 true). 원문 길이 표기는 "최대 5자"(true/false 문자 수로 추정) |
| buttons | Array | - | 최대 5개 | 템플릿 버튼 목록 |
| templatePreviewMessage | String | - | 40자 | 템플릿 미리보기 메시지 |

응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| data.templateKey | String | 템플릿키(유일키) |
| data.templateCode | String | 템플릿 코드 |
| data.templateName | String | 템플릿명 |
| data.kkoChId | String | 카카오채널 검색용 ID |
| data.regDt | String | 등록일시 |
| data.updDt | String | 최종 갱신일시 |
| data.templateInfo | Object | 템플릿 상세 정보. 필드는 아래 [템플릿 상세 정보 필드](#템플릿-상세-정보-필드) |

예시: 강조 없는 기본형(NONE) — 이미지형(IMAGE)은 이미지 파일 등록이 필요

```json
{
  "kkoChId": "@myservice",
  "senderType": "S",
  "templateName": "환영인사",
  "templateContent": "#{이름}님 환영합니다..",
  "templatePreviewMessage": "미리보기 메시지",
  "categoryCode": "008002",
  "templateMessageType": "BA",
  "templateEmphasizeType": "NONE",
  "securityFlag": false,
  "buttons": [
    { "name": "사용량 제한 이용안내", "linkType": "WL", "linkMo": "http://m.example.com", "linkPc": "http://www.example.com" }
  ]
}
```

유형별로 달라지는 부분

| 유형 | 달라지는 필드 |
|---|---|
| 강조표기형(`templateEmphasizeType=TEXT`) | `templateTitle`, `templateSubtitle` 필수 |
| 아이템리스트형(`ITEM_LIST`) | `itemList` 필수. `itemHeader`·`itemHighlightTitle`·`itemHighlightDescription` 사용 가능, `itemSummaryTitle`·`itemSummaryDescription` 은 `itemList` 가 있을 때만 |
| 부가정보형(`templateMessageType=EX`) | `templateExtra` 필수 |
| 광고형(`AD`) | `templateAd` 에 고정 문구 `채널 추가하고 이 채널의 광고와 마케팅 메시지를 카카오톡으로 받기` 입력, `buttons` 첫 번째 버튼은 채널추가형(`{"name":"채널 추가","linkType":"AC"}`) 필수 |
| 복합형(`MI`) | `templateExtra` 필수 + 광고형 규칙(`templateAd`, 첫 버튼 채널추가형) |

멀티파트 예시(이미지 포함)

```bash
curl -X POST "https://mnt-api.msghub.uplus.co.kr/kko/v2/channel/template/create" \
  -H "Authorization: Bearer {token}" \
  -F 'reqBody={"kkoChId":"@myservice","senderType":"S","templateName":"환영인사 템플릿","templateContent":"#{이름}님 환영합니다..","categoryCode":"008002","templateMessageType":"BA","templateEmphasizeType":"IMAGE"}' \
  -F "image=@300x300.png;type=image/png" \
  -F "itemHighlightImage=@300x300.png;type=image/png"
```

> 주의
> - `buttons` 항목 필드(`name`, `linkType`, `linkMo`, `linkPc` 등)와 `linkType` 값은 공통 개념의 버튼 타입 표 참고. 링크 타입별 필수 필드는 원문에 요청 표가 없다. 원문 확인 필요.
> - 원문 확인 필요: 이미지 파일의 형식·크기·해상도 제한(원문에 수치 없음. 예시는 300x300 PNG).
> - 원문 예시에서 AD·MI 예시에 `regId: "-"` 가 포함되어 있으나 요청 필드 표에는 없다.
> - 원문 예시는 `categoryCode` 가 6자리(`008002`)인데 채널 등록(#13)은 11자리다. 용도가 다른 코드(#1 vs #2)다.

## 19. 템플릿 수정

`POST /kko/v2/channel/template/update` — 기존 템플릿을 수정한다. 요청 형식은 #18 과 같고(이미지 유무에 따라 JSON/multipart), `reqBody` 에 `templateTitleFixYn` 필드가 하나 더 있다. 원문 표의 `reqBody` 설명이 "템플릿 생성 요청 정보"로 적혀 있는 것은 복사 잔재로 보인다.

추가 필드

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| templateTitleFixYn | String | - | 1자 | 강조표기형 사용 시 본문의 가변 영역과 별개로 쓸 수 있는 구분값(LG CNS 전용) |

나머지 필드(`kkoChId`, `kkoGrpId`, `senderType`●, `templateCode`, `templateName`●, `templateContent`●, `categoryCode`●, `templateMessageType`●, `templateEmphasizeType`●, 아이템·강조·버튼 관련 필드, `securityFlag`, `templatePreviewMessage`)는 #18 의 reqBody 표와 같다(필수 표시·길이 동일). 이미지는 `image`, `itemHighlightImage` 파일 필드로 보낸다.

예시

```json
{
  "kkoChId": "@myservice",
  "senderType": "S",
  "templateName": "환영인사 템플릿",
  "templateContent": "#{이름}님 환영합니다..",
  "categoryCode": "008002",
  "templateMessageType": "BA",
  "templateEmphasizeType": "NONE",
  "buttons": [
    { "name": "사용량 제한 이용안내", "linkType": "WL", "linkMo": "http://m.example.com", "linkPc": "http://www.example.com" }
  ]
}
```

응답은 `code`·`message` 만 있다.

> 주의
> - 상태가 등록완료(`T`) 또는 반려(`S`)일 때만 수정할 수 있다.
> - 템플릿 코드와 카테고리 코드는 수정할 수 없다.
> - 버튼은 부분 수정이 아니라 전체 교체(추가·삭제 포함)로 수정한다.
> - 내부승인 고객은 수정 후 검수요청(#14)까지 진행해야 한다.
> - 원문 확인 필요: 수정 대상을 식별하는 필드. 표에는 `templateCode` 가 필수 아님(`-`)으로 되어 있고 수정 예시에도 없다. 실제로는 `templateCode` 가 있어야 대상을 특정할 수 있을 것으로 보이나 원문에 명시가 없다.
> - 원문 확인 필요: 수정 예시에 `categoryCode` 가 포함되는데 수정 불가라고 적혀 있다(값이 기존과 같아야 하는지 등).

## 20. 템플릿 조회

`POST /kko/v2/channel/template/get` — 템플릿 한 건의 상세를 조회한다. 승인·미승인 템플릿 모두 조회되며 msghub 기준 정보다.

Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| kkoChId | String | - | 최대 61자 | 카카오채널 ID. 단일 채널이면 필수 |
| kkoGrpId | String | - | 최대 100자 | 카카오그룹 ID. 그룹 채널이면 필수 |
| templateCode | String | ● | 최대 30자 | 템플릿 코드(공백 불가) |
| senderKeyType | String | - | 1자 | 채널ID 유형 S 일반 / G 그룹(기본 S) |

응답 data 는 #18 의 응답과 같은 구조다(`templateKey`, `templateCode`, `templateName`, `kkoChId`, `templateInfo`, `regDt`, `updDt`). #18 과 달리 `templateInfo.itemHighlightTitle`, `templateInfo.itemHighlightDescription` 이 응답 표에 추가로 있다.

```json
{ "kkoChId": "@myservice", "templateCode": "ABcD82uK8x", "senderKeyType": "S" }
```

---

## 템플릿 상세 정보 필드

#18(생성)·#20(조회) 응답의 `data.templateInfo`. 표기는 `templateInfo.` 를 뺀 상대 경로.

| 필드 | 타입 | 설명 |
|---|---|---|
| senderKey | String | 발신프로필 키 |
| senderType | String | 발신프로필 유형(S/G) |
| templateCode | String | 템플릿 코드 |
| kkoTemplateCode | String | 카카오 템플릿 코드 |
| templateName | String | 템플릿명 |
| templateContent | String | 템플릿 내용 |
| categoryCode | String | 카테고리 코드 |
| templateMessageType | String | 메시지 유형(BA/EX/AD/MI) |
| templateEmphasizeType | String | 강조표기 유형(NONE/TEXT/IMAGE/ITEM_LIST) |
| templateTitle | String | 강조표기 핵심 정보 |
| templateSubtitle | String | 강조표기 보조 문구 |
| templateStatusCode | String | 템플릿 상태(T/R/Q/A/S) |
| block | boolean | 차단 여부(true 차단, false 차단해제) |
| dormant | boolean | 휴면 여부(true 휴면, false 휴면해제) |
| createId | String | 생성자 ID |
| createDate | String | 생성 일자 |
| approvalDate | String | 검수 일자 |
| comments | Array | 댓글 목록 |
| comments[].idx | String | 댓글 ID |
| comments[].createId | String | 작성자 |
| comments[].content | String | 내용 |
| comments[].createDate | String | 등록일 |
| comments[].status | String | 댓글 상태(INQ 문의/APR 승인/REJ 반려/REP 답변) |
| templateKey | String | 템플릿키 |
| relay | String | 중계사 정보 |
| itemHighlightTitle | String | 아이템 하이라이트 타이틀(#20 응답 표에만 있음) |
| itemHighlightDescription | String | 아이템 하이라이트 설명(#20 응답 표에만 있음) |
| imageFileName | String | 이미지 파일명 |
| itemHighlightImageFileName | String | 아이템 하이라이트 이미지 파일명 |
| templateTitleFixYn | String | 템플릿 타이틀 고정 여부 |
| item | Object | 아이템 정보 |
| item.list[].title | String | 아이템리스트 타이틀 |
| item.list[].description | String | 아이템리스트 설명 |
| item.summary.title | String | 아이템 요약정보 타이틀 |
| item.summary.description | String | 아이템 요약정보 설명 |
| regId | String | 등록자 ID |
| templateExtra | String | 부가정보 |
| templateAd | String | 광고성 메시지 |
| templatePreviewMessage | String | 템플릿 미리보기 메시지 |
| buttons[].name | String | 버튼 이름 |
| buttons[].linkType | String | 버튼 타입 |
| buttons[].linkMo | String | 모바일 환경에서 클릭 시 이동할 URL |
| buttons[].linkPc | String | PC 환경에서 클릭 시 이동할 URL |
| buttons[].linkAnd | String | 안드로이드에서 실행할 앱 custom scheme |
| buttons[].linkIos | String | iOS 에서 실행할 앱 custom scheme |
| buttons[].ordering | Integer | 버튼 노출 순서 |
| buttons[].varUrlYn | String | URL 가변 값 포함 여부 |
| buttons[].kkoBtnOutbrowserYn | String | 클릭 시 URL 이 열리는 브라우저 설정 |
| buttons[].chat_extra | String | 봇 관련 정보(type BC, BT) |
| buttons[].chat_event | String | 봇 관련 이벤트 정보(type BT) |

> 원문 확인 필요: 응답 예시에는 `securityFlag` 가 있으나 응답 필드 표에는 없다.

## 결과 코드

원문은 결과 코드 표를 별도 페이지로 연결한다. 이 문서에는 옮기지 않았다.
