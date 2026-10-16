# 3.1 채널 관리 인증
> 원문: https://doc.msghub.uplus.co.kr/rest-api/03채널/0301mnt-auth/ · 확인일 2026-10-16

채널 관리 API(`mnt-api` 호스트)를 호출하기 전에 클라이언트 인증으로 JWT 접근 토큰을 받는다. 토큰은 일정 시간 뒤 만료되므로 갱신 API 로 연장한다. 규격은 OpenAPI 3.0.1, 인증 방식은 HTTP Bearer(JWT).

## 한눈에 보기

| 기능 | Method | 경로 | 호스트 |
|---|---|---|---|
| 인증 요청(토큰 발급) | POST | `/auth/v1/{randomStr}` | mnt-api |
| 인증 갱신 | PUT | `/auth/v1/refresh` | mnt-api |

## 공통 요청 규칙

모든 요청은 아래 헤더를 쓴다. 파라미터는 경로·쿼리·JSON 본문 중 엔드포인트가 정한 방식으로 전달한다.

```
Authorization: Bearer {token}
Content-Type: application/json
```

## 인증 요청(토큰 발급)

`POST /auth/v1/{randomStr}` — API 키와 암호화한 패스워드로 접근 토큰(`token`)과 갱신 토큰(`refreshToken`)을 발급받는다.

Path

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| randomStr | String | ● | 최대 20자 | 임의 문자열(영문자, 숫자, `-`, `_` 조합). 패스워드 암호화에도 쓰인다 |

Body

| 필드 | 타입 | 필수 | 길이 | 설명 |
|---|---|---|---|---|
| apiKey | String | ● | 최대 20자 | API 키 |
| apiPwd | String | ● | - | API 패스워드(암호화 후 전송) |

`apiPwd` 암호화 방식:

```
SHA512.encryptToBase64( SHA512.encryptToBase64(apiPwd) + "." + randomStr )
```

응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| token | String | 접근 토큰(JWT) |
| refreshToken | String | 갱신 토큰(JWT) |

예시

```json
{
  "apiKey": "API_KEY_EXAMPLE",
  "apiPwd": "{SHA512 암호화된 값}"
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
> - `randomStr` 는 암호화 식에 그대로 들어가므로 경로에 쓴 값과 암호화에 쓴 값이 같아야 한다.
> - 원문은 SHA512 base64 의 정확한 구현(바이트 인코딩 등)을 설명하지 않는다. 원문 확인 필요: 암호화 입력 문자열 인코딩(UTF-8 여부).
> - 토큰 만료 시간(초)은 원문에 수치가 없다. 원문 확인 필요.

## 인증 갱신

`PUT /auth/v1/refresh` — `Authorization` 헤더에 유효한 **Refresh Token** 을 넣어 새 접근 토큰을 받는다. 요청 본문은 없다.

응답 data

| 필드 | 타입 | 설명 |
|---|---|---|
| token | String | 새 접근 토큰 |

예시

```bash
curl -X PUT https://mnt-api.msghub.uplus.co.kr/auth/v1/refresh \
  -H "Authorization: Bearer {refreshToken}"
```

> 주의
> - refresh 토큰에 담긴 ipAddr 과 요청 서버의 IP 가 같아야 한다. 다른 IP 에서 갱신하면 거절될 수 있다.
> - 갱신 응답에는 `refreshToken` 이 없다(원문 예시 기준). 갱신 토큰 자체의 만료·재발급 규칙은 원문 확인 필요.

## 결과 코드

원문은 결과 코드 표를 별도 페이지(2.9 결과코드)로 연결한다. 이 문서에는 옮기지 않았다.
