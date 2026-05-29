# Phase 0 — 베이스라인 & 자동 검증 결과

> 실행일: 2026-05-30
> 도구: ruff 0.8+ / pytest 8.3 / tsc 5.6 / next lint (eslint 8.57)

---

## 1. 자동 검증 요약

| 검증 | 명령 | 결과 | 판정 |
|------|------|------|------|
| 백엔드 테스트 | `pytest -q` | **195 passed in 0.87s** | ✅ 전부 통과 |
| 타입 안전성 | `tsc --noEmit` | **0 errors** | ✅ 완전 통과 |
| 프론트 린트 | `next lint` | **No warnings or errors** | ✅ 깨끗 |
| 백엔드 린트 | `ruff check` | **94건 (86 자동수정 가능)** | ⚠️ 전부 스타일/현대화 |

**종합**: 코드 위생(hygiene) 상태는 양호. 자동 도구로 잡히는 결함은 거의 없으며, ruff 94건도 **로직 버그가 아닌 스타일·타입 현대화** 항목이다. → 사람의 리뷰는 도구가 못 잡는 **설계·로직·UX·보안**에 집중하면 된다.

---

## 2. ruff 위반 분류 (총 94건)

| 규칙 | 건수 | 자동수정 | 의미 | 조치 |
|------|------|---------|------|------|
| `UP045` | 68 | ✅ | `Optional[X]` → `X | None` (PEP 604) | `ruff --fix` 일괄 |
| `I001` | 8 | ✅ | import 정렬 | `ruff --fix` 일괄 |
| `B904` | 7 | ❌ 수동 | `except`에서 `raise ... from` 누락 | 🟡 수동 (아래 참고) |
| `F401` | 7 | ✅ | 미사용 import | `ruff --fix` 일괄 |
| `UP041` | 2 | ✅ | `TimeoutError` alias 현대화 | `ruff --fix` 일괄 |
| `UP006` | 1 | ✅ | `List` → `list` | `ruff --fix` 일괄 |
| `UP035` | 1 | ❌ 수동 | deprecated import | 🟢 수동 |

### 🟡 B904 (수동 검토 필요) — 7곳
`except` 블록에서 새 예외를 raise할 때 `from err`/`from None`을 안 붙임. 원인 예외 체인이 끊겨 **디버깅 시 근본 원인 추적이 어려워짐**. 위치:
- `app/msghub/auth.py:77` — 응답 파싱 실패
- `app/msghub/client.py:91` — 응답 파싱 실패
- `app/routes/settings.py:170` — timezone 검증
- (그 외 4곳, `_ruff.txt` 참고)

> 권고: 자동수정 86건은 `ruff check app/ tests/ --fix`로 일괄 처리 후 테스트 재실행. B904 7건은 Phase 1/2 리뷰 시 예외 처리 맥락과 함께 검토.

전체 목록: `claudedocs/review/_ruff.txt`

---

## 3. 테스트 커버리지 공백 지도 ⚠️ 핵심 발견

현재 테스트: **16개 파일 / 195개 케이스**. import 집계 기준으로 모듈별 커버리지를 매핑.

### 🔴 테스트 안전망이 없는 고위험 모듈 (Phase 2 대상과 정확히 겹침)

| 모듈 | LOC | 단위 테스트 | 리스크 |
|------|-----|------------|--------|
| `msghub/client.py` | 471 | ❌ 없음 | 🔴 API 연동 핵심 — 발송 성패 좌우 |
| `msghub/auth.py` | 240 | ❌ 없음 | 🔴 JWT 발급/SHA512 — 인증 실패 시 전체 발송 불가 |
| `routes/webhook.py` | 282 | ❌ 없음 | 🔴 배달 리포트 수신 — 위변조/중복 처리 |
| `services/chat.py` | 370 | ❌ 없음 | 🔴 대화/메시지 로직 |
| `services/compose.py` | 629 | △ 1건만 | 🔴 발송 조립 핵심인데 커버리지 빈약 |
| `routes/campaigns.py` | 663 | △ recipient_limit만 | 🟠 캠페인 생성/실행 |

### 🟠 테스트 없는 중위험 모듈

| 모듈 | LOC | 비고 |
|------|-----|------|
| `security/crypto.py` | 109 | 🔴 Fernet 암호화 — 비밀값 보호 핵심인데 테스트 없음 |
| `auth/oidc.py` | 143 | OIDC 흐름 |
| `auth/session.py` | 60 | 세션 관리 |
| `routes/threads.py` | 416 | 스레드 API |
| `routes/numbers.py` | 389 | 발신번호 |
| `routes/reports.py` | 498 | 리포트 집계 |
| `routes/search.py` | 320 | 검색 |
| `routes/notifications.py` | 380 | 알림 |
| `services/report.py` | 252 | 집계 로직 |
| `services/image.py` | 140 | MMS 이미지 전처리 |
| `util/time.py` | 97 | KST 처리 (dashboard_kst가 간접 커버) |

### ✅ 테스트가 있는 모듈
`models`, `services.contacts`, `services.groups`, `services.csv_import`, `security.csrf`, `security.settings_store`, `util.phone`, `util.text`, `msghub.schemas`, `auth.deps`(일부), setup ACL(HTTP), dashboard KST(HTTP), CSRF 통합(HTTP)

### 프론트엔드
**테스트 0개** — 단위/통합/E2E 전무. Phase 4·6에서 최소 발송 플로우 E2E 권고 예정.

---

## 4. Phase별 시사점

- **Phase 2 (발송)**: 리뷰 중 발견하는 버그는 **재현 테스트로 고정**해야 한다. 현재 이 영역은 회귀 안전망이 거의 없어, 수정 시 새 버그 유입 위험이 큼.
- **Phase 1 (보안)**: `crypto.py`(Fernet), `oidc.py`에 테스트가 없으므로, 리뷰는 코드 정독 + 위협 모델링 중심으로.
- **Phase 6 (종합)**: 위 공백 지도를 회귀 테스트 백로그의 출발점으로 사용.

---

## 5. 결론

자동 검증 게이트 **통과**. 코드 위생은 우수하나, **테스트 커버리지가 리스크 역방향**(안전한 곳은 잘 덮고, 위험한 발송/보안 코어는 비어 있음)이라는 구조적 문제가 발견됨. 이는 이후 Phase의 리뷰 깊이와 테스트 권고에 직접 반영한다.
