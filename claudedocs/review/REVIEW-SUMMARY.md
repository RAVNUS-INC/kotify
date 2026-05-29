# kotify 코드 리뷰 — 종합 리포트

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
