# Handoff — 현재 상황 요약

## 2026-09-18 — 비용·Message Hub·회신 알림 main 병합·운영 배포 및 Telegram 수신 검증

- 기능 커밋 `b70a2dc4dad1c2f157ffd9f22c29a99c32d2dde3`를 게시하고 [PR #12](https://github.com/RAVNUS-INC/kotify/pull/12)를 08:55:18 UTC에 `main`으로 병합했다. 병합 커밋은 `572b3d1dec0bfd159c4ecef969edcde27211da81`이다. pre-push 훅에서 백엔드 전체 테스트, Ruff, TypeScript, ESLint, 프런트엔드 Vitest가 통과했고 별도 Next.js 프로덕션 빌드도 18/18 페이지에 성공했다.
- 기존 업데이트 worker로 08:57:05 UTC에 운영 배포를 시작해 08:58:13 UTC에 빌드를 마쳤고, post-restart가 08:58:45 UTC에 새 버전의 정상 기동을 확인했다. worker의 pre-migrate 백업 뒤 운영 스키마를 `0019 → 0020 → 0021 → 0022 → 0023`으로 올렸다.
- 운영 API와 웹 프록시는 모두 HTTP 200, `status=ok`, `version=572b3d1`을 반환했다. `kotify`와 `kotify-web`은 active이며 `NRestarts=0`, `ExecMainStatus=0`이다. DB `PRAGMA quick_check`는 `ok`, 배포 이후 warning 이상 journal은 0건이고 알림 outbox 적체도 없었다.
- 운영 설정의 `Telegram 알림 테스트`는 n8n 접수 성공을 반환했고, 18:00 KST에 로그인 사용자 Telegram의 `레이븐어스 알림봇`으로 새 테스트 회신 알림이 실제 도착했다. 이는 운영 Kotify → n8n → Telegram과 로그인 사용자 라우팅을 확인한 결과다.
- 실제 고객 MO는 이번 검증에서 새로 만들지 않았다. 따라서 outbox 저장·재시도와 최근 실제 발신 담당자 선택의 운영 종단 검증은 남아 있으며, 현재는 자동 회귀 테스트와 빈 outbox·무경고 상태를 확인했다.

## 2026-09-18 — RCS CHAT 24시간 세션 비용 상한 반영

- 원인: 성공한 양방향 `(RCS, CHAT)` 리포트마다 `Message.cost=8`원을 저장해 동일
  챗봇·고객에게 24시간 안에 11건 이상 답장하면 대화방·캠페인·대시보드·리포트 비용이
  세션 최대 80원을 초과했다. 기존 `chat_session_cost()`는 화면용 요약에서만 쓰였고 저장
  비용 및 집계에는 연결되지 않았다.
- 수정: 동일 `(caller_number, to_number)` 쌍의 성공 CHAT을 발송 시각순으로 묶어 첫
  성공부터 24시간 동안 첫 10건은 8원, 11번째 이후는 0원으로 배분한다. 늦은 리포트가
  먼저 처리돼도 해당 대화 전체를 다시 계산하고 비용이 달라진 모든 캠페인 합계를 갱신한다.
  실패 CHAT은 세션 건수에서 제외하며 대체 SMS 성공은 기존대로 9원이다.
- 기존 데이터: `0022_chat_session_cost_cap.py`가 같은 규칙으로 기존 성공 CHAT과 관련
  캠페인 합계를 보정한다. 스키마 head는 후속 알림 outbox를 포함한 `0023`이다. downgrade는
  무료 처리된 0원을 다른 0원 원인과 안전하게 구분할 수 없어 데이터 보정을 유지한다.
- 검증: 웹훅·재조정, 역순 리포트, 10/11건 경계, 24시간 경계, 챗봇·고객별 분리,
  마이그레이션 재실행·downgrade를 회귀 테스트로 확인했다. 전체 백엔드 비포트 테스트
  **706개**, 루프백 포트가 필요한 배포 테스트 **7개**, Ruff와 diff 공백 검사가 통과했다.
  실제 공급자 청구서 대조·운영 마이그레이션·배포는 수행하지 않았다.

## 2026-09-18 — 회신 Telegram 알림 4개 문제 수정

- 마지막 담당자 판정은 캠페인 생성 시각 대신 실제 완료·요청 시각을 사용한다. 실패·취소·발송 전
  예약을 제외하고, 삭제된 사용자라면 그보다 이전의 유효 담당자를 찾는다.
- MO와 n8n 알림 요청을 같은 트랜잭션의 `notification_deliveries`에 저장한다. 전송 실패는 즉시
  재시도 후 DB에 남고 60초 주기 작업에서 다시 처리한다. 동시 작업은 조건부 선점으로 같은 행을
  중복 전송하지 않으며 5분 이상 남은 잠금도 복구한다.
- n8n HTTP 응답은 2xx만 성공으로 인정한다. 설정의 n8n 테스트는 `test=true`와 빈 담당자 대신
  로그인 사용자를 `lastSender`로 보내 실제 Telegram 라우팅을 요청한다. RCS `chatbotId`는 활성
  발신번호의 등록 별칭으로 해석한다.
- 스키마 head는 `0023`이다. 기존 `0022_chat_session_cost_cap.py`를 보존하고 그 다음에
  `0023_notification_delivery_outbox.py`를 연결했다. 커밋·푸시·운영 마이그레이션·실제 Telegram
  발송은 수행하지 않았다.
- 검증: 백엔드 전체를 샌드박스 비포트 테스트 **706개**와 로컬 포트가 필요한 배포 테스트
  **7개**로 나눠 모두 통과했다. Ruff, Python compile, diff 공백 검사와 Alembic 전체
  upgrade(`0023`) → downgrade(`0018`) → 재upgrade도 통과했다. 프런트엔드 **19개 파일·154개**
  테스트, TypeScript와 ESLint도 통과했다. 실제 n8n·Telegram 수신 확인은 배포 후
  `deploy/README.md` 절차로 남아 있다.

## 2026-09-18 — U+ Message Hub 최신 가이드 전 항목 반영

- 공식 가이드 대조에서 확인한 MO 번호 반전, RCS/MMS 파일 ID 혼용, 환경 값 불일치, 예약 30일 상한, 첨부 만료, 재조정 고착, health check 누락과 로컬 문서의 구 endpoint를 수정했다.
- SMS/MMS MO는 `moNumber=우리 번호`, `moCallback=고객 번호`로 해석하고 RCS의 `chatbotId`/`phone`과 분리한다. 첨부는 MMS·RCS에 각각 등록해 채널별 ID·만료를 저장하며 예약 시각까지 유효한지 검사한다.
- 이 변경의 스키마는 `0021_channel_attachment_ids.py`이며 현재 Alembic head `0023`의 마이그레이션 체인에 포함된다. 기존 첨부는 일반 MMS에는 쓸 수 있지만 RCS 이미지에는 재업로드가 필요하다.
- msghub 환경은 `production`·`qa`만 허용한다. 예약은 최대 30일이며, 60초 주기로 공급자 health check를 수행한다. `OVER_DATE`·`INVALID_KEY` 재조정 결과는 실패로 닫는다.
- 최종 검증: 백엔드 비포트 706개와 로컬 포트 통합 7개, 프런트엔드 154개, Ruff·TypeScript·ESLint·diff 공백 검사, Next.js 프로덕션 빌드 18/18 페이지가 통과했다. Alembic 전체 `0023` upgrade → `0018` downgrade → 재upgrade에서 `0021` 첨부 열도 확인했다.
- 공급자 실계정 호출·문자 발송·운영 DB 마이그레이션·배포는 수행하지 않았다. U+ QA에서 실제 MO, RCS 이미지/MMS fallback, 예약 경계, 웹훅 재전송을 `claudedocs/E2E-CHECKLIST.md`에 따라 확인해야 한다.

## 2026-09-18 — 비용 계산·미리보기 보정 로컬 구현

- 원인: 최초 발송 화면이 UTF-8 길이로 비용을 계산해 서버의 EUC-KR 분류와 달랐고, 성공 리포트의 실제 상품코드 `RSMS`와 전송 채널이 다른 장문 조합을 단가표가 누락해 비용을 0원으로 저장할 수 있었다.
- 수정: `POST /campaigns/preview`가 서버의 본문 분류·중복 제거·선택 채널·첨부 여부를 사용하도록 추가했다. 현재 견적이 성공하기 전에는 발송할 수 없고, 이전 요청 응답은 무효화한다. `RCS/RSMS=17원`, `SMS/LMS=27원`, `MMS/LMS=27원` 조합을 런타임 단가표에 추가했다.
- 데이터 보정: Alembic `0020_report_product_cost.py`가 `DONE/10000/cost=0`인 확인된 조합만 보정하고 해당 캠페인 합계를 다시 계산한다. 실패·미확정·알 수 없는 상품과 이미 기록된 비용은 보존한다. 운영 DB에는 아직 적용하지 않았다.
- 검증: 비용·미리보기·마이그레이션 관련 백엔드 31개, 전체 백엔드(로컬 포트 바인딩 테스트 7개 제외) 683개, 프런트엔드 154개, Ruff·TypeScript·ESLint·Next.js 18/18 빌드가 통과했다. 포트 바인딩 테스트 7개는 샌드박스 권한으로 실행하지 못했다.
- 남은 적용 절차: 배포 시 기존 worker의 백업 후 `alembic upgrade head`로 `0020` 비용 보정을 포함한 최신 revision을 적용하고, 백엔드와 프런트엔드를 같은 릴리스로 재시작한다. 운영 발송·브라우저 E2E·실제 청구서 대조는 수행하지 않았다.

## 2026-09-18 — main 병합·운영 배포 완료

- 기능 커밋 `7ea9630418968b37c6978a8c1862cfdd435c387c`를 게시한 뒤 사용자 승인으로 [PR #11](https://github.com/RAVNUS-INC/kotify/pull/11)을 07:50:47 UTC에 main에 병합했다. 병합 커밋은 `d599d84de11e7cbd9de52aa3d36317d12677b67c`이며 기능의 커밋·푸시·운영 배포를 완료했다.
- 최종 두 영역 코드 리뷰에서 P1·P2 차단 사항이 없었고, pre-push 훅에서 백엔드 **667개**·프런트엔드 **154개** 테스트와 Ruff·TypeScript·ESLint를 다시 통과했다. GitHub Actions는 기존에 비활성화되어 있어 CI 실행으로 표현하지 않는다.
- 기존 업데이트 worker로 07:52:13 UTC에 배포를 시작해 07:53:24 UTC에 완료했다. 운영 스키마 `0018 → 0019` 마이그레이션과 Next.js 프로덕션 빌드 **18/18 페이지**가 성공했다. 서버 내 별도 SQLite 백업과 worker의 pre-migrate 백업은 `0600` 권한으로 보존했으며 DB를 외부로 전송하지 않았다.
- 운영 확인: API·웹 서비스 모두 active/running이며 07:53:36 UTC 정상 기동과 post-restart 로그를 확인했다. 두 서비스의 `NRestarts=0`, `ExecMainStatus=0`이고 운영 추적 파일 변경은 없었다. 내부 API·웹 프록시·외부 HTTPS 헬스체크 모두 **HTTP 200**, `status=ok`, `version=d599d84`였다.
- DB는 revision `0019`, `quick_check=ok`이며 기존 `thread_reads`·MO·메시지·캠페인 행이 모두 보존됐다. 잘못된 읽음 커서는 0건이다. 운영 OpenAPI에서 읽음 JSON body와 `lastReadMessageId` 필수 조건, 목록 `q/unread/limit/offset`, 답장 사전 검증 `validate-reply` 경로를 확인했다.
- 운영 수동 UI 검증: 사용자 승인으로 2026-09-18 08:04 UTC경 로그인한 Chrome에서 빈 초안을 확인한 뒤 한글 45자 `90/90` 발송 활성, 46자 `92/90` 초과 경고·발송 차단, 이모지 EUC-KR 미지원 경고·발송 차단을 확인했다. 운영 버전은 `d599d84`로 유지했다.
- 실발송 검증: 45바이트 테스트 안내문을 RCS 선택으로 **1건만** 발송했다. 입력창이 비워지고 말풍선 1건에 시간/RCS/로그인 작성자 이름이 표시됐으며 새로고침 후에도 유지됐다. 통신사 결과·DB를 읽기 전용으로 확인해 캠페인 1건·메시지 1건, `COMPLETED`, 성공 1·실패 0·대기 0, `DONE/10000`, RCS를 확인했다. 실제 경로는 `RPSSAXX001/RSMS` 단방향 RCS였고 추가 SMS 대체 발송은 없었다. 입력창은 빈 상태로 남겼으며 추가 발송은 하지 않았다.
- 검증 범위: 양방향 CHAT·명시 거부 대체 발송·실제 단절 중 회신의 재연결·다수 직원 동시 읽음은 이번 운영 수동 검증에서 재현하지 않았으며 기존 자동 회귀 테스트와 구분한다. 기존에 열어 둔 대화방 탭은 새로고침해야 한다. 비용 미리보기 수정은 아직 운영 배포 전이다.

아래 수정·검증 기록은 기능 구현 단계의 기록이며, 최신 게시·운영 상태는 위 내용을 따른다.

## 2026-09-18 — 대화방 리뷰 추가 5건 수정·통합 검증 완료

- 목표·범위: 사용자 승인에 따라 직전 대화방 리뷰의 미해결 5건을 수정했다. 기존 답장 바이트 안내·발신자 표시와 최근 커밋 리뷰 4건 수정은 유지한다. 작업 브랜치는 `codex/review-recent-commits-20260918`이며 커밋·푸시·배포는 아직 하지 않았다.
- 답장 발송: 양방향 RCS의 명시적인 요청·수신자 거부를 단방향 RCS 대체 경로로 연결했다. 시간 초과·5xx·파싱 오류처럼 접수 여부가 불명확하면 실제 요청 `cliKey`와 메시지를 보존하고 즉시 대체 발송하지 않는다. 지연 리포트·재조정으로 결과를 확인한다. 최종 실패는 HTTP 502 `send_failed`, 미확정은 `send_status_unknown`과 `fields.campaignId`를 반환한다. 입력 본문을 유지하고 오류 안내와 기록 새로고침만 수행하며 자동 재발송하지 않는다. 미확정은 기존 `FAILED`/`result_code=None` 경로이며 전달 성공을 보장하지 않는다.
- 목록·집계: 번호·최근 본문 검색과 안읽음 필터를 전체 대화에 적용한 뒤 페이지를 자른다. `GET /threads`의 `limit`(기본·최대 200)·`offset`과 `meta.total/limit/offset/hasMore/unreadTotal`을 연결했다. `unreadTotal`은 검색 결과 전체 기준이며 안읽음 필터·페이지와 무관하다. UI의 이전·다음 링크는 검색·필터·선택 대화를 보존하고, 검색·필터 변경은 첫 페이지로 이동한다. 대시보드 안읽음 집계도 200개 제한을 제거했다.
- 읽음: 상세의 `lastInboundMessageId`는 실제로 조회한 수신 MO의 최대 ID다. 읽음 API는 필수 JSON `{ "lastReadMessageId": 42 }`를 받아 같은 고객 번호의 MO인지 확인하고 원자적인 최댓값 갱신으로 경계가 후퇴하지 않게 한다. 같은 번호의 발신번호·사용자 전체가 읽음 경계를 공유한다. 화면은 새 관측 ID에 따라 읽음을 요청하고, 이전 화면의 늦은 응답은 새 화면을 갱신하지 않는다.
- 스키마: `0019_thread_read_mo_cursor.py`가 `thread_reads.last_read_mo_id`와 번호 인덱스를 추가한다. 기존 읽음 시각 이전에 서버가 받은 `received_at`의 연속 ID 구간만 보수적으로 이관하며, 공급자 발생 시각으로 지연 도착을 읽음 처리하지 않는다. `mo_messages`를 재구축하지 않는다. 현재 MO 삭제 경로가 없다는 전제이며 향후 삭제·보관 도입 시 ID 재사용 방지가 필요하다. 구 프런트엔드의 본문 없는 읽음 요청은 422가 되므로 백엔드·프런트엔드를 함께 배포하고 열린 탭을 새로고침해야 한다.
- 실시간·정렬: SSE 최초 연결·재연결 시 목록·확정된 대화를 포함해 화면을 한 번 갱신한다. 전달 상태 이벤트의 5~60초 간격과 대기·실패 감시는 유지하며 유휴 폴링을 추가하지 않았다. 목록 최근 발신 시각·본문은 상세와 같은 `complete_time → report_dt → campaign.created_at` 기준을 써 리포트 전 답장도 반영한다.
- 최종 검증: 백엔드 전체 **667개 통과**(Authlib 사용 중단 경고 1건·기존 Alembic 설정 경고 14건), 프런트엔드 **19개 파일·154개 통과**. Ruff·TypeScript·ESLint·diff 공백 검사와 Next.js 프로덕션 빌드 **18/18 페이지 성공**을 확인했다. 별도 임시 DB에서 전체 Alembic upgrade(`0019`) → downgrade(`0018`) → 재upgrade도 통과했다. 읽음·목록·SSE·발송의 독립 교차 리뷰에서 추가 차단 문제는 없었다. 직전 길이 안내·발신자 표시 구현 당시 수치인 백엔드 631개·프런트엔드 133개와 구분한다.
- 변경 파일: `app/models.py`, `app/routes/threads.py`, `app/routes/dashboard.py`, `app/services/chat.py`, `app/services/compose.py`, 마이그레이션 `0019`, 대화방 페이지·목록·읽음·SSE·발송 오류 처리와 관련 테스트. 문서는 `README.md`, `deploy/README.md`, `claudedocs/SPEC.md`, 본 인계 문서와 [리뷰 결과](claudedocs/review/REVIEW-SUMMARY.md)를 갱신했다.
- 미수행: 실제 공급자 요청·문자 발송·브라우저 E2E·운영 접근·운영 마이그레이션. 테스트는 격리 DB·모의 HTTP·React 환경에서 수행했다.
- 남은 사항: SMS 대체 발송을 기다리는 동안 SQLite 쓰기 트랜잭션을 유지하는 기존 구조 문제는 이번 범위 밖으로 남긴다. 비용 보정·미리보기는 로컬 수정·검증을 완료했으며 게시·운영 적용은 별도 작업이다. 배포 시 아래 운영 절차와 `deploy/README.md`의 `0020` 호환 안내를 따른다.

## 2026-09-18 — 최근 커밋 리뷰 수정·로컬 검증 완료

- 목표·범위: `bf232fe` 기준 최근 first-parent 25개 커밋(`405a254..bf232fe`)과 인접한 현재 동작을 검토하고 주요 결함을 수정했다. 작업 브랜치는 `codex/review-recent-commits-20260918`이다.
- 완료: 일부 청크만 접수된 예약의 취소 차단(P1), 과거 세션의 DB 권한 덮어쓰기(P1), 처리 중으로 복구된 캠페인의 실패 상태·이벤트 누락(P2), 대화방의 실패 복구 갱신 누락(P2)을 수정하고 회귀 테스트를 추가했다. 자세한 재현과 수정 내용은 [최신 리뷰](claudedocs/review/REVIEW-SUMMARY.md)에 있다.
- 예약: 상세 API의 `canCancelReservation`으로 취소 가능 여부를 표시한다. 확인된 예약 청크를 취소하고 시간 초과 등 접수 여부가 불명확한 행은 전체 취소로 확정하지 않는다. 상세 `failureReason`에 미확정 인원과 msghub 웹 콘솔 확인·취소 안내를 남긴다.
- 인증: 일반 요청과 `/auth/me`는 DB의 최신 역할·프로필을 사용하며 검증 로그인 콜백만 사용자 정보·`last_login_at`을 갱신한다. 삭제 계정은 기존 세션으로 복원되지 않는다. 세션 불일치 경고는 제거했고 최초 관리자 정책·`LOGIN` 역할 진단은 유지했다. Keycloak의 새 역할은 검증된 새 로그인으로 DB에 반영해야 한다.
- 상태·화면: 재조정의 `FAILED → REG/ING` 복구는 캠페인을 `DISPATCHING`으로 바꾸고 커밋 뒤 이벤트를 발행한다. `completed_at` 최초 결과 시각은 유지한다. 대화방은 대기·실패 메시지를 함께 감시하고 대화 이동 중 최근 이벤트도 보정하며, 이벤트 없는 폴링은 추가하지 않았다.
- 변경 파일: 인증(`app/auth/deps.py`, `app/routes/auth.py`), 예약(`app/routes/campaigns.py`, `app/services/compose.py`, 캠페인 상세 UI·API 타입), 결과(`app/services/report.py`, `app/services/reconcile.py`), 대화방 페이지·구독·메시지 조회 도우미와 관련 테스트. 문서는 `README.md`, `deploy/README.md`, `claudedocs/SPEC.md`, `claudedocs/review/REVIEW-SUMMARY.md`, `HANDOFF.md`를 갱신했다.
- 최종 검증: 기존 Python 3.14 `.venv`에서 루프백 바인딩이 허용된 백엔드 전체 **606개 통과**(기존 의존성 사용 중단 경고 8건). 프런트엔드 **17개 파일·109개 테스트**, Ruff·TypeScript·ESLint·diff 공백 검사 통과. Next.js 프로덕션 빌드 **18/18 페이지 성공**. 수정 전 리뷰 기준선은 백엔드 571개·프런트엔드 99개였다.
- 미수행: 실제 브라우저 E2E·공급자 실연동·메시지 발송·운영 검증. 커밋·푸시·배포도 하지 않았다. DB 마이그레이션을 추가하지 않아 스키마 `0018`을 유지한다. 아래 배포 이력은 이번 로컬 수정 이전의 기록이다.
- 남은 구조 개선: `623afd3`부터 알려진 SMS 대체 발송 대기 중 SQLite 쓰기 잠금 문제는 유지된다. 로컬 WAL DB·모의 공급자의 혼합 리포트 배치에서 이벤트 루프가 5.203초 막힌 뒤 HTTP 400이 반환됐다. 발송 소유권을 영속 기록한 뒤 외부 요청과 결과 확정을 분리하고, 중복 발송 방지·장애 복구를 함께 검증해야 한다.
- 다음 단계: 남은 쓰기 트랜잭션 구조 개선과 실제 브라우저·공급자 검증을 진행한다. 기존 런타임/E2E 미완료 항목도 유지한다. 로컬 수정은 검증 완료 상태이며 게시·운영 적용은 별도 작업이다.

## 2026-09-18 — main 통합·배포 및 Keycloak sender 진단

- 목표: 미반영 변경을 검토해 `main`에 통합·배포하고, Keycloak에서 `sender`를 부여한 계정이 `viewer`로 보이는 원인을 새 로그인 기록으로 확인한다.
- 통합 내용: 혼합 시각 포맷의 검색·그룹 최근 발송·웹훅 진단 정렬 수정 3건, 의존성 PR 8건, 회원 목록의 `sender` 표시와 회귀 테스트, 최소 CT의 `sudo` 설치 보완, 안전한 역할 진단과 회귀 테스트.
- 통합 제외: 과거 Jinja 화면·테스트는 Next.js 구현으로 대체됐고 예약 fallback 제품 수정은 이미 main에 있다. 현행 SMS fallback 정책과 충돌하는 옛 RCS fallback 정책, 원문 메시지·웹훅을 출력하는 임시 로그는 복원하지 않는다.
- 인증 동작: Authlib가 검증한 ID 토큰 클레임에서 역할을 읽는다. 유효한 지원 역할이 없으면 `viewer`를 적용하는 기존 정책을 유지하며 원문 JWT를 권한 판정용으로 임의 파싱하지 않는다. 로그인 이후 기존 세션 요청이 DB 역할을 덮는 정책도 아직 변경하지 않았다.
- 추가 진단: 새 `LOGIN` 감사 이벤트의 `detail.role_diagnostics`에 역할 위치·형태, 설정된 클라이언트와 `azp` 일치 여부, 파싱/최종 역할을 기록한다. 지원 역할 외에는 개수만 남기고 토큰·쿠키·프로필·클라이언트 이름은 넣지 않는다. 세션/DB 역할 불일치는 `auth_session_role_mismatch` 경고로 관찰한다.
- 배포 전 운영 증거: 운영 커밋 `db2db09`, 추적 파일 변경 없음, 두 서비스 실행 중. 대상 계정의 당일 `LOGIN` 이벤트와 현재 DB 역할 `viewer`를 읽기 전용으로 확인했다. 기존 로그에 역할 클레임이 없어 실제 ID 토큰의 `sender` 포함 여부는 입증할 수 없다.
- 주의: `users.last_login_at`은 일반 인증 요청에서도 갱신되므로 실제 로그인 시각은 `LOGIN` 이벤트를 사용한다. 불일치 경고에는 계정 식별자가 없으므로 경고 하나만으로 특정 사용자 원인을 단정하지 않는다.
- SSH 해결: CT 콘솔에서 `ssh.socket`을 중단하고 `ssh.service` 방식으로 전환한 뒤 이 Mac의 기존 키와 엄격한 호스트 키 검증으로 접속 성공. 접속 주소·키 원문·계정 개인정보는 기록하지 않는다.
- 로컬 검증: 전체 백엔드 571개·프론트엔드 99개 테스트, Ruff, TypeScript, ESLint, Next.js 프로덕션 빌드, `bash -n deploy/ct-bootstrap.sh`, diff 공백 검사 통과. 루프백 HTTP 서버가 필요한 테스트는 네트워크 바인딩이 허용된 환경에서 실행했다. 별도 통합 리뷰 승인. 기존 CT를 초기화하는 bootstrap은 운영에서 재실행하지 않는다.
- 배포 완료: 기능 통합 커밋 `9acc87d`를 `main`에 푸시하고 2026-09-18 05:25 UTC 운영 배포했다. 서버 빌드 성공, 두 서비스 active, API·웹 프록시·외부 HTTPS 헬스체크 모두 HTTP 200 / `status=ok` / `version=9acc87d`, DB quick_check 통과, 스키마 `0018` 유지. 열린 PR 0건 확인. 백업은 서버 내 비공개 파일로 보존했다.
- 배포 중 복구: 첫 시도는 백업용 제한 umask가 소스 갱신에 전파돼 서비스 계정의 파일 읽기가 실패했고 이전 커밋으로 자동 복원됐다. 정상 설치 umask로 기존 업데이트 스크립트를 재실행해 해결했다. 일반 배포 권한과 백업 파일 권한을 분리하는 절차를 `deploy/README.md`에 기록했다.
- 로컬 정리: 기본 작업폴더도 `main`으로 전환했다. 통합 전 문서 메모는 `main 통합 전 작업폴더 운영 메모 보존 2026-09-18` stash로 보존했으며, 최신 진단 내용은 이 문서와 운영 가이드에 반영했다.
- 원인 확인: 05:30 UTC 새 로그인 2건에서 검증된 ID 토큰에 `realm_access`와 `resource_access`가 모두 없고 `azp`는 설정된 클라이언트와 일치했다. 파서가 `viewer` 기본값을 선택했고 테스트 계정의 `admin`은 최초 관리자 이메일 정책에서 추가됐다. 원문 토큰은 조회·기록하지 않았다.
- Keycloak 대조: 테스트 계정에는 그룹에서 상속한 해당 클라이언트의 `sender`가 실제 존재한다. 연결된 공용 `roles` scope의 `client roles` 매퍼는 Access Token 포함만 켜져 있고 ID Token 포함은 꺼져 있었다. Kotify 전용 scope에는 매퍼가 없었다.
- Keycloak 수정: 사용자 승인 후 Kotify 전용 `kotify-client-roles-id-token` 매퍼를 생성했다. 해당 클라이언트 역할만 `resource_access.kotify.roles`의 다중 문자열 값으로 ID 토큰에 넣고, 다른 토큰 출력 옵션은 끈 상태로 저장·재조회했다. 기존 그룹·역할 할당과 공용 scope는 변경하지 않았다.
- 운영 재검증 완료: 05:40 UTC 새 로그인에서 검증된 ID 토큰의 해당 클라이언트 역할 배열에 `sender`, 파서 결과에 `sender`, 최종 역할과 현재 DB 값에 `admin`·`sender`가 확인됐고 `viewer_fallback_used=false`였다. 그룹 역할이 ID 토큰에서 누락되는 문제를 해결했다. 실제 문자 발송은 수행하지 않았다.
- 최초 신고 계정 검증 완료: 05:41 UTC 실제 로그인에서도 ID 토큰의 해당 클라이언트 역할, 파싱 결과, 최종 역할과 현재 DB 값 모두 `sender`로 확인했다. 최초 관리자 보정은 적용되지 않았고 `viewer_fallback_used=false`였다. 두 계정의 그룹 상속 역할 전달과 적용을 운영에서 검증해 이번 문제를 해결했다.
- 운영 참고: 다른 기존 `viewer` 세션은 `/api/auth/login`으로 재인증하면 새 역할 매핑을 받는다. 상세 설정·조회 절차는 `deploy/README.md`를 따른다.

---

아래는 이전 인계 기록이며 현재 운영 상태를 보장하지 않는다.

> 최종 갱신: 2026-04-21
> 현 브랜치: `vibrant-shamir-e74f49` (origin/main 대비 +31 커밋)

kotify는 두 번의 주요 전환을 거치며 다음 상태에 도달했다:

1. **NCP SENS → U+ msghub 마이그레이션** (완료)
2. **Jinja2 + HTMX → Next.js 14 App Router 포트 (Phase 1~10)** (완료)
3. **Phase 11 배포** (다음 단계)

---

## 1. 마이그레이션 (완료)

NCP SENS 의존을 전량 제거하고 U+ msghub로 전환.

| 영역 | 상태 |
|---|---|
| `app/msghub/` 신설 (`auth.py` / `client.py` / `schemas.py` / `codes.py`) | ✅ |
| JWT 인증 + SHA512 이중 해싱 + asyncio.Lock stampede 방지 | ✅ |
| SMS / LMS / MMS / RCS 양방향 + `fbInfoLst` fallback 지원 | ✅ |
| 웹훅 엔드포인트 (`/webhook/msghub/report`, `/webhook/msghub/mo`) | ✅ |
| `app/ncp/` 전량 삭제 | ✅ |
| `app/services/poller.py` 삭제 (웹훅 기반으로 전환되며 불필요) | ✅ |
| DB 스키마 전환 (`ncp_requests` → `msghub_requests` 등) | ✅ |

관련 문서: `claudedocs/msghub-migration-spec.md`, `msghub-api-guide.md`,
`msghub-error-codes.md`, `msghub-template-api.md`, `msghub-ux-changes.md`.

---

## 2. Next.js 14 포트 — Phase 1~10 (완료)

Jinja2 + HTMX 서버 렌더링을 Next.js 14 App Router 기반 RSC 아키텍처로 전면 포팅.

| Phase | 내용 | 상태 |
|---|---|---|
| 1 | 스캐폴드 — Next.js 14, TypeScript strict, Tailwind, pnpm | ✅ |
| 2 | 디자인 토큰 + 컴포넌트 프리미티브 (Card / Field / Input / Button / Drawer) | ✅ |
| 3 | 모션 프리미티브 (Counter / Sparkline / AnimatedBars / Progress / Rise / Stagger / PulseDot) | ✅ |
| 4 | 레이아웃 + Keycloak OIDC middleware + layout.tsx session guard (2-tier) | ✅ |
| 5 | S1 Dashboard (RcsDonut + KpiCards) | ✅ |
| 6 | S2 / S3 `/send/new` + `/chat` (SSE, Korean IME 처리) | ✅ |
| 7 | S4 `/campaigns/[id]` + S7 `/contacts` (Drawer) + S9~S10 `/groups` | ✅ |
| 8 | S11 `/numbers` + S12 `/settings/[[...tab]]` catch-all + S13 `/audit` (CSV export with CWE-1236 defense) | ✅ |
| 9 | S15 `/notifications` + S16 `/reports` + S17 `/search` + ⌘K Command Palette + S18 Error 3종 | ✅ |
| 10a | jsx-a11y/strict 프리셋 도입, 14 이슈 해결 | ✅ |
| 10b | `@next/bundle-analyzer` (ANALYZE=true gate), 번들 스냅샷 문서화 | ✅ |
| 10c | Motion 1.2s 예산 감사 + 6곳 압축, `motion-timing.md` 매트릭스 작성 | ✅ |
| 10d | Runtime audit (Lighthouse / CLS / 60fps / reduced-motion / axe) | ⏳ 배포 후 재개 |

**4차 코드 리뷰 완료** (Phase 0~9d 전반에 걸쳐 45 이슈 일괄 수정):
- Critical: 1 (msghub webhook signature verification)
- High: 8 (stale response race, mark CSS 누락, useId hydration 등)
- Medium: 22
- Low/NTH: 14

총 18/18 화면 포팅 완료. 코드는 `web/` 디렉토리에, 기존 FastAPI는 `app/`에 유지.

---

## 3. Phase 11 — 배포 (다음 단계)

> **운영 전제**: 기존 CT는 폐기하고 **완전 새 CT**에 배포.
> DB는 `alembic upgrade head`로 초기 빈 상태에서 최신 스키마가 자동 구축됨 — 이전 데이터 이관 없음.

### 3.1 현재 배포 자산 상태

| 자산 | 상태 | 비고 |
|---|---|---|
| `deploy/ct-bootstrap.sh` | ⚠️ FastAPI 기준 | Node 20 + pnpm + Next.js 빌드 단계 추가 필요 |
| `deploy/kotify.service` | ✅ FastAPI 전용 systemd | 8080 포트, NPM 내부 경유 |
| `deploy/kotify-web.service` | ❌ 미존재 | **추가 필요** (Next.js 3000 포트) |
| `deploy/npm-config.md` | ⚠️ 포트 8080 기준 | 포트 3000 + SSE 지원 추가 필요 |
| `deploy/sms.service` | ❌ 레거시 (NCP 시절) | 제거 예정 |
| `next.config.mjs` | ⚠️ `output: 'standalone'` 미설정 | 배포 용량 최적화 위해 추가 필요 |

### 3.2 사용자(운영자) 측 준비

| 항목 | 비고 |
|---|---|
| U+ msghub 계정 + API Key/Password | 필수 |
| RCS 브랜드 + 챗봇 등록 | `msghub-migration-spec.md`에 "완료"로 명시되어 있음 — 재확인 필요 |
| Keycloak realm/client `sms-sys` | Redirect URI `https://sms.example.com/auth/callback` |
| Proxmox CT (Debian 12/13, 1vCPU/1GB/8GB) | 아웃바운드 허용: msghub API, Keycloak, NTP, GitHub |
| DNS A 레코드 | `sms.example.com` → NPM 서버 IP |

### 3.3 배포 흐름 (최종 형태)

```
사용자: NCP 계정 ❌  →  msghub 계정 + RCS 브랜드 준비 (사전 리드타임)
사용자: Proxmox CT 생성 + DNS + Keycloak 구성
운영자: curl pipe로 ct-bootstrap.sh 실행
  └─ OS 확인 → Python + Node 설치 → 사용자/디렉토리/NTP
  └─ git clone → .venv/bin/pip install -e . → alembic upgrade
  └─ cd web && pnpm install && pnpm build
  └─ kotify.service + kotify-web.service 등록/기동
운영자: NPM Proxy Host 등록 (포트 3000, SSE 통과)
운영자: https://sms.example.com/setup → 마법사 5단계 완료
운영자: master.key 별도 안전 위치 백업
운영자: 본인 번호로 테스트 발송 (RCS → SMS fallback 확인)
```

---

## 4. 남은 작업 체크리스트

### 4.1 코드 갭 (Phase 11 시작 시)

- [ ] `next.config.mjs`에 `output: 'standalone'` 추가
- [ ] `deploy/kotify-web.service` 신설 (Next.js systemd)
- [ ] `deploy/ct-bootstrap.sh`에 Node 20 + pnpm + `pnpm install` + `pnpm build` 단계 추가
- [ ] `deploy/sms.service` 제거 (NCP 시절 레거시)
- [ ] 환경변수 목록 문서화 (`FASTAPI_URL`, `NEXTAUTH_URL` 등)

### 4.2 운영 환경 준비 (사용자 측)

- [ ] msghub API 키 / RCS 브랜드 상태 확인
- [ ] 도메인 값 결정 (`sms.example.com`)
- [ ] Keycloak realm/client 구성
- [ ] Proxmox CT 준비
- [ ] DNS 레코드

### 4.3 Phase 10d (배포 후 재개)

배포 완료 시점에 실 환경에서 실측:
- [ ] Lighthouse (Performance / A11y / Best Practices / SEO) × 주요 페이지
- [ ] Performance trace — FCP / LCP / CLS / TBT / 60fps 유지
- [ ] reduced-motion emulate → Counter / Sparkline / Progress 즉시 점프 확인
- [ ] axe-core 주입 실사

결과는 `claudedocs/phase-10d-runtime-audit.md`의 _측정 중_ 칸을 채움.

---

## 5. 참고 경로

```
app/               FastAPI 백엔드 (Python 3.12+)
  msghub/          U+ msghub 클라이언트 + 인증
  services/        비즈니스 로직 (compose, audit, ...)
  routes/          FastAPI 라우트 (webhook, auth, ...)
  models.py        SQLAlchemy 2.0 ORM
  config.py        pydantic-settings (SMS_* prefix)
alembic/           DB 마이그레이션
web/               Next.js 14 프론트엔드 (TypeScript)
  app/(app)/       인증 필요 route group
  app/(auth)/      로그인 route group
  components/      UI + motion primitives
  types/           공유 타입
deploy/            시스템 배포 자산
claudedocs/        스펙 / 가이드 / Phase 감사 문서
tests/             pytest
```

---

## 6. 알려진 주의사항

- **Python 3.14 호환성**: `app/db.py`가 Python 3.14의 pathlib 변경과 호환되지만, `pyproject.toml`은 3.12+를 요구한다. 운영은 3.12/3.13에서만 검증됨.
- **SMS_DEV_MODE**: 미설정 시 `/var/lib/kotify/` 권한 에러 — 로컬 smoke 실행 시 `SMS_DEV_MODE=true` 필수.
- **pnpm 필수**: `web/` 디렉토리는 pnpm lockfile(`pnpm-lock.yaml`) 기준. npm/yarn 사용 금지.
- **typedRoutes**: 동적 URL 조합(`${pathname}?${qs}`) 시 `as Route` 캐스트 필요.
- **motion 1.2s 예산**: 새 연출 컴포넌트 추가 시 `claudedocs/motion-timing.md` 매트릭스에 기입 + 예산 초과 여부 확인.
