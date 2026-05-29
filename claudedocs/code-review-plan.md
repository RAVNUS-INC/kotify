# kotify 코드 리뷰 기획안

> 작성일: 2026-05-30
> 대상: kotify (U+ msghub 기반 한국형 RCS/SMS 대량 발송 시스템)
> 목적: UX · 기능 · 코드 품질 · 알고리즘 4대 관점에서 개선점과 버그를 체계적으로 발굴

---

## 1. 프로젝트 스냅샷

| 항목 | 내용 |
|------|------|
| 도메인 | U+ msghub 기반 RCS-first 대량 메시지 발송 (SMS/LMS/MMS auto-fallback) |
| 백엔드 | FastAPI + SQLAlchemy 2.0 + SQLite(WAL), Python 3.12+ · **~11.2K LOC** |
| 프론트 | Next.js 14 (App Router, RSC-first) + TypeScript + Tailwind · **~13.6K LOC** |
| 인증 | Authlib + Keycloak OIDC, RBAC (viewer / sender / admin) |
| 보안 | Fernet 비밀값 암호화, CSRF, 2-tier guard(middleware+layout), 감사로그 |
| 외부 연동 | U+ msghub API (JWT + SHA512), 웹훅 수신 |
| 테스트 | pytest ~2.1K LOC, 16개 파일 (백엔드 위주, **프론트 테스트 없음**) |
| 배포 | Proxmox LXC 단일 컨테이너, 웹 기반 setup/update |

### 도메인 리스크 (리뷰 우선순위를 결정하는 핵심)

1. **금전 직결** — 건당 8~85원, 캠페인당 최대 1,000명. 발송 로직 버그 = 돈 손실 + 오발송 사고
2. **외부 연동 의존** — msghub API 실패/타임아웃/재시도/멱등성, 웹훅 위변조·중복 수신
3. **보안 민감** — 비밀값 평문 노출, CSRF, 권한 우회(RBAC), 감사 누락

---

## 2. 리뷰 4대 렌즈 (모든 Phase에 공통 적용)

각 Phase에서 아래 4가지 관점을 **동시에** 적용한다. 같은 코드라도 렌즈가 다르면 다른 결함이 보인다.

| 렌즈 | 핵심 질문 | 대표 결함 유형 |
|------|----------|---------------|
| 🧭 **UX** | 사용자가 막히거나 오해하는 곳은? | 로딩/에러/빈 상태 누락, 비직관적 플로우, 피드백 부재, 접근성 |
| ⚙️ **기능** | 명세대로 동작하는가? 엣지 케이스는? | 경계값 버그, 누락된 검증, 상태 전이 오류, race condition |
| 🧹 **코드** | 읽기 쉽고 안전하고 유지보수 가능한가? | 중복, 강결합, 죽은 코드, 일관성 부재, 타입 안전성 |
| 🔢 **알고리즘** | 정확하고 효율적인가? | O(n²)·N+1 쿼리, 잘못된 정렬/정규화, 부동소수점, 비용 계산 오류 |

---

## 3. 심각도 분류 체계

발견 항목은 아래 4단계로 태그한다 (사용자 RULES.md 우선순위 체계 차용).

| 등급 | 의미 | 예시 | 조치 |
|------|------|------|------|
| 🔴 **CRITICAL** | 보안/데이터/금전 사고 | 오발송, 권한 우회, 비밀값 노출, 멱등성 실패 | 즉시 수정 |
| 🟠 **HIGH** | 기능 깨짐 / 명백한 버그 | 잘못된 fallback, 상태 전이 오류 | 이번 사이클 내 수정 |
| 🟡 **MEDIUM** | UX 저하 / 품질 부채 | 에러 상태 누락, 중복 로직 | 계획적 개선 |
| 🟢 **LOW** | 권장 개선 | 네이밍, 사소한 리팩터 | 여유 시 |

각 발견 항목 기록 형식:
```
[등급][렌즈] 파일:라인 — 한 줄 요약
  근거: 무엇이 왜 문제인가 (재현 조건 포함)
  제안: 어떻게 고칠 것인가
```

---

## 4. Phase별 상세 계획

리뷰는 **리스크 높은 순 → 의존성 낮은 순**으로 진행한다. 발송 파이프라인이 가장 먼저인 이유는 금전·사고 직결이기 때문이다.

### Phase 0 — 베이스라인 & 자동 검증 게이트 ⏱️ 0.5d

> "사람이 보기 전에 기계가 먼저 거른다." 정적 분석으로 저수준 결함을 제거하고 출발점을 측정.

**작업**
- [ ] `ruff check app/` — 린트/import/버그 패턴 (B 규칙 포함)
- [ ] `pytest -q` — 현재 16개 테스트 통과 여부 + 실행시간 베이스라인
- [ ] `cd web && pnpm typecheck` (tsc --noEmit) — 타입 에러 수집
- [ ] `cd web && pnpm lint` (eslint) — 프론트 린트
- [ ] 의존성 취약점 점검 (pip/npm audit 수준)
- [ ] 테스트 커버리지 맵: 어느 모듈에 테스트가 **없는지** 식별

**산출물**: `claudedocs/review/phase0-baseline.md` (도구별 결과 + 커버리지 공백 지도)

---

### Phase 1 — 아키텍처 & 횡단 관심사 ⏱️ 1d

> 개별 파일 전에 "전체 구조와 경계"를 본다. 여기서 발견한 패턴 문제는 모든 Phase에 영향.

**대상**: `app/main.py`, `app/config.py`, `app/db.py`, `app/models.py`, `app/auth/*`, `app/security/*`, `web/middleware.ts`, `web/lib/api.ts`, `web/app/(app)/layout.tsx`

**렌즈별 체크포인트**
- ⚙️ **인증/인가**: OIDC 흐름(`oidc.py`), 2-tier guard(middleware+layout) 우회 가능성, RBAC(viewer/sender/admin) 강제가 모든 라우트에 일관되게 걸리는가 — `deps.py` 의존성 주입 검증
- 🔴 **보안 기반**: Fernet 키 관리(`crypto.py`), CSRF 토큰 생성·검증(`csrf.py`), 비밀값 저장(`settings_store.py`) 평문 노출 경로
- 🧹 **레이어 경계**: routes → services → msghub/db 의존 방향이 단방향인가, 비즈니스 로직이 라우트에 새지 않는가
- ⚙️ **에러/로깅 일관성**: 예외 처리 패턴 통일성, 민감정보 로그 유출
- 🧹 **데이터 모델**: `models.py` 관계·인덱스·제약조건, 마이그레이션(alembic)과 모델 일치

**예상 핫스팟**: 2-tier guard의 틈(미들웨어 통과 후 layout 미검증 경로), `/api/*` rewrite 신뢰 경계

**산출물**: `claudedocs/review/phase1-architecture.md` + 아키텍처 다이어그램(텍스트)

---

### Phase 2 — 발송 파이프라인 (Critical Path) ⏱️ 2d 🔴 최우선

> 금전·사고 직결 핵심. 가장 깊게, 가장 꼼꼼히. 알고리즘 렌즈 비중 ↑

**대상**: `services/compose.py`(629), `routes/campaigns.py`(663), `routes/threads.py`(416), `services/chat.py`(370), `msghub/client.py`(471), `msghub/auth.py`(240), `msghub/codes.py`(127), `msghub/schemas.py`(375), `routes/webhook.py`(282)

**렌즈별 체크포인트**
- 🔢 **fallback 알고리즘**: RCS→SMS/LMS/MMS 전환(`fbInfoLst`) 조건 분기 정확성 — 텍스트 길이 경계(SMS↔LMS), 이미지 유무(MMS) 판정, 채널별 비용 계산이 README 표(8/9/27/40/85원)와 일치하는가
- 🔴 **멱등성·중복발송**: 네트워크 타임아웃 후 재시도 시 같은 메시지 2번 발송 방지 장치, 캠페인 재실행 가드
- 🔴 **수신자 한도**: 1,000명 제한 강제 위치 (검증 우회 가능?), `test_recipient_limit.py`와 실제 코드 일치
- ⚙️ **msghub 연동**: JWT 발급/만료/갱신(`auth.py`), SHA512 해싱 정확성, HTTP 에러·타임아웃 처리, 응답 코드 매핑(`codes.py`)
- 🔴 **웹훅 보안**: 서명/토큰 검증, 위변조 거부, 중복 콜백 멱등 처리, 상태 전이(발송→전달→실패) 정합성
- ⚙️ **상태 머신**: 캠페인/수신자 상태(pending→sent→delivered/failed) 전이 누락·역행 가능성
- 🧭 **UX**: 발송 진행률 피드백, 부분 실패 시 사용자 인지, 비용 사전 고지

**예상 핫스팟**: fallback 분기의 경계 조건, 웹훅 멱등성, 재시도 중복발송, JWT 갱신 race

**산출물**: `claudedocs/review/phase2-send-pipeline.md` (발견 버그는 재현 시나리오 필수)

---

### Phase 3 — 데이터 도메인 (연락처·그룹·번호) ⏱️ 1.5d

> 대량 데이터 정합성과 입력 안전성. CSV injection·전화번호 정규화가 핵심.

**대상**: `routes/contacts.py`(592), `routes/groups.py`(558), `routes/numbers.py`(389), `services/contacts.py`, `services/groups.py`, `services/csv_import.py`(211), `util/phone.py`(74), `util/csv_safe.py`, `util/text.py`

**렌즈별 체크포인트**
- 🔢 **전화번호 정규화**: 010/+82/하이픈 변형 처리(`phone.py`) 정확성, 잘못된 번호 거부, 국제번호 엣지 케이스 — `test_phone.py` 커버리지 확인
- 🔴 **CSV injection**: `=`, `+`, `-`, `@` 시작 셀 무력화(`csv_safe.py`), import/export 양방향 검증 — `test_csv_import.py`
- 🔢 **대량 처리 성능**: CSV import N건 처리 시 N+1 쿼리, 중복 검사 O(n²), 메모리 — bulk insert 사용 여부
- ⚙️ **중복·정합성**: 연락처 중복 판정 기준, 그룹 멤버십 정합성, 번호 등록 상태 전이
- 🧭 **UX**: import 부분 실패 리포트(`ContactImportDialog`), 검증 에러 메시지 명확성, 대량 작업 진행 표시

**예상 핫스팟**: CSV import 성능/부분실패, 전화번호 엣지 케이스, 그룹 대량 추가(`GroupMembersBulkAddDialog`)

**산출물**: `claudedocs/review/phase3-data-domain.md`

---

### Phase 4 — 프론트엔드 UX & 상태관리 ⏱️ 2d

> 사용자가 실제로 만지는 표면. 프론트 테스트가 0이므로 수동 검증 비중 ↑. (선택: `--frontend-verify`로 Playwright 검증)

**대상**: `components/send/ComposeForm.tsx`(403), `components/setup/SetupWizard.tsx`(430), `components/chat/*`(ThreadView, useChatStream, MessageBubble, ThreadComposer), `components/search/CommandPalette.tsx`(278), `components/contacts/ContactDrawer.tsx`(230), `lib/*-client.ts`, `lib/csrf-client.ts`

**렌즈별 체크포인트**
- 🧭 **상태 3종 세트**: 모든 비동기 화면에 로딩/에러/빈 상태가 있는가 (`loading.tsx`, `error.tsx`, `EmptyState`)
- ⚙️ **낙관적 업데이트·동기화**: 채팅 스트림(`useChatStream`) 폴링/재연결, 메시지 순서, 중복 렌더
- 🔴 **CSRF 클라이언트**: `csrf-client.ts` 토큰 주입이 모든 변경 요청에 적용되는가
- 🧭 **접근성**: 키보드 내비(CommandPalette), 포커스 트랩(Drawer/Dialog), ARIA, 색 대비, `useReducedMotion` 준수
- 🧭 **발송 플로우 UX**: ComposeForm 검증 타이밍, 비용/수신자 수 실시간 표시, 첨부 업로드(`AttachmentPicker`) 실패 처리
- 🧹 **클라이언트 계층 일관성**: `lib/*-client.ts` 에러 처리·타입 통일, RSC/CSR 경계 적절성
- 🔢 **렌더 성능**: 대량 리스트(ThreadList, ContactsTable) 가상화/페이지네이션, 불필요한 리렌더

**예상 핫스팟**: useChatStream 재연결/메모리 누수, ComposeForm 비용 계산 프론트-백엔드 불일치, 대량 테이블 성능

**산출물**: `claudedocs/review/phase4-frontend-ux.md` (가능 시 스크린샷/콘솔 로그 첨부)

---

### Phase 5 — 관측성 & 운영 (리포트·대시보드·감사·설정·배포) ⏱️ 1d

> 데이터 정확성과 운영 안전. 집계 알고리즘과 권한이 핵심.

**대상**: `routes/settings.py`(734), `routes/reports.py`(498), `routes/notifications.py`(380), `routes/search.py`(320), `routes/dashboard.py`(229), `services/report.py`, `services/audit.py`, `routes/setup.py`(347), `deploy/*`, `components/settings/SystemUpdatePanel.tsx`

**렌즈별 체크포인트**
- 🔢 **집계 정확성**: 리포트/대시보드 KPI 계산, KST 시간대 처리(`util/time.py`, `test_dashboard_kst.py`), 일별 버킷팅 경계
- 🔴 **설정 보안**: `settings.py` 비밀값 마스킹, provider 설정 변경 권한, API 키 노출
- 🔴 **셋업 ACL**: `setup.py` 최초 1회 셋업 후 재접근 차단(`test_setup_acl.py`), 권한 우회
- ⚙️ **감사 완전성**: 모든 민감 작업이 audit에 기록되는가, 누락 액션 식별
- 🔴 **시스템 업데이트**: `deploy/update.sh` 원클릭 배포 안전장치 (git 로그상 다수 배포 버그 이력 → 집중 점검), 롤백 안전성, race condition
- 🔢 **검색**: `search.py` 쿼리 인젝션, 성능, 결과 정확성

**예상 핫스팟**: KST 경계 집계 오류, 배포 스크립트(최근 커밋 다수가 deploy 버그픽스), 설정 권한

**산출물**: `claudedocs/review/phase5-ops.md`

---

### Phase 6 — 테스트 갭 & 종합 ⏱️ 1d

> 발견 사항을 회귀 테스트로 고정하고 전체를 종합.

**작업**
- [ ] Phase 0의 커버리지 공백 지도와 대조 — Critical Path(Phase 2)에 테스트 없는 곳 우선
- [ ] 발견된 🔴/🟠 버그마다 재현 테스트 작성 가능성 평가
- [ ] 프론트 테스트 부재에 대한 최소 권고 (발송 플로우 E2E 1개라도)
- [ ] 전체 발견 항목 통합 → 심각도별 정렬 → 수정 로드맵

**산출물**: `claudedocs/review/REVIEW-SUMMARY.md` (경영진/팀 공유용 종합 리포트 + 우선순위 백로그)

---

## 5. 실행 순서 & 일정 요약

| Phase | 주제 | 리스크 | 예상 | 의존성 |
|-------|------|--------|------|--------|
| 0 | 베이스라인 & 자동검증 | — | 0.5d | 없음 |
| 1 | 아키텍처 & 횡단 | 🔴 | 1d | 0 |
| 2 | **발송 파이프라인** | 🔴🔴 | 2d | 1 |
| 3 | 데이터 도메인 | 🟠 | 1.5d | 1 |
| 4 | 프론트 UX | 🟡 | 2d | 1 |
| 5 | 관측성/운영 | 🟠 | 1d | 1 |
| 6 | 테스트 갭 & 종합 | — | 1d | 2~5 |

**총 예상**: ~9 영업일 (1인 기준). 병렬화 시 Phase 3·4·5는 동시 진행 가능 → ~5~6일로 단축.

---

## 6. 방법론 & 도구 활용

- **정적 분석 우선**: ruff / tsc / eslint를 Phase 0에서 일괄 → 사람은 도구가 못 잡는 로직·설계·UX에 집중
- **렌즈 교차 검증**: 같은 파일을 4대 렌즈로 각각 통과시켜 누락 방지
- **증거 기반**: 모든 🔴/🟠 발견은 재현 조건 또는 코드 라인 근거 필수 (RULES.md: Evidence > assumptions)
- **에이전트 병렬화(선택)**: 독립적인 Phase 3·4·5는 전문 에이전트로 병렬 위임 가능
  - 백엔드 로직 → `architect` / 보안 → `security-reviewer` / 프론트 → `designer` / 코드품질 → `code-reviewer`
- **프론트 검증(선택)**: `--frontend-verify` (Playwright + Chrome DevTools)로 실제 동작·접근성 확인

---

## 7. 진행 추적

각 Phase 완료 시 `claudedocs/review/` 하위에 결과 문서를 남기고, 최종 `REVIEW-SUMMARY.md`에 통합한다.
발견 항목은 심각도 태그로 정렬해 수정 우선순위 백로그로 전환한다.
