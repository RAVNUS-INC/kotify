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
- ~~**window.confirm** (5곳: 연락처/발신번호/그룹 삭제·예약 취소·시스템 업데이트)~~ → ✅ `84ea2c4`. **Vitest+RTL 인프라 선도입**(`1e91337`) 후, Radix 기반 `useConfirm` 훅(Promise 기반, 전역 Provider 없음) 신규 생성 + 5개 호출부 sync→async 최소 리팩터링. 검증: 컴포넌트 동작 7건(확인=true·취소/ESC=false) + tsc 0 + eslint 0 + **next build 성공(18/18)**. (잔여: `CampaignDetailActions` 의 `alert()` 는 별개 — 미스코프)
- ~~**배포** `kotify-update.sh`(JSON 파괴)/`worker.sh`(alembic 롤백)~~ → ✅ `e26047b`. #15 sed+awk→`python3 json.dumps`(악성 메시지 valid JSON 검증), #16 `if ! alembic` 가드 제거→bare 명령으로 ERR trap 롤백 발동(trap 발동 차이 재현 검증). 정적 검증만(배포 환경 부재).

### C. P3/P4
- ~~PII 로그 마스킹~~ → ✅ `649f8da`. `mask_phone`(앞3·뒤4) + 3개 로그 사이트(webhook/report×2) + 회귀 8건.
- ~~ruff `--fix`~~ → ✅ `e10c9f6`(safe 자동수정 106: UP045/I001/F401/UP041/UP006), `7aeab6f`(`.claude` 워크트리 lint 제외), `3840179`(B904 예외체이닝 5). **실소스 ruff 위반 0**(미커밋 threads.py 제외). pytest 271 유지.
- ~~프론트 테스트 인프라 도입 (Vitest)~~ → ✅ `1e91337` (Vitest+RTL+jsdom, `pnpm test`). 발송 플로우 E2E(Playwright)는 별도 미도입.
- ~~양방향 8원 전환~~ → **❌ 비가능(not viable)**. 공식 스펙(`doc.msghub.uplus.co.kr/guide/d/rcs`) 확인: 양방향 발송(`/msg/v1.1/bi/rcs`)은 `replyId`+`moRecvDt` 필수 = **MO(inbound) 응답 전용**. outbound 브로드캐스트는 응답할 MO 가 없어 불가 → 단방향 RCS SMS형 17원(C4 확정)이 유일 경로. 코드 변경 없음(compose.py 에 이미 문서화).

## 성공 패턴 (재현할 것)
- 검증: `.venv/bin/pytest -q -p no:cacheprovider` / `(cd web && node_modules/.bin/tsc --noEmit)` / `next lint` / **`(cd web && pnpm test)`**(Vitest, 신규)
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
**리뷰 백로그 사실상 완료.** 이번 resume 세션: 상태머신 P2-E(H4/H1/H5) + CSV injection +
PII 마스킹 + 배포 스크립트 + C3 외부검증 + window.confirm(프론트 테스트 인프라 포함) +
**P4 전건(ruff 정리·양방향 8원 검증)** 완료. 백엔드 271 / 프론트 7 / 실소스 ruff 0 /
next build OK. **리뷰의 🔴 전부 해소 + P4 종결.**

남은 것 (모두 선택·저우선):
1. **미커밋 `threads.py`** — 세션 전부터 있던 변경(내 작업 아님). 커밋 시 ruff 6건(I001/F841/B904×2 등) 함께 정리 가능.
2. (선택) 발송 플로우 E2E(Playwright), `alert()` → toast(CampaignDetailActions) 등 UX 개선.
