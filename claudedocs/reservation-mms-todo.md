# 예약 발송 + MMS 구현 — 다음 세션 TODO

> **⚠️ HISTORICAL — 이 문서의 모든 작업은 완료되었고, 이후 NCP 전체가 msghub로 교체되었다.**
> 본 문서는 NCP 시절 기획 히스토리로 보존됨. 현재 시스템 정보는 [HANDOFF.md](../HANDOFF.md) 참조.
>
> - 예약 발송: msghub 연동으로 구현 완료
> - MMS + 이미지 전처리: `app/services/image.py`에 RCS/MMS 공용으로 구현 완료
> - 본문에 나오는 `app/ncp/*`, `NCPClient`, `NcpRequest`는 현재 존재하지 않음 (msghub로 치환됨)
>
> 이 문서는 세션을 새로 시작할 때 컨텍스트 복원용으로 작성됐다.
> `git log --oneline`과 함께 읽으면 이전 작업 전체가 복원된다.

## 완료된 것 (git log 기준)

| SHA | 제목 | 설명 |
|---|---|---|
| `9958c95` | feat(db): 캠페인 테이블에 예약 발송 필드 추가 (스키마만) | Phase B1 — 스키마만 |
| `aa028a8` | ux: 캠페인 상세에 LMS 제목 표시 | Phase A |
| `48b9fc4` | fix(poller): 발송 후 70분 cutoff + backoff/hot-loop/쿨다운 정리 | C1~I4 전체 해결 |
| `ac7cbe1` | fix(ncp): 수신결과 코드를 NCP statusMessage 원문으로 노출 | codes.py 리팩터 |

## Phase B2 — NCP 클라이언트/서비스/라우트 확장 (예약 발송 기능부)

### 목표
예약 발송 동작을 백엔드 레벨까지 완성. UI는 Phase B3에서.

### 작업 항목

**`app/ncp/client.py`**:
- `send_sms()` 시그니처에 `reserve_time: str | None`, `reserve_time_zone: str | None` 추가
- `reserve_time`가 있으면 body에 `reserveTime`, `reserveTimeZone` 필드 추가
- 새 메서드 `get_reserve_status(reserve_id: str) -> ReserveStatusResponse`
  - `GET /sms/v2/services/{serviceId}/reservations/{reserveId}/reserve-status`
  - 응답 필드: `reserveId`, `reserveTimeZone`, `reserveTime`, `reserveStatus`
  - `reserveStatus` 7개 값: `READY | PROCESSING | CANCELED | FAIL | DONE | STALE | SKIP`
- 새 메서드 `cancel_reservation(reserve_id: str) -> None`
  - `DELETE /sms/v2/services/{serviceId}/reservations/{reserveId}`
  - 성공: 204 No Content
  - NCP 공식 문서: https://api.ncloud-docs.com/docs/en/sens-sms-reservation-delete

**새 dataclass**:
```python
@dataclass
class ReserveStatusResponse:
    reserve_id: str
    reserve_timezone: str
    reserve_time: str          # "YYYY-MM-DDTHH:mm:ss+09:00" 형식
    reserve_status: str        # READY|PROCESSING|CANCELED|FAIL|DONE|STALE|SKIP
```

**`app/services/compose.py`**:
- `dispatch_campaign()`에 예약 파라미터 추가
- 예약 캠페인의 경우:
  - `Campaign.state = "RESERVED"` 설정
  - `NcpRequest.sent_at` = **예약 실행 시각의 UTC 변환값**
    (그래야 70분 cutoff가 정상 동작 — "DONE 이후 70분"이 아닌 "예약 실행 이후 70분")
  - `Campaign.reserve_time`, `reserve_timezone` 저장
- `send_sms()` 호출 시 reserve 파라미터 전달

**`app/routes/campaigns.py`**:
- 새 엔드포인트: `POST /campaigns/{id}/cancel-reservation`
  - 권한: sender/admin
  - `state != "RESERVED"`이면 400
  - `ncp_client.cancel_reservation(ncp_req.request_id)` 호출
  - 성공 시 `state = "RESERVE_CANCELED"`로 업데이트
  - 실패(NCP 응답 에러) 시 사용자에게 표시 (NCP는 READY 상태에서만 취소 가능)

### 설계 결정 (이미 확정됨)

1. **`sent_at` 의미**: 예약 캠페인에서는 "예약 실행 시각(UTC)"로 저장 → 70분 cutoff가 일관됨
2. **`reserveStatus` → `campaign.state` 매핑**:
   ```
   READY      → RESERVED
   PROCESSING → DISPATCHING
   DONE       → 기존 메시지 폴링 로직으로 자동 전환
   CANCELED   → RESERVE_CANCELED
   FAIL       → RESERVE_FAILED
   STALE      → RESERVE_FAILED (시간 초과)
   SKIP       → RESERVE_FAILED (서비스 없음)
   ```

### 테스트

- `tests/test_ncp_client.py` — 기존 있으면 확장, 없으면 신설
  - send_sms with reserve params → body에 reserveTime/reserveTimeZone 포함 검증
  - get_reserve_status 파싱 검증
  - cancel_reservation 204 처리 검증
- `tests/test_compose_service.py` — 예약 캠페인 생성 시 state=RESERVED, sent_at=예약시각
- `tests/test_campaigns_route.py` — cancel-reservation 엔드포인트 권한/상태 검증

---

## Phase B3 — UI + 폴러 워커 통합

### 목표
사용자가 실제로 예약 발송을 만들고 취소할 수 있게 된다.

### 작업 항목

**`app/templates/compose.html`**:
- "예약 발송" 체크박스 + `input[type=datetime-local]`
- 체크 시 버튼 문구: "발송" → "예약 등록"
- 최소 예약 시간 검증 (현재 시각 + 10분 이상)
- 타임존은 서버 기본 `Asia/Seoul` 고정 (사용자 입력 없음)

**`app/templates/campaigns/detail.html`**:
- 예약 시각 표시 (기본 정보 카드)
- `state == "RESERVED"`일 때 "예약 취소" 버튼 노출
- `state == "RESERVE_CANCELED"`, `"RESERVE_FAILED"`에 뱃지 추가
- HTMX 폴링 조건에 `RESERVED` 추가

**`app/templates/campaigns/list.html`**:
- 상태 뱃지에 `RESERVED`, `RESERVE_CANCELED`, `RESERVE_FAILED` 케이스 추가
- 가능하면 예약 시각을 목록에 표시 (좁은 컬럼)

**`app/services/poller.py`**:
- `_poll_cycle`에 예약 캠페인 처리 분기 추가
  - `state == "RESERVED"`인 캠페인의 `ncp_request`를 조회
  - `get_reserve_status(request_id)` 호출
  - `reserveStatus`에 따라 `campaign.state` 업데이트:
    - `DONE` → `state = "DISPATCHING"`, 이후 기존 메시지 폴링 로직으로 넘어감
    - `CANCELED` → `state = "RESERVE_CANCELED"` (사용자가 우리 UI가 아닌 NCP 콘솔에서 취소한 케이스 대응)
    - `FAIL/STALE/SKIP` → `state = "RESERVE_FAILED"`
- 예약 캠페인 상태 조회의 backoff: 예약 실행 시각 T-5분까지 10분 간격, T-5분부터 1분 간격
- 70분 cutoff는 `sent_at` 기준이므로 자동 적용됨 (설계 결정 1 덕분)

### 테스트

- `tests/test_poller.py`에 예약 관련 테스트 추가
  - READY → DONE 전환 시 state가 DISPATCHING으로 전환
  - FAIL/STALE/SKIP → RESERVE_FAILED
  - 예약 시각 T-10분에 호출 빈도 증가

---

## Phase C — MMS + 파일 업로드

### 목표
SMS, LMS에 이어 MMS 발송을 지원한다. JPG/JPEG 이미지 1장 첨부.

### 사전 작업: 의존성

- **Pillow 추가**: `pyproject.toml`의 `dependencies`에 `"pillow>=10.0.0"` 추가
- 이미지 검증/변환에 사용
- `uv pip install pillow` 또는 `uv sync`

### DB 스키마 (alembic/0006)

```python
# 신규 테이블
attachments (
    id INTEGER PK,
    campaign_id INTEGER FK,
    ncp_file_id TEXT NULL,              -- NCP가 돌려준 fileId (업로드 성공 후)
    original_filename TEXT NOT NULL,    -- 사용자가 올린 원본 파일명
    stored_filename TEXT NOT NULL,       -- 우리가 저장한 파일명 (UUID.jpg)
    content_blob BLOB NOT NULL,          -- SQLite BLOB (설계 결정: DB 저장)
    file_size_bytes INTEGER NOT NULL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL,
    ncp_expires_at TEXT NULL             -- NCP가 돌려준 expireTime
)
```

### 모델 (`app/models.py`)

```python
class Attachment(Base):
    __tablename__ = "attachments"
    # 위 스키마 대응
    campaign: Mapped[Campaign] = relationship(...)
```

### 이미지 전처리 서비스 (`app/services/image.py` 신설)

**목표**: 사용자가 어떤 JPG/JPEG/PNG를 올려도 NCP 제약에 맞게 자동 변환한다.

```python
def preprocess_mms_image(raw: bytes) -> tuple[bytes, int, int]:
    """MMS용 이미지를 NCP 제약에 맞게 변환.

    NCP 제약:
    - JPG/JPEG만 (PNG/GIF는 변환)
    - 최대 300KB
    - 최대 1500x1440 해상도
    - Base64 인코딩 결과로 전송

    전략:
    1. Pillow로 이미지 오픈 (입력 포맷 무관)
    2. RGB 변환 (JPEG는 알파 채널 없음)
    3. 1500x1440 초과 시 aspect ratio 유지하며 리사이즈
    4. JPEG 저장, 품질 95부터 시작
    5. 300KB 초과면 품질 -5씩 낮춤 (최소 50까지)
    6. 50에서도 300KB 초과면 ValueError (너무 복잡한 이미지)

    Returns:
        (변환된 JPEG bytes, width, height)
    """
```

### NCP 클라이언트 (`app/ncp/client.py`)

- `upload_attachment(file_name: str, content: bytes) -> UploadResponse`
  - `POST /sms/v2/services/{serviceId}/files`
  - body: `{"fileName": ..., "fileBody": base64(content)}`
  - 응답: `fileId`, `createTime`, `expireTime`
- `send_sms()` 시그니처 확장:
  - `message_type: Literal["SMS", "LMS", "MMS"]`
  - `file_ids: list[str] | None` 추가 → body에 `files: [{fileId}]` 추가

### 업로드 라우트 (`app/routes/compose.py`)

- `POST /compose/upload-attachment` (multipart/form-data)
- 권한: sender/admin
- 파일 수신 → `preprocess_mms_image()` → NCP 업로드 → `attachments` 테이블에 저장
- 응답: `{attachment_id, width, height, file_size_bytes}`

### 발송 서비스 (`app/services/compose.py`)

- `dispatch_campaign()`에 `attachment_id: int | None` 파라미터 추가
- MMS 발송 시:
  - `Campaign.message_type = "MMS"`
  - `NCPClient.send_sms(..., file_ids=[attachment.ncp_file_id])` 호출

### UI

**`app/templates/compose.html`**:
- 파일 첨부 `input[type=file]` (accept="image/jpeg,image/jpg,image/png")
- 첨부하면 AJAX로 업로드, 썸네일 미리보기 표시
- MMS 자동 감지: 첨부 있으면 MMS로 고정
- subject 입력란 활성화 (MMS도 subject 지원)

**`app/templates/campaigns/detail.html`**:
- MMS 캠페인이면 첨부파일 썸네일 표시
- `message_type` 뱃지에 `MMS` 분기 추가

**`app/templates/campaigns/list.html`** + **`dashboard.html`**:
- `message_type` 뱃지에 MMS 분기 추가

### 이력 라우트 (`app/routes/campaigns.py`)

- `GET /campaigns/{id}/attachment/{attachment_id}` — BLOB 스트리밍
- `Content-Type: image/jpeg`, `Cache-Control: private, max-age=3600`

### 테스트

- `tests/test_image_service.py` — Pillow 기반 전처리 단위 테스트
  - PNG 입력 → JPEG 변환
  - 큰 해상도 → 리사이즈
  - 큰 파일 → 품질 압축
  - 너무 복잡한 이미지 → ValueError
- `tests/test_ncp_client.py` — upload_attachment 모킹 + send with files
- `tests/test_compose_with_mms.py` — 전체 MMS 플로우 (업로드 → 발송)

### 보관/정리 전략

- NCP는 6일만 보관 → `Campaign.state == "COMPLETED"` 도달 후 24시간 뒤 BLOB 삭제 권장
- 당장은 구현 안 함 (스코프 크림), 주석으로 TODO 남김

### 설계 결정 (이미 확정됨)

1. **파일 저장**: SQLite BLOB (동일 DB, 백업 단순)
2. **이미지 전처리**: 자동 변환 (포맷 통일 + 해상도 리사이즈 + 품질 압축)
3. **할당량 추적**: 스킵

---

## 작업 순서 권장

1. **세션 A** (예약 발송 백엔드): Phase B2 한 번에 → 커밋 1개
2. **세션 B** (예약 발송 UI/폴러): Phase B3 한 번에 → 커밋 1~2개
3. **세션 C** (MMS 백엔드): Phase C의 DB/모델/image 서비스/NCP 클라이언트 → 커밋 1개
4. **세션 D** (MMS UI): Phase C의 라우트/UI → 커밋 1~2개

각 세션 시작 시 이 문서 + `git log --oneline -10`만 읽으면 컨텍스트 복원 완료.
