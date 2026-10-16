# 5.4 모니터링용 API
> 원문: https://doc.msghub.uplus.co.kr/rest-api/06모니터링/0601-monitoring/ · 확인일 2026-10-16

## 한눈에 보기

| 기능 | Method | 경로 | 호스트 |
|---|---|---|---|
| 헬스체크 | PUT | `/client/v1/healthCheck` | api |

## 헬스체크

`PUT /client/v1/healthCheck`

agent 의 연결 상태를 주기적으로 알린다.

| 구분 | 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|---|
| Header | Authorization | String | ● | 사용자 인증 토큰 (`Bearer {token}`) |

응답은 공통 `code`·`message` 뿐이다.

요청 예시

```
PUT https://api.msghub-qa.uplus.co.kr/client/v1/healthCheck
Authorization: Bearer {token}
```

응답 예시

```json
{ "code": "10000", "message": "성공" }
```

> 주의
> - 연결 상태 확인을 위해 1분 이하 간격으로 호출한다.
> - msghub 가 1분마다 연결 상태를 점검하고, 문제가 계속되면 사용자가 정한 간격으로 알람을 보낸다.
> - 알람은 메시지허브 홈페이지 관리자콘솔의 알람 메뉴(세션체크용 알람)에서 설정한다.
> - 원문 확인 필요: 원문 URL 이 검수(QA) 호스트로 적혀 있다. 상용은 같은 경로를 상용 호스트(00-README 참고)로 호출하는 것으로 보인다.
