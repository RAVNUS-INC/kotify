# kotify 코드 리뷰 — 종합 리포트

## 2026-09-18 — main 병합·운영 배포 완료

- 기능 커밋 `7ea9630418968b37c6978a8c1862cfdd435c387c`를 게시한 뒤 사용자 승인으로 [PR #11](https://github.com/RAVNUS-INC/kotify/pull/11)을 07:50:47 UTC에 main에 병합했다. 병합 커밋은 `d599d84de11e7cbd9de52aa3d36317d12677b67c`이며 기능의 커밋·푸시·운영 배포를 완료했다.
- 최종 두 영역 코드 리뷰에서 P1·P2 차단 사항이 없었고, pre-push 훅에서 백엔드 **667개**·프런트엔드 **154개** 테스트와 Ruff·TypeScript·ESLint를 다시 통과했다. GitHub Actions는 기존에 비활성화되어 있어 CI 실행으로 표현하지 않는다.
- 기존 업데이트 worker로 07:52:13 UTC에 배포를 시작해 07:53:24 UTC에 완료했다. 운영 스키마 `0018 → 0019` 마이그레이션과 Next.js 프로덕션 빌드 **18/18 페이지**가 성공했다. 서버 내 별도 SQLite 백업과 worker의 pre-migrate 백업은 `0600` 권한으로 보존했으며 DB를 외부로 전송하지 않았다.
- 운영 확인: API·웹 서비스 모두 active/running이며 07:53:36 UTC 정상 기동과 post-restart 로그를 확인했다. 두 서비스의 `NRestarts=0`, `ExecMainStatus=0`이고 운영 추적 파일 변경은 없었다. 내부 API·웹 프록시·외부 HTTPS 헬스체크 모두 **HTTP 200**, `status=ok`, `version=d599d84`였다.
- DB는 revision `0019`, `quick_check=ok`이며 기존 `thread_reads`·MO·메시지·캠페인 행이 모두 보존됐다. 잘못된 읽음 커서는 0건이다. 운영 OpenAPI에서 읽음 JSON body와 `lastReadMessageId` 필수 조건, 목록 `q/unread/limit/offset`, 답장 사전 검증 `validate-reply` 경로를 확인했다.
- 기존에 열어 둔 대화방 탭은 새로고침해 새 클라이언트를 로드해야 한다. 실제 메시지 발송과 로그인 후 브라우저 E2E는 수행하지 않았다. SQLite 외부 발송 대기 중 쓰기 잠금과 최초 발송 화면의 UTF-8 예상 길이/서버 EUC-KR 불일치는 별도 후속 개선으로 남긴다.

아래 수정·검증 기록은 기능 구현 단계의 기록이며, 최신 게시·운영 상태는 위 내용을 따른다.

## 2026-09-18 — 대화방 집중 리뷰 5건 수정·통합 검증 완료

직전 리뷰에서 남긴 P2 5건을 사용자 승인에 따라 수정했다. 답장 길이 안내·초과 차단과 발신자 표시, 이전 최근 커밋 리뷰 4건 수정도 유지한다. 현재 작업 트리 기준이며 커밋·푸시·배포는 수행하지 않았다.

| 우선순위 | 수정 영역 | 수정 전 재현·영향 | 현재 동작 |
|---|---|---|---|
| P2 | `app/services/compose.py`, `app/services/chat.py`, 답장 API·입력창 | 양방향 RCS 전체 코드 `10000`, 수신자 코드 `51004`를 API 성공으로 반환하고 대체 발송 없이 `FAILED`로 종료 | 명시적 요청·수신자 거부는 단방향 RCS 경로로 대체한다. 시간 초과·5xx·파싱 오류처럼 접수 미확정이면 실제 `cliKey`의 기록을 남겨 지연 리포트·재조정으로 확인하며 즉시 중복 발송하지 않는다. 최종 실패와 미확정은 각각 HTTP 502 `send_failed`·`send_status_unknown` 및 `fields.campaignId`를 반환한다. 입력 본문은 유지하고 안내·기록 갱신만 수행한다. |
| P2 | `app/services/chat.py`, 목록·대시보드 API, 대화 목록 UI | 최근 200개를 자른 뒤 검색·안읽음 필터를 적용해 201번째 일치 대화 누락, 후속 페이지 접근 불가 | 전체 대화에 검색·안읽음 필터를 적용한 뒤 페이지를 자른다. API `limit`·`offset`과 전체 건수·다음 페이지·안읽음 metadata를 UI 이전·다음 이동에 연결했다. 안읽음 총수는 검색 결과 전체 기준이며 페이지·안읽음 필터와 무관하고, 대시보드도 200개 제한 없이 집계한다. |
| P2 | `app/models.py`, `app/routes/threads.py`, `app/services/chat.py`, `ThreadView`, 마이그레이션 `0019` | 상세 조회 후 도착한 미관측 회신까지 현재 시각으로 읽음 처리. 늦은 MO의 과거 공급자 시각도 읽음으로 오판. `unread=true → true`인 새 회신은 추가 읽음 요청 누락 | 상세에 실제 포함된 MO의 최대 ID를 반환하고, 클라이언트는 이 ID만 필수 읽음 요청으로 보낸다. 서버는 같은 번호의 MO를 확인한 뒤 원자적 최댓값으로 팀 공유 경계를 갱신한다. 새 관측 ID 변경은 읽음을 다시 요청하며 이전 화면의 늦은 응답은 무시한다. 공급자 발생 시각은 읽음 판정에 사용하지 않는다. |
| P2 | `web/components/chat/useChatStream.ts` | 목록·정상 상세에서 SSE `error → 재연결 → open` 뒤 갱신 0회여서 끊긴 동안의 회신이 표시되지 않음 | 최초 연결·재연결마다 화면 종류와 무관하게 한 번 갱신한다. 닫힌 연결의 늦은 이벤트는 무시한다. 전달 상태의 대기·실패 감시와 5~60초 간격은 유지하며 유휴 폴링은 없다. |
| P2 | `app/services/chat.py` | 리포트 없는 신규 `REG`·`FAILED` 답장은 상세에만 보이고 목록 순서·미리보기는 이전 발송에 머무름 | 목록의 최근 MT 시각·본문도 상세와 같은 `complete_time → report_dt → campaign.created_at` 기준으로 고른다. 혼합 시각 형식 비교와 배치 조회를 유지한다. |

접수 미확정 기록은 현재 `FAILED`·`result_code=None`으로 저장된다. 공급자에게 실제로 접수됐을 수 있으므로 오류 안내대로 결과를 확인하기 전 다시 보내지 않으며, 대체 경로가 있다는 이유로 전달 성공을 보장하지 않는다.

읽음 경계 마이그레이션 `0019`는 `thread_reads.last_read_mo_id`와 번호 인덱스를 추가한다. 기존 `read_at` 이전에 로컬 서버가 수신한 `received_at`의 연속 ID 구간만 이관한다. 시각이 불명확하거나 앞선 ID가 미관측이면 그 이후까지 읽음으로 추정하지 않아 일부 과거 회신이 안읽음으로 다시 보일 수 있다. `mo_messages`는 재구축하지 않는다. 현재 MO 삭제 경로가 없으며, 향후 삭제·보관 정책 도입 시 ID 재사용 방지가 필요하다. 읽음은 고객 번호 단위로 발신번호·사용자 전체에 공유된다.

기존 답장 검증은 `POST /threads/validate-reply`를 통해 실제 발송과 같은 EUC-KR·앞뒤 공백 제거 정책을 적용한다. 300ms 입력 대기 후 현재 바이트·90바이트 한도·오류를 표시하고 검증 중·초과·미지원 문자·통신 오류에서 버튼과 단축키 발송을 차단한다. 발신자는 캠페인 작성자의 현재 표시명(`display_name` → `name`)을 사용하며 없으면 `알 수 없음`으로 표시한다. 현재 열람자를 작성자로 추정하지 않는다.

이번 추가 수정의 최종 전체 검증은 백엔드 **667개 통과**(Authlib 사용 중단 경고 1건·기존 Alembic 설정 경고 14건), 프런트엔드 **19개 파일·154개 통과**다. Ruff·TypeScript·ESLint·diff 공백 검사와 Next.js 프로덕션 빌드 **18/18 페이지 성공**을 확인했다. 별도 임시 DB의 전체 Alembic upgrade(`0019`) → downgrade(`0018`) → 재upgrade도 통과했으며, 읽음·목록·SSE·발송의 독립 교차 리뷰에서 추가 차단 문제는 없었다. 직전 길이 안내·발신자 표시 단계의 백엔드 631개·프런트엔드 133개 통과는 당시 검증 기록이며 이번 수정의 최종 수치와 구분한다. 검증은 격리 DB·모의 HTTP·React 환경을 사용했으며 실제 공급자 요청·문자 발송·브라우저 E2E·운영 접근은 수행하지 않았다.

변경 계약과 `0019` 호환·배포 절차는 `claudedocs/SPEC.md` §4.3·§8.4와 `deploy/README.md`에 반영했다. 구 프런트엔드의 본문 없는 읽음 요청은 422가 되므로 백엔드·프런트엔드를 함께 배포하고 열린 탭을 새로고침해야 한다. SQLite 대체 발송 쓰기 잠금 구조 개선과 최초 발송 화면의 UTF-8 예상 길이/서버 EUC-KR 불일치는 별도 미해결 사항으로 남긴다.

---

## 2026-09-18 — 최근 커밋 리뷰와 수정 완료

- 범위: `bf232fe` 기준 최근 first-parent 25개 커밋(`405a254..bf232fe`)과 연결된 현재 동작. 작업 브랜치는 `codex/review-recent-commits-20260918`이다.
- 상태: 주요 4건을 수정하고 회귀 테스트·로컬 전체 검증을 완료했다. 커밋·푸시·운영 배포는 수행하지 않았다. DB 마이그레이션은 추가하지 않아 스키마 `0018`을 유지한다.

| 우선순위 | 수정 영역 | 수정 전 재현 | 현재 동작 |
|---|---|---|---|
| P1 | `app/routes/campaigns.py`, `app/services/compose.py`, 캠페인 상세 UI | 25건 예약 중 첫째·셋째 청크 15건 접수, 둘째 청크 10건 시간 초과 → `PARTIAL_FAILED`; 취소는 HTTP 400, 공급자 취소 호출 0회 | 캠페인 상태와 별도로 남은 예약 청크를 판별하고 상세 API의 `canCancelReservation`으로 버튼을 표시한다. 알려진 청크를 취소하되 시간 초과·조회 불명확 행이 있으면 전체 취소로 표시하지 않고 `failureReason`에 콘솔 확인 안내를 남긴다. 명시적인 공급자 거부 코드는 별도로 보존한다. |
| P1 | `app/auth/deps.py`, `app/routes/auth.py` | DB `viewer` 사용자의 기존 `admin` 세션이 DB 역할을 다시 덮어 권한 검사 통과 | 일반 요청과 `/auth/me`는 DB 역할·프로필을 읽는다. 검증 로그인 콜백만 사용자 정보를 갱신하며 삭제 계정은 세션으로 복원되지 않는다. 잘못된 역할 형식은 권한 없음으로 처리하고 반복적인 세션 불일치 경고는 제거했다. |
| P2 | `app/services/report.py`, `app/services/reconcile.py` | 요청 실패가 `ING`/`REG`로 복구돼 실패 0건·대기 1건이어도 캠페인은 `FAILED`, 처리 건수 0이라 변경 이벤트도 누락 | 캠페인을 `DISPATCHING`으로 복구하고 확정 건수와 별도로 변경 여부를 추적해 커밋 후 이벤트를 발행한다. 최초 결과 시각인 `completed_at`은 보존해 알림 정렬·읽음 기준을 유지한다. |
| P2 | `web/lib/chat.ts`, `web/components/chat/useChatStream.ts` | 실패 메시지만 있는 화면은 서버의 성공 복구 이벤트·재연결에 새로고침 0회 | 대기·실패 메시지를 함께 감시한다. 이벤트 기반 갱신과 5~60초 간격 제한을 유지하며, 대화 이동 중 도착한 최근 15초 이내 이벤트도 한 번 보정한다. |

예약 취소 제한은 기존 4월 상태 분기의 공백으로 `8391c9f`에도 남아 있었고, 세션의 DB 역할 덮어쓰기는 `9acc87d`에서 진단만 추가했던 기존 정책이다. 처리 중 복구 후 캠페인 상태 불일치는 `1561e6b`의 복구 경로에서 발생했다. 이번 수정은 검증된 기존 세션의 권한 적용을 바로잡았으며, Keycloak 외부 변경은 여전히 새 로그인으로 DB에 반영한다. 최초 관리자 정책과 `LOGIN` 역할 진단은 유지한다.

검증은 기존 Python 3.14 `.venv`와 로컬 환경에서 수행했다.

- 리뷰 기준선: 백엔드 571개·프런트엔드 16개 파일 99개 테스트 통과. 최초 백엔드 실행의 루프백 바인딩 오류 7건은 허용된 환경에서 재실행해 통과했다.
- 최종 수정본: 루프백 바인딩이 허용된 환경에서 백엔드 전체 **606개 통과**(기존 의존성 사용 중단 경고 8건), 프런트엔드 **17개 파일·109개 통과**. Ruff·TypeScript·ESLint·diff 공백 검사 통과, Next.js 프로덕션 빌드 **18/18 페이지 성공**.
- 회귀 검증은 격리된 메모리/임시 DB·모의 공급자·ASGI 요청·프런트엔드 테스트를 사용했다. 실제 브라우저 E2E, 공급자 실연동·메시지 발송, 운영 배포 검증은 수행하지 않았다.

남은 구조 개선은 SMS 대체 발송 대기 중 SQLite 쓰기 트랜잭션 유지다(`app/services/reconcile.py`, `app/routes/webhook.py`). `623afd3`에 명시된 기존 제약으로, 로컬 WAL DB·모의 공급자에서 조기 SMS 리포트만 있으면 0.004초 만에 HTTP 400 `report before record`, 다른 정상 리포트를 섞으면 이벤트 루프가 5.203초 막힌 뒤 HTTP 400 `processing failed`가 재현됐다. 영속적인 발송 소유권 확보, 외부 요청 대기, 결과 확정의 트랜잭션을 분리하면서 멱등성과 장애 복구를 검증하는 작업이 남아 있다. 기존 런타임/E2E 미완료 항목도 그대로 남아 있다.

문서는 `README.md`, `deploy/README.md`, `claudedocs/SPEC.md`, 본 리뷰와 `HANDOFF.md`를 최종 동작에 맞춰 갱신했다.

---

## 2026-05-30 — 과거 종합 리뷰 보존

아래는 당시 코드와 검증 결과의 기록이며 현재 미해결 목록이 아니다. 현재 리뷰 범위와 결과는 위 2026-09-18 절을 기준으로 본다.

> 리뷰 기간: 2026-05-30 · 방식: 자동 검증(Phase 0) + 전문 에이전트 5인 병렬 리뷰(Phase 1~5) + 교차검증(Phase 6)
> 대상: 백엔드 ~11.2K LOC · 프론트 ~13.6K LOC · 4대 렌즈(UX/기능/코드/알고리즘)

---

## 1. Executive Summary

kotify는 **코드 위생(hygiene)은 우수**하나(테스트 195개 통과, 타입·린트 0 에러, 인증/암호화 설계 견고), **돈과 데이터 정합성이 걸린 핵심 경로에 구조적 결함이 집중**되어 있다.

가장 중요한 단일 결론:

> **"메시지 발송의 안전장치 다수가 '구현은 됐지만 배선되지 않은' dead code 상태다."**
> 중복제거·정산 재조정·답장 검증 함수가 모두 정의만 있고 호출되지 않는다(grep으로 검증 완료). 코드가 존재하므로 안전한 것처럼 보이지만 런타임에는 동작하지 않는다.

이로 인해 **중복 발송·이중 과금·과금 단가 오류·집계 누락**이 실제 운영에서 재현 가능하다. 대량 발송 시스템에서 이는 직접적 금전 손실로 이어진다.

| 영역 | 평가 |
|------|------|
| 인증/인가/암호화 (Phase 1) | 🟢 견고 (CRITICAL 0) |
| 발송 파이프라인 (Phase 2) | 🔴 위험 집중 (CRITICAL 6) |
| 데이터 도메인 (Phase 3) | 🟠 정합성 결함 (CRITICAL 4) |
| 프론트 UX (Phase 4) | 🟠 중복제출·CSRF (CRITICAL 3) |
| 관측성/운영 (Phase 5) | 🟠 배포·감사 (CRITICAL 4) |

---

## 2. 전체 통계

| Phase | 🔴 | 🟠 | 🟡 | 🟢 | 합계 |
|-------|----|----|----|----|------|
| 1 아키텍처/보안 | 0 | 2 | 7 | 4 | 13 |
| 2 발송 파이프라인 | 6 | 6 | 6 | 4 | 22 |
| 3 데이터 도메인 | 4 | 6 | 7 | 4 | 21 |
| 4 프론트 UX | 3 | 5 | 7 | 5 | 20 |
| 5 관측성/운영 | 4 | 5 | 7 | 5 | 21 |
| **합계** | **17** | **24** | **34** | **22** | **97** |

자동 검증(Phase 0): pytest 195 passed · tsc 0 · eslint 0 · ruff 94(86 자동수정 가능, 전부 스타일). 상세: `phase0-baseline.md`

---

## 3. 교차검증 결과 (Phase 6)

에이전트의 가장 강한 주장(dead code)을 grep으로 직접 검증 — **모두 사실로 확인**:

| 주장 | 검증 방법 | 결과 |
|------|----------|------|
| `resolve_recipients`(수신자 중복제거) 미배선 | `grep -rn` → 정의만, 호출 0 | ✅ dead code 확인 |
| `query_sent`·`process_sent_query`·`get_daily_stats`(정산 재조정) 미배선 | 정의만, 호출 0 | ✅ dead code 확인 |
| `validate_reply_content`(답장 길이검증) 미배선 | 정의만, 호출 0 | ✅ dead code 확인 |
| 캠페인 멱등키 부재 | `cli_key`는 메시지 레벨만 존재, campaign_id 재생성 시 무력화 | ✅ 캠페인 레벨 멱등성 없음 확인 |

→ 이 검증으로 종합 리포트의 신뢰도가 확보되었다(거짓 양성 아님).

---

## 4. 교차 테마 — 통합에서만 보이는 시스템 리스크 ⭐

개별 Phase를 넘어 **여러 에이전트가 독립적으로 같은 위험을 다른 각도로 지적**한 패턴. 이것이 진짜 우선순위다.

### 테마 A — 중복 발송: 방어선이 전 계층에 전무 🔴🔴
> 프론트부터 백엔드까지 어느 한 층에도 중복 차단이 없다.
- **P4-🔴** `ComposeForm.tsx:114` 더블클릭 race (setSubmitting 비동기)
- **P2-C1** `campaigns.py:295` 캠페인 멱등키 부재 → 재요청 시 새 campaign_id로 중복
- **P2-C2** `compose.py:599` 수신자 dedup 함수가 dead code → 입력 중복 그대로 발송
- **P2-C3** `compose.py:262` 29002 재시도가 채널 바꿔 재발송 → 부분수락분 중복

### 테마 B — 웹훅 단일 의존: 정산 붕괴 경로 🔴
> 배달 리포트가 100% 웹훅 의존인데, 실패 시 복구 수단이 모두 죽어있다.
- **P1-🟠** `webhook.py:68` + `setup.py:309` setup이 webhook_token을 안 만들어 운영 직후 리포트 전면 401
- **P2-C5** `report.py:82` 웹훅 유실 시 폴링/재조정 경로(query_sent 등) dead → 영구 PENDING
- **P2-H1** `compose.py:535` item 단위 실패가 즉시 카운터에 반영 안 됨 (웹훅 도착 전까지 틀림)
- **P2-H4** `report.py:162` cliKey 없는 리포트의 phone 보조매칭이 엉뚱한 캠페인에 귀속
- **P2-H5** `compose.py:459` 예약 캠페인이 실행돼도 상태 갱신 경로 없어 영구 RESERVED

### 테마 C — 과금 정확성: 견적·청구·집계가 제각각 🔴
- **P2-C4** `codes.py:41` 단문 과금 **견적-실청구 2배 괴리** (✅ Phase 6 외부확인 완료·결론반전): U+ 공식 단가 확인 결과 `(RCS,SMS)=17`은 **정확한 실단가**(RCS 단문 18.7원 VAT포함). 즉 `calculate_cost`는 맞다. **진짜 결함은 견적·문서**가 단문을 "양방향 8원"으로 안내하는 것(양방향은 outbound 불가). 사용자에게 8원 견적 → 실제 17원 청구. 수정은 PRICE_TABLE이 아니라 estimate·SPEC·README 정정. 상세: `phase6-verification.md`
- **P2-H3** `report.py:223` KAKAO 채널이 rcs/fallback 어디에도 분류 안 됨 → breakdown 합 불일치
- **P2-M1** `campaigns.py:329` 발송 직후 estimate.cost가 항상 0원 표시
- **P3-🟡** `numbers.py:81` dailyUsage가 예약수(total_count) 기준이라 실발송과 괴리

### 테마 D — 전화번호 정규화 이중 표준 🔴
> `normalize_phone`이 있는데 CSV import만 쓰고, 직접 API는 안 쓴다.
- **P3-🔴** `contacts.py:370` POST /contacts가 숫자추출만 → 유선번호·국제표기 그대로 저장
- **P3-🔴** `groups.py:505` bulk-add가 숫자추출만 → +82 번호 매칭 실패로 중복 연락처 생성
- **P3-🟠** `contacts.py:398` PATCH 빈 phone(`""`)을 그대로 저장
- → 같은 번호가 경로별로 다르게 저장 → 중복검사·발송 모두 불일치 (테마 A의 dedup과 직결)

### 테마 E — PII(수신자 번호) 노출 🟠
- **P1-🟠** `webhook.py:121` SMS 실패 로그에 전화번호 평문 (발송 실패는 빈번 → 로그 누적)
- **P1-🟢** `models.py:298` MO 원문·raw_payload 무기한 저장, 보존정책 없음
- → PIPA 적용 개인정보. 로그/DB 양쪽에서 노출.

### 테마 F — dead code = 안전장치 착시 (메타 결함) ⭐
> 가장 위험한 종류: "있는 줄 알지만 동작 안 하는" 코드.
- `resolve_recipients`(dedup) / `query_sent`·`process_sent_query`·`get_daily_stats`(정산) / `validate_reply_content`(답장검증) / `estimate_cost`(견적) / `setup_service.complete_setup` 모두 미배선
- P1·P2·P5가 독립 지적 + Phase 6 grep 검증 완료

### 테마 G — 배포 스크립트 취약성 (git 로그가 예고한 위험)
> 최근 커밋 다수가 deploy 버그픽스 — 근본 결함이 남아있다.
- **P5-🔴** `kotify-update.sh:46` 커밋메시지 특수문자(`'` `\` 개행)로 JSON 파괴 → 502
- **P5-🔴** `kotify-update-worker.sh:106` `if ! cmd` + `set -e`로 ERR trap 안 걸려 rollback 중복/누락
- **P5-🟠** `worker.sh:63` PREV_HEAD가 reflog 의존 → reset 후 롤백 대상 오류
- **P5-🟠** `worker.sh:144` ERR trap 해제 후 실패 시 "완료"로 오표시

### 테마 H — 디자인시스템 미사용 + 접근성
- **P4-🔴** `ContactDrawer.tsx:47` / **P4-🟢** `SystemUpdatePanel.tsx:55` window.confirm (Radix Dialog 있는데 미사용)
- **P4-🟠** `CommandPalette.tsx` listbox/option ARIA 오용 + activedescendant 부재
- **P4 다수** SetupWizard 등 htmlFor/id 미연결 (스크린리더 라벨 끊김)

### 테마 I — 감사 로그 누락/불일치
- **P5-🔴** `settings.py:182` patch_org 감사 누락 (provider는 기록하는데 org는 안 함)
- **P5-🟡** `setup.py:328` BOOTSTRAP_INIT vs SETUP_COMPLETED 혼용
- **P3-🟡** `contacts.py:580` 전체 연락처 export에 감사 없음

---

## 5. 🔴 CRITICAL 17건 전체 목록 (테마별)

| # | 위치 | 요약 | 테마 |
|---|------|------|------|
| 1 | `campaigns.py:295` | 캠페인 멱등키 부재 → 중복발송·이중과금 | A |
| 2 | `compose.py:599` | 수신자 dedup dead code → 입력중복 발송 | A,D |
| 3 | `compose.py:262` | 29002 재시도 채널변경 중복발송 | A |
| 4 | `ComposeForm.tsx:114` | 발송 더블클릭 race → 중복접수 | A |
| 5 | `codes.py:41` | 단문 과금 명세-구현-표 3중 불일치 (✅심층검증) | C |
| 6 | `report.py:82` | 웹훅 유실 재조정 dead → 영구 PENDING | B |
| 7 | `webhook.py:178` | MO moKey 누락 시 조용한 유실 + 위변조 주입 | B,E |
| 8 | `csv_import.py:127` | import N+1 쿼리(1000행→2000쿼리) | — |
| 9 | `contacts.py:370` | POST 전화번호 검증 우회 | D |
| 10 | `groups.py:505` | bulk-add 국제번호 매칭 실패 | D |
| 11 | `csv_safe.py:17` | import 경로 CSV injection 방어 없음 | — |
| 12 | `csrf-client.ts:13` | CSRF 토큰 stale(401시 미무효화) | — |
| 13 | `ContactDrawer.tsx:47` | window.confirm 접근성 위반 | H |
| 14 | `settings.py:600` | /system/update/check 인증 패턴 불일치 | — |
| 15 | `kotify-update.sh:46` | 배포 커밋메시지 JSON 파괴 | G |
| 16 | `worker.sh:106` | alembic 실패 감지 + rollback 버그 | G |
| 17 | `settings.py:182` | patch_org 감사 로그 누락 | I |

> 주: Phase 5 문서 통계표의 합계 표기 오류(14)가 있으나 실제 🔴는 4건(위 #14~17). 본 종합은 실집계 17건 기준.

---

## 6. 권장 수정 로드맵 (우선순위)

### P0 — 즉시 (금전·오발송 직결, 이번 주)
1. **중복 발송 3중 차단** (테마 A): ① `dispatch_campaign` 진입부 `dict.fromkeys` dedup 배선 ② POST /campaigns Idempotency-Key + UNIQUE ③ ComposeForm `useRef` 동기 가드. → 한 묶음으로 처리해야 효과.
2. **과금 견적·문서 정정** (C4, ✅외부확인 완료): PRICE_TABLE 17원은 U+ 공식값으로 **유지**. `_ESTIMATE_MAP["short"]` min을 `(RCS,CHAT)8`→`(RCS,SMS)17`로, SPEC/README 단문 단가를 17원으로 정정. estimate_cost 배선(M1)도 함께.

### P1 — 긴급 (데이터 정합성, 2주 내)
3. **웹훅 재조정 배선** (C5): `query_sent`/`process_sent_query`를 주기 작업으로 실제 연결 (멱등성 이미 구현됨).
4. **webhook_token 자동 생성** (P1-🟠): setup/complete에서 `secrets.token_hex` 생성·저장·노출.
5. **전화번호 정규화 통일** (테마 D): 모든 입력 경로가 `normalize_phone` 호출.
6. **import N+1 제거** (P3-🔴): IN 쿼리 일괄 조회.

### P2 — 중요 (안정성, 1개월)
7. MO 안전(C6), 상태머신 정합(H1/H4/H5/H6), CSRF stale(P4), import 트랜잭션 경계(P3), 답장 검증 배선(H2).

### P3 — 운영 (컴플라이언스/배포)
8. 배포 스크립트 JSON·rollback 수정(테마 G), 감사 로그 보강(테마 I), PII 로그 마스킹(테마 E).

### P4 — 품질 (상시)
9. `ruff --fix`로 86건 자동정리, dead code 제거/배선 명확화, 접근성(window.confirm→Dialog, ARIA, htmlFor).

---

## 7. 테스트 갭 연계 (Phase 0 → Phase 6)

Phase 0이 발견한 "**테스트 커버리지가 리스크 역방향**"이 이번 리뷰로 증명됨 — 🔴 17건 중 발송/웹훅 영역(테스트 없는 곳)에 11건 집중.

**회귀 테스트 백로그 (수정과 함께 필수)**:
- `compose.py` dedup·멱등키·fallback 분기·비용계산 (현재 1개 테스트만)
- `msghub/client.py`·`auth.py` (현재 0)
- `webhook.py` 멱등성·서명검증 (현재 0)
- `report.py` 집계·재조정 (현재 0)
- 프론트 발송 플로우 E2E 1개 이상 (현재 0)

---

## 8. 부록 — 상세 문서

| Phase | 문서 |
|-------|------|
| 0 베이스라인 | `claudedocs/review/phase0-baseline.md` |
| 1 아키텍처/보안 | `claudedocs/review/phase1-architecture.md` |
| 2 발송 파이프라인 | `claudedocs/review/phase2-send-pipeline.md` |
| 3 데이터 도메인 | `claudedocs/review/phase3-data-domain.md` |
| 4 프론트 UX | `claudedocs/review/phase4-frontend-ux.md` |
| 5 관측성/운영 | `claudedocs/review/phase5-ops.md` |
| 6 심층검증(C1·C2·C4·C5) | `claudedocs/review/phase6-verification.md` |
| 원본 도구 출력 | `claudedocs/review/_ruff.txt`, `_pytest.txt`, `_tsc.txt`, `_eslint.txt` |

> 본 리뷰는 **발견 중심(리뷰만, 코드 미수정)**이다. 수정 착수는 P0 로드맵부터 권장한다.
