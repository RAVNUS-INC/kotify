# Web Bundle Snapshot (Phase 10b)

생성: `pnpm analyze` · @next/bundle-analyzer 16.2.4 · Next.js 14.2.35

## 실행 방법

```bash
cd web
pnpm analyze
# .next/analyze/{client,edge,nodejs}.html 생성
open .next/analyze/client.html
```

리포트 3종 (모두 `.next/analyze/`, Git 제외):

| 파일 | 크기 | 대상 |
|---|---|---|
| `client.html` | 412 KB | 브라우저 다운로드 번들 (가장 중요) |
| `nodejs.html` | 452 KB | Server Component 실행 번들 |
| `edge.html` | 272 KB | Middleware 번들 |

## First Load JS (모든 (app) 라우트 공통)

**87.3 kB gzipped** — 18 화면 전부에 공유.

| 청크 (gzip) | 크기 | 정체 |
|---|---|---|
| `2200cc46-*.js` | **53.7 kB** | React DOM + Next.js core runtime |
| `945-*.js` | **31.7 kB** | 공통 client components (Drawer·Palette·Button 등) |
| other shared | 1.95 kB | webpack runtime, main-app |

Minified (pre-gzip):
- `2200cc46`: 172 KB
- `framework`: 140 KB
- `main`: 132 KB
- `945`: 124 KB
- `polyfills`: 113 KB

Gzip 비율 약 3.2:1 (text-heavy JS 표준).

## 페이지별 순증 bundle

| 경로 | Page Size | First Load | 증가 사유 |
|---|---|---|---|
| `/` (home) | 976 B | 127 kB | Dashboard (Counter·Sparkline·RcsDonut client) |
| `/audit` | 256 B | 126 kB | Server only |
| `/campaigns` | 301 B | 126 kB | Table + LinkSegmented (server) |
| `/campaigns/[id]` | 301 B | 126 kB | KPI + FallbackFlow |
| `/chat` | 263 B | 126 kB | 3컬럼 server |
| `/chat/[id]` | 263 B | 126 kB | ThreadView + ThreadComposer |
| `/contacts` | 1.51 kB | 127 kB | **ContactDrawer (client)** |
| `/groups` | 290 B | 126 kB | GroupCard grid (server) |
| `/groups/[id]` | 289 B | 126 kB | KPI + MembersTable |
| `/kitchen` | **3.36 kB** | 129 kB | 모든 프리미티브 데모 (FormsSample + MotionSample) |
| `/login` | 235 B | 113 kB | auth 레이아웃만 |
| `/notifications` | 1.68 kB | 127 kB | NotificationFeed + MarkAllReadButton (client) |
| `/numbers` | 289 B | 126 kB | LinkSegmented + table |
| `/offline` | 2.67 kB | 115 kB | **Static prerender**, auth 레이아웃 바깥 |
| `/reports` | 290 B | 126 kB | KpiStack·DailyBars·ChannelBreakdown 전부 SC |
| `/search` | 302 B | 126 kB | 결과 페이지 SC (CommandPalette는 Topbar에 상주) |
| `/send/new` | 254 B | 126 kB | ComposeForm (client) |
| `/settings/[[...tab]]` | 1.93 kB | 128 kB | OrgSettingsForm (client) |

## Shared chunk 내역 (945-*.js = 31.7 kB gzip)

모든 (app) 페이지가 공유하므로 가장 비싼 단일 비용:
- **Radix Dialog** (Drawer + Command Palette 기반)
- **CommandPalette** (Topbar에 마운트되어 모든 페이지 포함)
- **Sidebar** (`usePathname` 기반 client)
- **Topbar** (`usePathname` + `<CommandPalette>`)
- Icon·Button·Kbd 등 client boundary에서 쓰이는 UI

## 관찰

### 긍정

1. **First Load 87.3 kB**는 Next.js + React 18 + Radix Dialog 조합으로는 **업계 평균 이하**. Dashboard처럼 무거운 페이지도 127 kB 선에서 수렴.
2. **Server Component가 페이지 bundle을 거의 0**으로 만듦 — 대부분의 `(app)` 라우트가 256-302 B. Sidebar/Topbar/Card 등 prim이 전부 shared에 들어가고, 페이지 고유 코드는 거의 없음.
3. **`/offline` `○ Static` 2.67 kB** — 인증 레이아웃 바깥 + FastAPI 의존 없는 정적 페이지. Phase 11 SW 연결 시 폴백 자원으로 최적.
4. **`/contacts`, `/notifications`, `/settings` 1.5-2 kB 증가**는 각각 client component(Drawer·Feed·Form) 크기와 정확히 일치. 추적 가능.

### 주의 관찰

1. **`/kitchen` 3.36 kB**는 FormsSample/MotionSample/DeviceMockup/MessageBubble 모두 client로 올려 Phase 2/3/6 프리미티브 전체가 포함. 개발용이라 production bundle 영향 없음(라우트 접근 시에만). Phase 11 배포 전 제거 검토.
2. **Radix Dialog 11 kB**가 shared chunk 상당 부분 차지. Drawer·Command Palette 공유. Phase 후속에 Toast/Select/Popover 도입해도 **추가 비용 없음** (이미 dependency graph에 올라와 있음) — 재사용 가치 확인.
3. **Command Palette는 모든 (app) 페이지에 포함됨** — Topbar에 상주하므로. `<CommandPalette>`를 lazy load로 전환하면 "검색 처음 누를 때까지" 유예 가능. 현재는 ⌘K 단축키 즉응이 중요해 유지.

## CI 통합 (Phase 후속)

CI에서 bundle regression 감시:
```yaml
# .github/workflows/web.yml (추후)
- run: pnpm analyze
- name: Bundle size check
  run: |
    MAIN=$(du -b .next/static/chunks/2200cc46-*.js | cut -f1)
    [ "$MAIN" -lt 200000 ] || exit 1
```

또는 `next-bundle-analyzer` + `bundlesize` GitHub Action 조합.

## 히스토리 (참고)

| Phase | First Load JS | 비고 |
|---|---|---|
| 0 | 87.4 kB | Next.js 14 스모크 |
| 2 중반 | 93 kB | +5.67 kB (폼 client) |
| 3 | 97.7 kB | +4.69 kB (모션) |
| 5a | 108 kB | +10 kB (Dashboard client RcsDonut) |
| 7c | 108 kB → 116 kB | **+8 kB (Radix Dialog)** |
| 9c | 116 kB → 125 kB | +9 kB (CommandPalette shared) |
| 10b 현재 | **127 kB** (home) / **87.3 kB** shared | 안정화 |

Radix Dialog 1회 비용(+11 kB) 이후 Phase 8·9 페이지 추가에도 shared 증가 미미.
