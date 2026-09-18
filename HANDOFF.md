# Handoff — 현재 상황 요약

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
- 남은 단계: 배포 직후 진단을 포함한 새 LOGIN 이벤트는 0건이다. 사용자가 먼저 테스트할 계정으로 로그아웃·재로그인하면 진단 필드와 최종 역할을 대조한다. 원인이 확인되면 앱 파서·Keycloak 매퍼·기존 세션 중 해당 지점을 수정한다. 상세 조회 및 원인별 조치는 `deploy/README.md`를 따른다.

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
