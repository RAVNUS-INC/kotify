# msghub 통합발송 템플릿 관리 API

> 출처: msghub API 가이드 > 통합발송 연동관리
> 최종 업데이트: 2026-02-23

콘솔에서 등록한 채널별 템플릿(SMS/LMS/MMS/RCS/알림톡/친구톡/푸시/스마트)을 API로 조회한다.
발송 자체는 `/msg/v1.1/send` (통합발송) 에서 `tmpltCode` 로 참조.

---

## 공통

- **Base URL**: `https://api.msghub.uplus.co.kr`
- **인증**: `Authorization: Bearer {token}` — `/auth/v1/{randomStr}` 로 발급
- **Content-Type**: `application/json`

---

## 1. 템플릿 목록 조회

```
GET /msg/v1/template/all
Authorization: Bearer {token}
```

### Request

| 파라미터 | Type | Required | 설명 |
|---------|------|----------|------|
| `ch` | String | Y | 채널 (`mms` / `rcs` / `alimtalk` / `friendtalk` / `push` / `smart`) |
| `listCnt` | Integer | Y | 조회할 템플릿 목록 수 (1, 10, ...) |
| `pageIdx` | Integer | Y | 페이지 번호 (1, 2, 3, ...) |

### Response

| 필드 | Type | 설명 |
|------|------|------|
| `code` | String | 결과 코드 |
| `message` | String | 결과 코드 설명 |
| `data[].tmpltId` | String | 템플릿 ID |
| `data[].tmpltName` | String | 템플릿 이름 |
| `data[].senderType` | String | 발송 유형 (발송 채널) |
| `data[].msgKind` | String | 메시지 구분 (RCS는 정보성/광고성) |
| `data[].msgType` | String | 메시지 타입 (default `1`) |
| `data[].tmpltStatus` | String | 템플릿 승인 상태 |
| `data[].regDt` | String | 등록 일자 |
| `data[].updDt` | String | 최종 수정 일자 |

### 샘플

**Request:**
```bash
curl -X GET "https://api.msghub.uplus.co.kr/msg/v1/template/all?ch=mms&listCnt=1&pageIdx=1" \
  -H "Authorization: Bearer {token}"
```

**Response:**
```json
{
  "code": "10000",
  "message": "성공",
  "data": [
    {
      "tmpltId": "TPLqlWWqL9",
      "tmpltName": "fdsfdsfsdf",
      "senderType": "SMS",
      "msgKind": "",
      "msgType": "",
      "tmpltStatus": "완료",
      "regDt": "2022-09-29 10:34:01",
      "updDt": "2022-09-29 10:34:01"
    }
  ]
}
```

---

## 2. 템플릿 상세 팝업 (웹 화면)

```
GET /msg/v1/template/detailPop
Authorization: Bearer {token}
```

콘솔의 템플릿 상세 내용을 웹 팝업으로 띄운다. 프로그램 연동보다 **운영자 조작용**.

### Request

| 파라미터 | Type | Required | 설명 |
|---------|------|----------|------|
| `ch` | String | Y | 채널 |
| `tmpltId` | String | Y | 템플릿 ID |

### 샘플

```bash
curl -X GET "https://api.msghub-qa.uplus.co.kr/msg/v1/template/detailPop?ch=mms&tmpltId=1"
```

---

## 3. 템플릿 상세 조회 (API)

```
GET /msg/v1/template/get
Authorization: Bearer {token}
```

프로그램 연동용. JSON으로 템플릿 구성 정보를 반환한다.

### Request

| 파라미터 | Type | Required | 설명 |
|---------|------|----------|------|
| `tmpltId` | String | Y | 통합 템플릿 ID |

### Response

| 필드 | Type | 설명 |
|------|------|------|
| `data.tmpltCode` | String | 템플릿 코드 |
| `data.msgKind` | String | 메시지 종류 |
| `data.msgType` | String | 메시지 유형 |
| `data.tmpltTitle` | String | 템플릿 제목 |
| `data.tmpltInfo[]` | Object | 채널별 정보 |
| `data.tmpltInfo[].ch` | String | 채널 |
| `data.tmpltInfo[].data.msg` | String | 메시지 내용 |
| `data.tmpltInfo[].data.callback` | String | 발신번호 |

### 샘플

**Request:**
```bash
curl -X GET "https://api.msghub.uplus.co.kr/msg/v1/template/get?tmpltId=TPL1IY6GGW" \
  -H "Authorization: Bearer {token}"
```

**Response:**
```json
{
  "code": "10000",
  "message": "성공",
  "data": {
    "tmpltCode": "TPL1IY6GGW",
    "msgKind": "I",
    "msgType": "BASE",
    "tmpltTitle": "통합발송 머지O",
    "tmpltInfo": [
      {
        "ch": "SMS",
        "data": {
          "msg": "#{고객}님, 확인합니다",
          "callback": "0269496227"
        }
      }
    ]
  }
}
```

---

## 이 앱에서의 활용 포인트 (참고)

현재 이 앱은 **템플릿 기반 발송을 쓰지 않고** 직접 발송 API를 호출한다:
- `/msg/v1/sms` — SMS
- `/msg/v1/mms` — LMS/MMS
- `/rcs/v1.1` — RCS 단방향 (장문/이미지)
- `/rcs/bi/v1.1` — RCS 양방향 CHAT

**템플릿 API가 필요해지는 시점:**
1. **채널별 폴백 체인을 콘솔에서 관리**하고 싶을 때 (현재는 코드에 하드코딩)
2. **변수 치환 메시지(`#{이름}`)를 재사용**하고 싶을 때
3. **RCS 카드/버튼/이미지 양식을 콘솔에서 설계**해서 앱은 `tmpltCode`만 참조하고 싶을 때
4. **발송 감사(audit)/정산에서 템플릿 단위 집계**가 필요할 때

해당 필요가 생기면:
- `/msg/v1.1/send` (통합발송 API) 호출 경로를 `app/msghub/client.py` 에 추가
- `tmpltCode` 를 campaigns 테이블에 저장
- 콘솔에서 템플릿 관리 → 앱은 `tmpltCode` + `kvData` + `recvInfoLst` 만 보냄
