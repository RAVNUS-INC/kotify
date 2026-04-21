# Phase 10d — Runtime Audit

`motion-timing.md` Phase 11+ 섹션에서 남긴 세 가지 실측 과제와
reduced-motion·axe 실사를 수행한 결과를 기록한다.

**측정 환경**

| 항목 | 값 |
|---|---|
| 측정 일자 | 2026-04-21 |
| Next.js | 14.2.35 (production `next start`) |
| FastAPI | uvicorn, `SMS_DEV_MODE=true` |
| 브라우저 | Chromium (Chrome DevTools MCP) |
| 하드웨어 | Apple Silicon M-series (개발 머신) |

> 측정은 **production build + next start** 기준. dev 모드는 HMR/Fast Refresh
> 오버헤드가 있어 실측에 부적합.

## 범위 결정

### 자동 실측 가능

- ✅ **공개 페이지**: `/login`, `/offline` — 인증 미들웨어 우회
- ✅ Lighthouse (Performance / A11y / Best Practices / SEO)
- ✅ Performance trace (FCP, LCP, CLS, TBT)
- ✅ `prefers-reduced-motion: reduce` emulate
- ✅ axe-core 주입 실사

### 수동 체크리스트 (Keycloak 구성 필요)

- ⏳ `/` Dashboard — RcsDonut + KpiCards 동시 연출
- ⏳ `/campaigns/[id]` — CampaignKpis + FallbackFlow
- ⏳ `/reports` — ReportKpi × 4 + Sparkline × 4 + AnimatedBars + ChannelBreakdown
- ⏳ `/notifications` — Rise stagger 20 items
- ⏳ `/groups/[id]` — GroupKpis Counter × 3
- ⏳ `/chat/[id]` — SSE 스트림, 실시간 접속 상태

인증이 필요한 페이지는 배포 환경(Phase 11 이후)에서 재측정 예정.

---

## 1. Lighthouse — 공개 페이지

### `/login`

| 카테고리 | 점수 | 비고 |
|---|---|---|
| Performance | _측정 중_ | — |
| Accessibility | _측정 중_ | — |
| Best Practices | _측정 중_ | — |
| SEO | _측정 중_ | — |

핵심 메트릭:

| 메트릭 | 값 | 기준 | 판정 |
|---|---|---|---|
| FCP | _측정 중_ | <1.8s | — |
| LCP | _측정 중_ | <2.5s | — |
| CLS | _측정 중_ | <0.1 | — |
| TBT | _측정 중_ | <200ms | — |

### `/offline`

| 카테고리 | 점수 |
|---|---|
| Performance | _측정 중_ |
| Accessibility | _측정 중_ |
| Best Practices | _측정 중_ |
| SEO | _측정 중_ |

---

## 2. Performance Trace — 60fps 유지

### `/login` 초기 렌더

- _측정 중_

### `/offline` 초기 렌더

- _측정 중_

---

## 3. CLS — tabular-nums 효과 검증

`Counter` 컴포넌트가 tweening 중 자릿수가 바뀔 때 layout shift가 발생하는지
실측. `tabular-nums` CSS가 폰트 슬롯 넓이를 고정해주므로 이론적으로 0 shift.

- 결과: _측정 중_

---

## 4. Reduced Motion — `prefers-reduced-motion: reduce`

| 페이지 | Counter | Sparkline | AnimatedBars | Progress | Rise |
|---|---|---|---|---|---|
| `/login` | — | — | — | — | — |
| `/offline` | — | — | — | — | — |

각 primitive가 `useReducedMotion()` 훅 통해 즉시 최종값으로 점프하는지 확인.

---

## 5. axe-core 실사

axe-core@4.x CDN에서 주입 후 `axe.run()`. jsx-a11y/strict(Phase 10a)에서
정적으로 잡지 못한 런타임 a11y 이슈를 보완.

### `/login`

| 심각도 | 이슈 | 수량 |
|---|---|---|
| serious | _측정 중_ | — |
| moderate | _측정 중_ | — |
| minor | _측정 중_ | — |

### `/offline`

| 심각도 | 이슈 | 수량 |
|---|---|---|
| serious | _측정 중_ | — |

---

## 수동 검증 체크리스트 (Phase 11 배포 후)

### 페이지별 "1.2s 예산" 체감 검증

- [ ] `/` 접속 후 페이지 완전 정지까지 **1.2s 이내** 체감 확인
- [ ] `/campaigns/[id]` KPI + FallbackFlow 동시 등장 자연스러움
- [ ] `/reports` 다중 연출(Sparkline × 4 + AnimatedBars × 7 + Progress × 4) 60fps
- [ ] `/notifications` 20개 Rise stagger 1200ms 체감
- [ ] `/groups/[id]` GroupKpis 3 Counter duration=800 확인

### Reduced Motion (OS 설정)

- [ ] **macOS**: 시스템 환경설정 → 손쉬운 사용 → 디스플레이 → "동작 줄이기" ON
- [ ] **Chrome**: DevTools → Rendering → "Emulate CSS prefers-reduced-motion" → reduce
- [ ] 모든 페이지에서 Counter/Sparkline/Progress/Rise가 즉시 최종값으로 점프 확인
- [ ] `PulseDot` CSS keyframes가 globals.css 미디어 쿼리로 자동 정지 확인

### Keyboard Navigation

- [ ] Tab 순서가 시각적 순서와 일치
- [ ] Focus ring 가시성 (모든 primary action)
- [ ] Radix Dialog(Drawer) ESC로 닫힘, Focus trap 동작
- [ ] Command Palette ⌘K 열림, ESC/외부 클릭 닫힘
- [ ] Sidebar 하위 메뉴 Enter/Space 작동

### Screen Reader (VoiceOver on macOS, NVDA on Windows)

- [ ] 페이지 진입 시 제목 첫 읽음 (`aria-label` on `<main>`)
- [ ] Counter/Sparkline이 `role="img"` + `aria-label`로 값 읽힘
- [ ] Progress `aria-valuenow` 읽힘
- [ ] Drawer 열기 시 `aria-describedby` 첫 읽음
- [ ] Toast/Notification `role="status"` 또는 `aria-live="polite"` 전달

### Color Contrast

- [ ] 라이트/다크 모드에서 WCAG AA 이상 (4.5:1 본문 / 3:1 큰 글자)
- [ ] Focus ring 대비 3:1 이상
- [ ] Warning/Danger 상태 색만으로 정보 전달 금지 (아이콘/텍스트 병행 확인)

---

## 결론

_측정 완료 후 작성_

## 참고

- `motion-timing.md` — Phase 10c 타이밍 기준
- `web-bundle-snapshot.md` — Phase 10b 번들 기준
- WCAG 2.1 AA — 접근성 기준
- Core Web Vitals — LCP/CLS/INP 기준
