# 2.1 인증
> 원문: https://doc.msghub.uplus.co.kr/rest-api/02메시지발송/0201auth/ · 확인일 2026-10-16

API 규격은 OpenAPI 3.0.1, 인증은 JWT Bearer 방식이다. 모든 API 호출 전에 apiKey/apiPwd 로 토큰을 발급받고, 만료 전에 refresh 토큰으로 갱신한다.

## 한눈에 보기

| 기능 | Method | 경로 | 호스트 |
|---|---|---|---|
| 인증 요청(토큰 발급) | POST | `/auth/v1/{randomStr}` | api |
| 인증 갱신 | PUT | `/auth/v1/refresh` | api |

## 공통 개념

### Bearer 인증 헤더
발급받은 토큰은 이후 모든 API 요청에 아래 헤더로 보낸다. 기본 요청은 `Content-Type: application/json` 이며, 파라미터는 경로·쿼리·JSON 본문 중 엔드포인트가 정한 방식으로 전달한다.

```
Authorization: Bearer {token}
Content-Type: application/json
```

### 토큰 수명과 사전 갱신

| 구분 | 만료 시간 | 사전 갱신 권장 시점 |
|---|---|---|
| Token | 발급 1시간 후 | 만료 10분 전 |
| Refresh Token | 발급 25시간 후 | 만료 30분 전 |

## 인증 요청(토큰 발급)

`POST /auth/v1/{randomStr}` — apiKey 와 암호화한 apiPwd 로 token, refreshToken 을 발급받는다.

요청 Path

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| randomStr | String | ● | 최대 20 | 임의 문자열. 영문자·숫자·`-`·`_` 조합 |

요청 Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| apiKey | String | ● | 최대 20 | API 키 |
| apiPwd | String | ● | - | API 패스워드. 아래 공식으로 암호화한 값 |

응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| token | String | 접근 토큰(JWT) |
| refreshToken | String | 갱신용 토큰(JWT) |

예시

```json
// POST /auth/v1/abc123_XYZ
{
  "apiKey": "API_KEY_EXAMPLE",
  "apiPwd": "{encrypted_apiPwd}"
}
```

```json
{
  "code": "10000",
  "message": "성공",
  "data": { "token": "{token}", "refreshToken": "{refreshToken}" }
}
```

> 주의
> - apiPwd 암호화 공식: `SHA512.encryptToBase64( SHA512.encryptToBase64(apiPwd) + "." + randomStr )`. 즉 평문을 SHA-512 해시 후 Base64 한 값에 `.` 과 경로의 randomStr 을 이어 붙여 다시 SHA-512 해시 후 Base64 한다. 경로의 randomStr 과 공식의 randomStr 은 같은 값이어야 한다.
> - 같은 아이디로 여러 번 인증하면 토큰이 각각 발급되고, 각 토큰은 자기 만료 시각까지 독립적으로 쓸 수 있다.
> - 원문 확인 필요: SHA-512 결과의 Base64 인코딩이 표준 Base64 인지, 해시 입력 문자 인코딩(UTF-8 여부)은 원문에 명시가 없다.

## 인증 갱신

`PUT /auth/v1/refresh` — Refresh Token 으로 새 token 을 발급받는다. 요청 본문은 없다.

요청 Header

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| Authorization | String | ● | `Bearer {refreshToken}` — 일반 token 이 아니라 Refresh Token 을 넣는다 |

응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| token | String | 새로 발급된 접근 토큰 |

예시

```bash
curl -X PUT https://api.msghub.uplus.co.kr/auth/v1/refresh \
  -H "Authorization: Bearer {refreshToken}"
```

> 주의
> - IP 제약: refresh 토큰에 기록된 ipAddr 과 갱신을 요청하는 서버의 ipAddr 이 같아야 한다. 토큰을 발급받은 서버와 다른 IP 에서 refresh 하면 실패한다고 봐야 한다(원문은 "동일해야 한다"고만 서술).
> - Refresh Token 이 갱신되더라도, 그 토큰으로 이미 갱신해 둔 인증 토큰은 만료 시간까지 계속 쓸 수 있다.
> - 안정 운영을 위해 Token 은 만료 10분 전, Refresh Token 은 만료 30분 전에 미리 갱신하길 권장한다(위 표).
> - 원문 확인 필요: 응답에 refreshToken 은 없고 token 만 온다. Refresh Token 자체를 연장하는 방법은 원문에 없다(만료 시 재인증 추정).
> - 원문 확인 필요: 원문 "결과 코드" 절은 별도 페이지(2.9 결과코드) 링크뿐이라 인증 관련 오류 코드는 이 문서에서 확인할 수 없다.
