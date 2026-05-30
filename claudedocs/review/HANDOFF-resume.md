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
- **C3** `compose.py:262` 29002 재시도 중복발송 — msghub 부분수락 의미론 **외부 확인 필요**(C4처럼 msghub 스펙). 확인 전엔 보수적 처리(재시도 시 query_sent로 기접수분 제외).
- **CSV injection** — export 일관성이 근본 방어. `audit_api.py`/`reports.py` export가 `safe_csv_cell` 쓰는지 확인 후 누락 보강(export_contacts는 이미 적용).
- **window.confirm** `ContactDrawer.tsx:47`, `SystemUpdatePanel.tsx:55` — Radix Dialog 기반 ConfirmDialog로 교체. ⚠️ 프론트 테스트 인프라 없음(tsc/eslint만).
- **배포** `deploy/kotify-update.sh`(커밋메시지 JSON 파괴), `kotify-update-worker.sh`(alembic 실패감지) — 셸, 로컬 검증 어려움. Python/jq JSON 직렬화로 교체.

### C. P3/P4
- PII 로그 마스킹 (`webhook.py:121` 전화번호 평문 → 010****1234)
- ruff `--fix` 86건 (스타일 일괄, 변경 후 pytest)
- 프론트 테스트 인프라 도입 (Playwright/Vitest) → 발송 플로우 E2E
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
상태머신 P2-E 완료. 남은 미해결 🔴/🟠 (각각 제약 있음, 권장 순):
1. **CSV injection** (🔴) — `audit_api.py`/`reports.py` export가 `safe_csv_cell` 쓰는지 확인 후 누락 보강 (`export_contacts`는 이미 적용). 백엔드·테스트 가능 → **다음 권장**
2. **window.confirm** (🔴/🟢) — `ContactDrawer.tsx:47`/`SystemUpdatePanel.tsx:55` → Radix ConfirmDialog. ⚠️ 프론트 테스트 인프라 없음(tsc/lint만)
3. **배포 스크립트** (🔴) — `kotify-update.sh`(JSON 파괴)/`worker.sh`(alembic 실패감지). 셸, 로컬 검증 어려움 → Python/jq 직렬화
4. **C3** (🔴) — `compose.py:262` 29002 재시도 중복발송. ⚠️ **msghub 부분수락 의미론 외부 확인 필요**(C4처럼). 확인 전 보수적 처리만
5. P3/P4: PII 로그 마스킹 · ruff --fix 86건 · 프론트 테스트 인프라 · 양방향 8원
