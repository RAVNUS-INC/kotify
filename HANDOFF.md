# Handoff: NCP → msghub 마이그레이션

> 작성: 2026-04-17
> 브랜치: `feat/msghub-migration` (4커밋 완료)

---

## 목표

NCP SENS SMS API를 U+ msghub API로 완전 교체하여 RCS 우선 발송 + SMS/LMS/MMS fallback 시스템을 구축한다.

- RCS 양방향(8원) → SMS(9원) fallback으로 비용 절감
- 이미지: RCS 이미지 템플릿(40원) → MMS(85원) fallback으로 53% 절감
- 웹훅 기반 리포트로 폴링 제거
- NCP 관련 코드 전량 삭제

---

## 현재 진행 상황

### 완료 (4커밋, `feat/msghub-migration` 브랜치)

| 커밋 | 파일 | 내용 |
|------|------|------|
| `2beceb7` | `app/msghub/auth.py` | TokenManager — JWT 인증, SHA512 이중 해싱, asyncio.Lock stampede 방지, 자동 갱신 |
| `abce054` | `app/msghub/client.py`, `schemas.py`, `codes.py` | MsghubClient (SMS/LMS/MMS/RCS 단방향/양방향), 예외 계층, 요금표, 비용 계산 |
| `8758918` | `app/models.py`, `alembic/versions/0006_msghub_migration.py`, `app/web.py`, 템플릿 | DB 모델 변경 (NcpRequest→MsghubRequest, Message/Campaign/Caller/Attachment), 마이그레이션, 템플릿 NCP 참조 제거 |
| `e37f2aa` | `app/main.py`, `app/routes/campaigns.py`, `app/services/compose.py` | main.py NCP→msghub 전환, import chain 수정, 앱 시작 가능 |

### 미완료

| Phase | 작업 | 상태 |
|-------|------|------|
| **Phase 1** | `services/compose.py` 전면 리라이트 (msghub 발송) | **다음 작업** |
| Phase 1 | `routes/compose.py` NCP 참조 교체 (업로드 등) | 대기 |
| Phase 1 | `routes/admin.py` NCP 설정 → msghub 설정 교체 | 대기 |
| Phase 1 | `routes/setup.py` NCP 스텝 → msghub+RCS 스텝 교체 | 대기 |
| Phase 1 | `app/ncp/` 디렉토리 삭제 + `services/poller.py` 삭제 | 대기 (모든 참조 제거 후) |
| **Phase 2** | `routes/webhook.py` 웹훅 수신 엔드포인트 | 대기 |
| Phase 2 | `services/report.py` 리포트 처리 | 대기 |
| Phase 2 | `services/cost.py` 비용 계산 서비스 | 대기 |
| **Phase 3** | RCS 우선 라우팅 + fbInfoLst | 대기 |
| Phase 3 | `services/image.py` RCS용 이미지 처리 | 대기 |
| **Phase 4** | UI 전면 교체 (설정/셋업/발송/캠페인상세/대시보드) | 대기 |

---

## 성공한 접근법

1. **병렬 생성 후 점진적 교체**: `app/ncp/`를 먼저 삭제하지 않고 `app/msghub/`를 병렬 생성 → import를 하나씩 교체 → 마지막에 NCP 삭제. 한번에 삭제하면 앱 전체가 ImportError로 죽음.

2. **코드리뷰 에이전트 자동 호출**: 구현 완료 후 `oh-my-claudecode:code-reviewer`를 자동으로 돌려서 CRITICAL/HIGH 이슈 수정 후 커밋. 사용자 허락 불필요.

3. **모듈 레벨 import 우선 수정**: 런타임에 호출되는 함수 내 lazy import보다 모듈 레벨 import를 먼저 수정해서 앱 시작을 unblock. 이후 함수 내부 로직은 순차적으로 교체.

4. **venv python 사용**: 시스템 python3에는 httpx가 없음. `.venv/bin/python`으로 테스트. `SMS_DEV_MODE=1` 환경변수 필수 (없으면 `/var/lib/kotify` 권한 에러).

---

## 실패한 접근법

1. **NCP 코드 먼저 삭제 시도**: `app/ncp/` 삭제를 Phase 1 첫 단계로 계획했으나, 12개 파일에서 NCP를 참조하고 있어서 앱이 완전히 깨짐. 병렬 생성 + 점진적 교체로 전략 변경.

2. **`python` 명령어**: macOS에서 `python`은 없고 `python3`만 있음. 그러나 프로젝트 venv의 httpx가 필요하므로 `/Users/stopdragon/Documents/ncp-sms-system/.venv/bin/python` 사용 필수.

3. **한번에 모든 NCP 참조 교체**: compose.py(500줄+)와 campaigns.py를 동시에 리라이트하려 했으나, 너무 큰 변경이라 모듈 레벨 import만 먼저 수정해서 앱 시작 가능 상태를 확보한 후 순차적으로 진행하는 것이 안전.

---

## 다음 단계

### 즉시 실행: `services/compose.py` 전면 리라이트

현재 `services/compose.py`는 모듈 레벨 import만 `MsghubRequest`로 바꿨고, 함수 내부는 여전히 NCP 로직(`NCPClient.send_sms()`, `list_by_request_id()`, 100명 청크 등)이다. **이 파일이 전체 마이그레이션의 핵심.**

변경해야 할 것:
- `dispatch_campaign()` 함수 — 발송 핵심 로직
  - 청크 크기: 100명 → 10명 (`CHUNK_SIZE`)
  - `cliKey` 생성: `c{campaign_id}-{chunk}-{idx}` 패턴
  - NCP `send_sms()` → msghub `send_rcs()` + `fbInfoLst` (RCS 우선)
  - NCP `list_by_request_id()` 제거 (msghub는 발송 응답에 `msgKey` 즉시 반환)
  - `NcpRequest` 생성 → `MsghubRequest` 생성
  - Message 레코드: `message_id` → `cli_key` + `msg_key`, `ncp_request_id` → `msghub_request_id`
  - 예약 발송: `ReserveResponse.web_req_id` → `campaign.web_req_id` 저장
  - 예외: `NCPBadRequest/NCPRateLimited/NCPServerError/NCPAuthError` → msghub 예외
- `_record_failed_chunk()` 함수 — `NcpRequest` → `MsghubRequest`
- `get_ncp_client()` 호출 → `get_msghub_client()` 호출

### 그 다음

1. `routes/compose.py` — 업로드 로직 NCP→msghub, `NCP_MMS_MAX_BYTES` rename
2. `routes/admin.py` — NCP 설정 폼 → msghub+RCS 설정 폼
3. `routes/setup.py` — NCP 스텝 → msghub+RCS 스텝
4. `app/ncp/` + `services/poller.py` + NCP 테스트 삭제
5. Phase 2~4 진행

---

## 관련 파일

### 기획서 (claudedocs/)
- `claudedocs/msghub-api-guide.md` — msghub 순수 API 레퍼런스
- `claudedocs/msghub-migration-spec.md` — 구현 기획서 v2.0 (DB 스키마, API 매핑, 구현 순서)
- `claudedocs/msghub-ux-changes.md` — UI 변경 확정안 (모든 결정사항 반영)

### 새로 생성된 msghub 모듈
- `app/msghub/__init__.py`
- `app/msghub/auth.py` — TokenManager (JWT 인증)
- `app/msghub/client.py` — MsghubClient (SMS/LMS/MMS/RCS 발송)
- `app/msghub/schemas.py` — 예외 + 요청/응답 데이터클래스
- `app/msghub/codes.py` — 에러 코드 + 비용 계산

### 수정된 파일
- `app/models.py` — MsghubRequest, Message, Campaign, Caller, Attachment 변경
- `app/main.py` — NCP→msghub 싱글턴 교체
- `app/web.py` — `describe_ncp` → `describe_result`
- `app/routes/campaigns.py` — NcpRequest→MsghubRequest, 예약 취소 단순화
- `app/services/compose.py` — 모듈 레벨 import만 변경 (**내부 로직 리라이트 필요**)
- `app/templates/campaigns/_recipients.html` — result_status→result_code, NCP 문구 제거
- `alembic/versions/0006_msghub_migration.py` — DB 마이그레이션

### 아직 NCP 코드가 남아있는 파일 (삭제 대상)
- `app/ncp/` (전체 디렉토리)
- `app/services/poller.py`
- `tests/test_signature.py`, `tests/test_poller.py`, `tests/test_poller_transactions.py`

### 아직 NCP lazy import가 남아있는 파일 (교체 필요)
- `app/routes/compose.py:370` — `from app.ncp.client import NCPError`
- `app/routes/admin.py:131,151` — `from app.ncp.client import NCPAuthError, NCPClient, NCPForbidden`
- `app/routes/setup.py:103` — `from app.ncp.client import NCPAuthError, NCPClient, NCPError, NCPForbidden`
- `app/services/compose.py` — 함수 내부 전체 (dispatch_campaign 등)

### 워크플로우 참고
- 구현 → 코드리뷰 에이전트 자동 호출 → 수정 → 커밋 → 다음 기능 (사용자 허락 불필요)
- 테스트: `SMS_DEV_MODE=1 /Users/stopdragon/Documents/ncp-sms-system/.venv/bin/python -c "..."`
