# U+ msghub REST API 레퍼런스

> 원문: https://doc.msghub.uplus.co.kr/rest-api/01개요/01intro/ (하위 23쪽) · 확인일 2026-10-16
> 원문 내용을 개발자가 찾기 쉽게 재구성한 한국어 정리본이다. 필드·코드 값은 원문 기준이며, 원문이 애매한 곳은 각 문서에 `원문 확인 필요` 로 표시했다.
> 예전 정리본(`claudedocs/msghub-api-guide.md` 등)은 옛 문서 사이트(docs2) 기준이라, 둘이 다르면 이 디렉터리를 우선한다.

## msghub 한 줄 요약

SMS/LMS/MMS, RCS, 카카오(알림톡·친구톡·브랜드메시지), 앱 푸시를 한 플랫폼에서 보내고, 결과 리포트·MO(수신)·통계·080 수신거부·단축 URL 까지 REST API 로 제공하는 LG U+ 기업 메시징 서비스.

## 호스트

API 는 용도별로 호스트가 셋이다. 각 문서의 '한눈에 보기' 표는 아래 약칭(api / api-send / mnt-api)으로 호스트를 적는다.

| 약칭 | 용도 | 상용 | 검수(QA) |
|------|------|------|----------|
| api | 인증, 리포트, 예약 관리 등 | `https://api.msghub.uplus.co.kr` | `https://api.msghub-qa.uplus.co.kr` |
| api-send | 채널별 메시지 발송 | `https://api-send.msghub.uplus.co.kr` | `https://api-send.msghub-qa.uplus.co.kr` |
| mnt-api | 채널 관리(파일·템플릿·브랜드 등) | `https://mnt-api.msghub.uplus.co.kr` | `https://mnt-api.msghub-qa.uplus.co.kr` |

전용회선은 호스트 이름에 `-direct` 가 붙는다(`api-direct`, `api-send-direct`, `mnt-api-direct`). 방화벽 작업이 필요해 고객센터 신청이 먼저다. 원문에 IP 가 적힌 것은 api-direct 뿐이다.

| 구분 | api-direct IP | 포트 |
|------|---------------|------|
| 상용 | 1.209.4.60 / 1.209.4.75 | 443 |
| 검수 | 1.209.4.92 / 1.209.4.105 | 443 |

인터넷 연동에서 고정 IP 가 필요하면 고객센터에 따로 요청한다.

kotify 는 [app/msghub/client.py](../../app/msghub/client.py) 에서 이 세 호스트(인터넷 연동)를 쓴다.

## 공통 규칙

- 메서드: 생성 POST · 조회 GET · 수정 PUT · 삭제 DELETE
- Content-Type: `application/json`, 파일 업로드만 `multipart/form-data`
- 인코딩: UTF-8
- 인증: 모든 요청에 `Authorization: Bearer {JWT}` — 발급·갱신은 [01-auth.md](01-auth.md)
- 응답 래퍼: `{ "code": "10000", "message": "성공", "data": ... }` — `10000` 이 성공, 나머지는 [09-result-codes.md](09-result-codes.md)

## 문서 목록

| 원문 | 파일 | 내용 |
|------|------|------|
| 2.1 | [01-auth.md](01-auth.md) | 토큰 발급·갱신 |
| 2.2 | [02-xms.md](02-xms.md) | SMS / LMS / MMS 발송 |
| 2.3.1 | [03a-rcs-android.md](03a-rcs-android.md) | RCS 메시지(android) 발송 |
| 2.3.2 | [03b-rcs-integrated.md](03b-rcs-integrated.md) | 통합 RCS 단방향·양방향 발송 |
| 2.4 | [04-kakao.md](04-kakao.md) | 카카오톡 메시지 발송 |
| 2.5 | [05-push.md](05-push.md) | 앱 푸시 발송 |
| 2.6 | [06-smartmsg.md](06-smartmsg.md) | 통합발송(템플릿 기반 여러 채널) |
| 2.7 | [07-reservation.md](07-reservation.md) | 예약 메시지 조회·취소 |
| 2.8 | [08-report.md](08-report.md) | 발송 결과 리포트(폴링·웹훅) |
| 2.9 | [09-result-codes.md](09-result-codes.md) | 결과 코드 전체 |
| 3.1 | [10-mnt-auth.md](10-mnt-auth.md) | 채널 관리 API 인증 |
| 3.2 | [11-mnt-contents.md](11-mnt-contents.md) | 컨텐츠(이미지) 업로드·관리 |
| 3.3 | [12-mnt-kakao.md](12-mnt-kakao.md) | 카카오 V2 관리 |
| 3.4 | [13-mnt-kakao-brandtalk.md](13-mnt-kakao-brandtalk.md) | 카카오 V2 브랜드메시지 관리 |
| 3.5 | [14-mnt-rcs.md](14-mnt-rcs.md) | RCS 관리 |
| 3.6 | [15-mnt-xms-smart.md](15-mnt-xms-smart.md) | 문자 메시지 / 통합발송 관리 |
| 4.1 | [16-statistics.md](16-statistics.md) | 발송 통계 |
| 4.2 | [17-kakao-statistics.md](17-kakao-statistics.md) | 카카오 통계 |
| 5.1 | [18-ars080.md](18-ars080.md) | 080 수신거부 |
| 5.2 | [19-mo.md](19-mo.md) | MO(수신 메시지) |
| 5.3 | [20-shorturl.md](20-shorturl.md) | 반응형 URL |
| 5.4 | [21-monitoring.md](21-monitoring.md) | 모니터링용 API |

## 이 정리본에 없는 것

- replyId 유효시간(24h)·RCS 세션 과금 같은 상위 규격은 msghub 문서가 아니라 이통 공통 RCS 발송규격(https://biz-rcs-1.gitbook.io/rcs/)에 있다. 검증 기록은 [../review/reply-id-verification.md](../review/reply-id-verification.md).
- cliKey 10분 중복 규칙처럼 kotify 가 따르는 로컬 규칙은 현행 원문에 없다. 출처는 [../msghub-migration-spec.md](../msghub-migration-spec.md).
