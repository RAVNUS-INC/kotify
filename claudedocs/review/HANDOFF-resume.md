# kotify 코드 리뷰 수정 — 인계 문서 (resume)

> 작성: 2026-05-30 · 브랜치: `vibrant-shamir-e74f49` (feature)
> 전체 리뷰: `claudedocs/review/REVIEW-SUMMARY.md` · C4 검증: `phase6-verification.md`

## 목표
`REVIEW-SUMMARY.md` 우선순위 백로그를 차례로 수정. **각 수정 = 코드 + 회귀 테스트 + atomic 커밋**.

## 완료 (이번 세션, 15 커밋 push 완료)
- **P0**: C1 멱등키 · C2 dedup · 프론트 더블클릭 race · C4 과금 정정
- **P1**: 전화번호 정규화 통일 · CSV import N+1 · webhook_token 자동생성 · C5 웹훅 재조정
- **P2**: C6 MO 안전 · CSRF stale · settings 인증/감사 · H2 답장검증 · import 트랜잭션 · H6 취소 오표기
- **🔴 12/17 해결 · 테스트 195 → 248 (+53)**

## 남은 작업 (우선순위 순)

### A. 상태머신 P2-E (🟠) — ✅ 완료 (H6·H4·H1·H5 전건, 테스트 248→259)
- ~~**H4** phone 보조매칭이 "가장 최근 미완료 1건"에 오귀속~~ → **정확히 1건일 때만 매칭, 2건+면 보류(로그)**. ✅ `00acc59` (`report.py:_find_message`, limit(2) 유일성 판별, 테스트 3건)
- ~~**H1** HTTP 200 응답 내 item 실패가 dispatch 카운터 미반영~~ → `_create_messages_from_response`가 `(accepted, failed)` 반환, `_dispatch_rcs_chunks`가 `item_failed` 누적, dispatch가 `failed_recipients`에 합산. ✅ `e9a2f04` (테스트 5건). 청크실패·item실패는 서로소라 이중계산 없음.
- ~~**H5** 예약 캠페인 영구 RESERVED 우려~~ → **코드 추적 결과 기존 경로가 이미 정확**(`_refresh_campaign_counters` 전이대상에 RESERVED 포함 + reconcile는 메시지 status/sent_at으로만 필터). production 무변경, 웹훅·재조정 양쪽 완료 전이를 **회귀 테스트로 고정**. ✅ `d3afe80` (테스트 3건)

### B. 미해결 🔴 (다른 Phase, 제약 있음)
- ~~**C3** 29002 재시도 중복발송~~ → **❌ 반증(false positive)**. LG U+ 공식 스펙 확인: CPS=요청 단위 레이트리밋, 29002=HTTP 400 최상위 code(요청 전체 거부)라 접수분 0 → `-fb` 재시도 중복 불가. 부분수락은 HTTP 200+`data[].code`(H1) 경로뿐. 코드 무변경 + 확정 주석 + 회귀 1건. ✅ `553ddd3` (검증: `c3-verification.md`)
- ~~**CSV injection** — export 일관성이 근본 방어~~ → **전 4개 export 경로(audit_api/campaigns/reports/contacts) 인스펙션 결과 모든 사용자 입력 컬럼이 `safe_csv_cell` 적용됨**(숫자 컬럼은 서버 계산값이라 안전). 방어 완전·일관 확인, 누락 0. `safe_csv_cell` 테스트 커버리지 0 → 회귀 고정. ✅ `039b285` (테스트 3건)
- **window.confirm** `ContactDrawer.tsx:47`, `SystemUpdatePanel.tsx:55` — Radix Dialog 기반 ConfirmDialog로 교체. ⚠️ 프론트 테스트 인프라 없음(tsc/eslint만). **남은 유일한 프론트 🔴**.
- ~~**배포** `kotify-update.sh`(JSON 파괴)/`worker.sh`(alembic 롤백)~~ → ✅ `e26047b`. #15 sed+awk→`python3 json.dumps`(악성 메시지 valid JSON 검증), #16 `if ! alembic` 가드 제거→bare 명령으로 ERR trap 롤백 발동(trap 발동 차이 재현 검증). 정적 검증만(배포 환경 부재).

### C. P3/P4
- ~~PII 로그 마스킹~~ → ✅ `649f8da`. `mask_phone`(앞3·뒤4) + 3개 로그 사이트(webhook/report×2) + 회귀 8건.
- ruff `--fix` 86건 (스타일 일괄, 변경 후 pytest) — **다음 권장**(저위험·검증가능)
- 프론트 테스트 인프라 도입 (Playwright/Vitest) → 발송 플로우 E2E (window.confirm 검증 전제)
- 양방향 8원 전환 (U+ outbound 양방향 CHAT 가능 여부 확인)

## 성공 패턴 (재현할 것)
- 검증: `.venv/bin/pytest -q -p no:cacheprovider` / `(cd web && node_modules/.bin/tsc --noEmit)` / `next lint`
- ruff: 변경분 **새 위반 0**만 확인 (`ruff check <file> | grep -E "B[0-9]{3}|F[0-9]{3}"`), 기존 부채(UP045/I001/B904)는 P4
- 병렬 Bash는 `; true`로 exit 정규화 (non-zero가 배치 취소시킴)
- atomic 커밋, conventional 한국어 메시지, **AI 흔적 없음**(CLAUDE.md 규칙)
- 코드베이스 관용: 지역 import(순환 회피), `db.begin_nested()`(savepoint), self-healing loop, `_FakeClient` 덕타이핑 모킹
- **외부 확인이 방향을 바꾼다**: C4는 코드만 보면 17→9 역행했을 것을 U+ 단가 확인으로 정정. C3도 동일하게 외부 확인 선행.

## 주의
- `app/routes/threads.py`(M), `app/util/time.py`(??), `.claude/` = **세션 전 미커밋**(내 작업 아님). 커밋에서 제외 유지.
- 테스트는 `Base.metadata.create_all`(모델 기반). 마이그레이션(alembic)은 모델과 일치하게 별도 작성.
- 단일 워커(`--workers 1`) 전제 — lifespan 백그라운드 태스크 안전.

## 다음 단계 (바로 시작)
이번 resume 세션: 상태머신 P2-E(H4/H1/H5) + CSV injection + PII 마스킹 + 배포 스크립트
+ C3 외부검증 완료 (테스트 **248→271**, 8 fix/test 커밋 + docs). **검증 가능한 백엔드
🔴/🟠 전부 처리.** 남은 항목 (모두 검증 제약·옵트인 필요):
1. **window.confirm → ConfirmDialog** (🔴, 프론트) — `ContactDrawer.tsx:47`/`SystemUpdatePanel.tsx:55`. ⚠️ 프론트 테스트 인프라 없어 tsc/eslint+인스펙션만 — **검증 방식 합의 또는 프론트 테스트 인프라 먼저**.
2. **ruff `--fix` 86건** (P4) — 스타일 일괄정리. 저위험·`pytest`로 검증 가능하나 큰 noise 디프 → 옵트인 권장. 변경분만, 기존 부채(UP045/I001/B904) 신중히.
3. P4 기타: 프론트 테스트 인프라(Vitest/Playwright) · 양방향 8원(U+ outbound 양방향 CHAT 가능 여부).
