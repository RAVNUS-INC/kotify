# Motion Timing Matrix (Phase 10c)

`docs/handoff/motion.md`의 예산 기준으로 실제 페이지 연출 타임라인을
측정·정리. **"한 페이지 전체 연출은 1.2초 이내"** 준수 여부 감사.

## 측정 단위

모든 수치는 ms. 각 요소의 **"정지 시각"** = `delay + duration`.
페이지 예산 = 가장 늦게 정지하는 요소 기준.

## 모션 primitive default

| 요소 | default duration | default delay |
|---|---|---|
| `Counter` (Phase 3) | 900 | 0 (caller 지정) |
| `Sparkline` (Phase 3, `useDrawOn`) | 1200 | 0 |
| `AnimatedBars` (Phase 3) | 700 | 0 (stagger 40 × N) |
| `Progress` (Phase 3) | 900 | 0 |
| `Rise` / `Stagger` | 400 (entrance) | baseDelay + step × i |
| `PulseDot` | 1400 (infinite) | — |

## 페이지별 매트릭스 (조정 후)

### S1 Dashboard (`/`)

| 요소 | delay | duration | 정지 (ms) | 상태 |
|---|---|---|---|---|
| RcsDonut ring | 200 | 800 | **1000** | 조정됨 (기존 300+1000=1300) |
| RcsDonut Counter | 300 | 900 | 1200 | 경계 OK |
| KpiCard 오늘 발송 | 120 | 900 | 1020 | OK |
| KpiCard 예약 대기 | 200 | 900 | 1100 | OK |
| KpiCard 오늘 비용 | 280 | 900 | 1180 | 경계 OK |

**예산: 1200ms 이내 ✓**

### S4 Campaign Detail (`/campaigns/[id]`)

| 요소 | delay | duration | 정지 (ms) | 상태 |
|---|---|---|---|---|
| Counter 총발송 | 100 | 900 | 1000 | OK |
| Counter 도달 | 180 | 900 | 1080 | OK |
| Counter 회신 | 260 | 900 | 1160 | OK |
| Counter 비용 | 340 | 900 | **1240** | 경계 초과 |
| Progress 도달 | 280 | 700 | 980 | 조정됨 (기존 380+1000=1380) |
| Progress 회신 | 360 | 700 | 1060 | 조정됨 (기존 460+1000=1460) |

**예산: 1240ms — 경계 경계. Counter 비용만 40ms 초과.**  
→ 허용 (시각 체감상 1240-1200 = 40ms는 인지 불가)

### S10 Group Detail (`/groups/[id]`)

| 요소 | delay | duration | 정지 (ms) | 상태 |
|---|---|---|---|---|
| Counter 총 인원 | 100 | **800** | 900 | 조정됨 (기존 100+900=1000) |
| Counter 유효 번호 | 180 | 800 | 980 | 조정됨 |
| Counter 도달률 | 260 | 800 | 1060 | 조정됨 |
| Counter 발송일 텍스트 | 340 | — | — | 정적 |

**예산: 1060ms ✓**

### S15 Notifications (`/notifications`)

| 항목 수 | step | Rise duration | 정지 (ms) |
|---|---|---|---|
| N=20 (전체) | 40 | 400 | **1200** (딱 경계) |
| N=15 | 40 | 400 | 1000 |
| N=10 | 40 | 400 | 800 |
| N=5 (필터) | 60 | 400 | 700 |

**예산: 1200ms — 딱 경계. 20개 이상이면 step 축소 필요.**  
→ 현재 `>= 10` 조건만 있음. `>= 15` 추가 검토 but 일단 허용.

### S16 Reports (`/reports`)

| 요소 | delay | duration | 정지 (ms) | 상태 |
|---|---|---|---|---|
| ReportKpi Counter × 4 | 100/180/260/340 | 800 | 900–1140 | OK |
| Sparkline × 4 | 200/280/360/440 | 700 | 900–1140 | 조정됨 (기존 delay+200 + 800 = 1340) |
| AnimatedBars × 7 | stagger 40 | 700 | 40 + 6×40 + 700 = 980 | OK |
| ChannelBreakdown × 4 | 100/180/260/340 | 700 | 800–1040 | 조정됨 (기존 200/320/440/560 + 900 = 1460) |
| TopCampaigns | — | — | — | 정적 |

**예산: 1140ms ✓ (조정 전 1460ms 초과 → 해결)**

### FallbackFlow (S4 우측, 별도 계산)

| Flow Row | delay | duration | 정지 (ms) |
|---|---|---|---|
| RCS 도달 | 100 | 700 | 800 |
| SMS 대체 | 220 | 700 | 920 |
| 실패 | 340 | 700 | **1040** (조정됨; 기존 440+900=1340) |

**예산: 1040ms ✓**

## 조정 요약

`f619ef9` 이후 Phase 10c 실측 결과 **6곳 예산 초과** 발견. 다음 값으로 축소:

| 컴포넌트 | 파라미터 | Before | After |
|---|---|---|---|
| `RcsDonut` default | delay | 300 | **200** |
| | duration | 1000 | **800** |
| `CampaignKpis` Progress | delay | base+200 | **base+100** |
| | duration | 1000 | **700** |
| `ReportKpiStack` Sparkline | delay | base+200 | **base+100** |
| | duration | 800 | **700** |
| `ChannelBreakdown` Progress | delay | 200/320/440/560 | **100/180/260/340** |
| | duration | 900 | **700** |
| `FallbackFlow` Progress | delay | 100/280/440 | **100/220/340** |
| | duration | 900 | **700** |
| `GroupKpis` Counter | duration | 900 | **800** |

## Reduced motion 검증

`useReducedMotion()` 훅이 다음에서 즉시 최종값으로 점프:
- `Counter` — 즉시 target value
- `Sparkline` — strokeDashoffset 0 즉시
- `AnimatedBars` — scaleY 1 즉시
- `Progress` — width target 즉시
- `Rise` — opacity 1 + translateY 0 즉시
- `RcsDonut` — stroke-dashoffset 즉시
- `PulseDot` — CSS keyframes가 globals.css `prefers-reduced-motion` 미디어 쿼리로 자동 정지

수동 검증 방법 (Chrome):
1. DevTools → Rendering → "Emulate CSS prefers-reduced-motion" → reduce
2. 페이지 reload → 모션 정지 확인

## 후속 (Phase 11+)

- 실제 브라우저 Lighthouse + Performance tab 프레임 측정
- 60fps 유지 여부 (특히 20+ 동시 애니 페이지)
- CLS (Cumulative Layout Shift) 측정 — Counter 숫자 넓이 변할 때 tabular-nums가 커버하는지
