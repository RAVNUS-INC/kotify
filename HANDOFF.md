# Handoff — 현재 상황 요약

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
