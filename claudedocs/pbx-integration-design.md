# PBX(DIPCAST/VitalPBX) 연동 설계안 — 팩스 발송·통화 기록·녹음 재생

> 상태: **승인됨(2026-10-15)** · 녹음 재생 sender 이상, 팩스 PDF 영구 보관, 실측용 키는 운영 CT 파일로 전달
> 대상 장비: VitalPBX 4.5.1-4 (API v2, `vitalpbx-api 4.5.0-5`), 테넌트 2

> 구현: 2026-10-15 브랜치 `jj/pbx-integration-1f8e12` (`63d830e` 백엔드, `0e576b2` 화면). 확정 동작은 SPEC §8.6 이 기준이고, 이 문서는 설계 근거와 실측 상태를 기록한다.

## 0. 확인된 사실 / 미확인 사항

| 항목 | 상태 | 근거 |
|---|---|---|
| 운영 CT → `https://10.0.5.10:4430/api/v2/cdr` 도달 | ✅ 키 없이 401 (48ms) | 2026-10-15 CT 에서 curl |
| 운영 CT httpx | ✅ 0.28.1 (새 의존성 불필요) | CT `.venv` |
| 팩스 발송 응답 | 문서상 `data.{device, recipients[], file, email, status}` — **로그 ID 없음** | 공식 Postman 예시 |
| 팩스 로그 | `GET /virtual_faxes/log/{id}` → `{unix_date, device_id, type, recipient, file, status, error}` · **목록 API 없음** | 공식 Postman 예시 |
| 발송 응답 `file`(`/var/lib/vitalpbx/fax/tmp/<ts>.<n>.pdf`)과 로그 `file`(`<ts>.<n>.pdf`)이 같은 이름인지 | ❓ 키 발급 후 실측 필요 | 문서 예시는 서로 다른 건 |
| CDR 의 고객 번호 형식(0 포함/+82/숫자만) | ❓ 실측 필요(필드 형태만 본다) | — |
| 단건 CDR 조회 방법(`search_fields=uniqueid`) | ❓ 실측 필요 | — |
| PBX(10.0.5.10) → kotify CT `10.0.5.204:3000` 도달(팩스 PDF 내려받기) | ❓ PBX 쪽에서 확인 필요 | — |
| 팩스 발신 번호 형식(국번 포함·접두 번호 필요 여부) | ❓ 기존 성공 3건 로그로 확인 | — |

미확인 항목은 **kotify 전용 API 키를 받은 뒤 운영 CT 에서 읽기 전용 GET 으로만** 확인한다(값은 출력하지 않고 필드 이름·건수·형식 패턴만 본다). 결과에 따라 아래 §3.3 의 로그 추적 방식을 확정한다.

## 1. 공통: PBX 클라이언트 (`app/pbx/client.py`)

- `httpx.AsyncClient` 하나, `base_url = pbx.api_base_url` (기본 `https://10.0.5.10:4430`), 헤더 `app-key`, `tenant`.
- 타임아웃: 연결 3초 / 읽기 10초(녹음 스트리밍은 읽기 30초).
- TLS: 자체 서명이라 `pbx.tls_verify=false` 기본. 사내망 직결(10.0.5.0/24)만 쓰고 공인 도메인(`call.ravnus.com`·`time.ravnus.com`)은 절대 쓰지 않는다.
- 응답 `status != "success"` · 4xx/5xx · 파싱 실패 → `PbxError(code)`. 메시지에 PBX 응답 본문·URL 쿼리를 넣지 않는다(번호가 섞임).
- **로그 규칙**: 전화번호·`recording_url`·`recfile`·`secret`·`app-key` 를 남기지 않는다. 오류 로그는 `endpoint 이름 + HTTP 상태 + 오류 코드`만.
- 미설정(`pbx.app_key` 없음)이면 기능 비활성 — API 는 `409 pbx_not_configured`, 화면은 안내 문구.

## 2. 설정 키 (SettingsStore, §10.2 에 추가)

| 키 | 저장 | 설명 |
|---|---|---|
| `pbx.api_base_url` | plain | 기본 `https://10.0.5.10:4430` |
| `pbx.tenant` | plain | `f14d776c85f4a734` |
| `pbx.app_key` | **encrypted** | kotify 전용 키(테넌트 2) |
| `pbx.tls_verify` | plain | `"false"` 기본 |
| `pbx.fax_device_id` | plain | `2` (RAVNUS, 발신 0236639887) |
| `pbx.fax_fetch_base_url` | plain | PBX 가 PDF 를 받아 갈 kotify 주소. 예 `http://10.0.5.204:3000` (사내 주소, 공개 도메인 아님) |

- 설정 화면: `/settings/provider` 에 "전화 교환기(PBX)" 섹션 + **연결 테스트**(admin, `GET /virtual_faxes/{id}` → 장치 이름만 표시, secret 은 버림).
- 감사: 기존 `SETTINGS_UPDATE` 그대로(값 미기록).

## 3. ① 팩스 발송

### 3.1 데이터 모델 — 새 테이블 `fax_jobs` (alembic `0024`)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| id | int PK | |
| created_by | text FK users.sub | |
| recipient | text | 숫자만(정규화) |
| original_filename | text | |
| pdf_blob | blob | 최대 10MB, `%PDF-` 시그니처 검사 (첨부 이미지와 같이 DB 저장 → 기존 백업에 포함, **영구 보관**) |
| file_size_bytes | int | |
| resolution | text | standard/medium/high (기본 `high`) |
| retries / retry_time | int | 기본 2회 / 300초 |
| status | text | `QUEUED`→`SUBMITTED`→`SENT` / `FAILED` / `UNKNOWN` |
| pbx_file | text | 발송 응답의 파일 이름(로그 매칭 키) |
| pbx_log_id | int nullable | 매칭된 로그 ID |
| error | text nullable | PBX 오류 문구(번호 없음) |
| fetch_count | int | PBX 가 PDF 를 받아 간 횟수 |
| created_at / submitted_at / completed_at | text | UTC ISO |

### 3.2 흐름

1. `POST /fax` (sender 이상, CSRF, multipart: `recipient`, `file`, `resolution`) — 번호 검증(0 으로 시작 9~11자리 국내 유선·휴대), PDF 검증, 행 생성(`QUEUED`).
2. 같은 요청에서 서명 URL 생성: `{pbx.fax_fetch_base_url}/api/pbx/fax-files/{token}` — token 은 `fax_job_id + 만료(10분)` 를 HMAC(session 비밀과 별도의 `pbx.fax_url_secret`, 자동 생성·암호화) 로 서명.
3. `POST /virtual_faxes/{device}/send` (form: url, recipients=번호 1개, resolution, retries, retry_time) → 성공이면 `SUBMITTED` + `pbx_file` 저장. 요청 거부면 `FAILED`. 시간 초과·5xx 는 **재전송하지 않고** `UNKNOWN`(이중 발송 방지, 기존 문자 발송의 "접수 미확정" 원칙과 동일).
4. `GET /api/pbx/fax-files/{token}` (인증 없음 — PBX 가 호출): 서명·만료 확인 + 상태가 `QUEUED/SUBMITTED` 일 때만 PDF 반환, `fetch_count` 증가(상한 5회). 실패는 모두 404(존재 여부 노출 안 함). 로그에 token 남기지 않음.
5. 결과 추적: 백그라운드 루프(기존 `_reconcile_loop` 와 같은 lifespan 태스크, 30초 간격)가 `SUBMITTED/UNKNOWN` 작업의 로그를 찾는다 → 아래 3.3.
6. 감사 로그: `FAX_SEND`(job id 만, 번호·파일명 미기록).

### 3.3 로그 ID 찾기 (실측 후 확정)

목록 API 가 없으므로 **증가하는 로그 ID 를 앞으로 훑는** 방식을 1안으로 둔다.
- `pbx.fax_log_cursor`(마지막으로 확인한 최대 로그 ID)부터 `GET /virtual_faxes/log/{cursor+1..}` 를 404 가 날 때까지(한 번에 최대 20건) 읽고, `type=Outgoing` + `file == pbx_file` 로 작업에 매칭.
- 매칭되면 `status`(예: `Sent`/`Failed`)로 `SENT`/`FAILED`, `error` 저장.
- 2시간 넘게 매칭이 안 되면 `UNKNOWN` 으로 두고 화면에 "PBX 팩스 뷰어에서 확인" 안내.
- 실측에서 파일 이름이 일치하지 않으면 `unix_date`(발송 시각 ±5분) + `recipient` 로 매칭(2안).

### 3.4 회선·재시도

G.711 팩스라 실패가 잦을 수 있다 → PBX 자체 재시도(`retries`·`retry_time`)를 쓰고 kotify 는 자동 재발송하지 않는다. 실패한 작업은 화면의 "다시 보내기"로 **새 작업**을 만든다(사람이 판단). 동시에 회선 1개를 쓰므로 kotify 는 `SUBMITTED` 작업이 3건 이상이면 새 발송을 409 로 막는다(대기열은 PBX 모뎀 큐에 맡김).

## 4. ② 고객별 통화 기록(CDR)

- 저장하지 않고 **조회 시 PBX 에서 읽는다**(PBX 가 원본, kotify DB 에 통화 기록 복제 없음).
- `GET /pbx/calls?phone=&from=&to=&type=&page=&limit=` (권한: §6)
  - PBX `GET /cdr` 에 `extensions=<번호>`(실측 형식에 맞춰 변환), `start_date`/`end_date`(기본 최근 30일), `calltype`, `limit=offset,length`, `order_by=calldate desc`.
  - 응답은 kotify 형식으로 줄여서 반환: `{id, at(KST), direction(in/out/internal), from, to, durationSec, billSec, disposition, hasRecording, recordingToken?}`.
  - `recording_url`·`recfile`·`channel`·`lastdata` 는 **절대 응답에 넣지 않는다.**
- `phone` 없이 전체 조회는 admin 만(업무 전체 통화 이력이라 범위가 큼).

## 5. ③ 녹음 재생

- 목록 응답의 `recordingToken` = `Fernet(마스터 키)` 로 암호화한 `{path, user_sub, exp(30분)}`. 브라우저는 경로를 알 수 없다(암호문).
- `GET /pbx/recordings/{token}` (권한: §6): 복호화 → `user_sub` 가 현재 사용자와 같은지, 만료, 경로가 `^/vrecordings/<tenant>/\d{4}/\d{2}/\d{2}/[\w.-]+\.wav$` 인지 검사 → 내부 주소 `{api_base_url}{path}` 를 스트리밍 프록시.
  - `Range` 헤더를 그대로 전달해 206 응답을 중계(오디오 탐색 지원), `Content-Type: audio/wav`, `Cache-Control: no-store`, `Content-Disposition: inline`.
  - 감사 로그 `RECORDING_PLAY`(CDR id 만). 같은 녹음의 Range 요청 반복은 첫 요청만 기록.
- PBX 프록시 차단(`/vrecordings`·`/api` 내부 IP 만) 이후에도 kotify 는 10.0.5.204 → 10.0.5.10 직결이라 영향 없음.

## 6. 권한 (확정)

| 기능 | 제안 |
|---|---|
| 팩스 발송·내 팩스 이력 | sender 이상 |
| 전체 팩스 이력 | admin |
| 번호별 통화 기록 | sender 이상 |
| 전체 통화 기록(번호 없이) | admin |
| 녹음 재생 | sender 이상 (모든 재생을 감사 로그에 기록) |
| PBX 설정·연결 테스트 | admin |

## 7. 화면 (Next.js)

- **`/fax`** (사이드바 "팩스", sender 이상): 위 발송 폼(받는 번호·PDF·해상도) + 아래 이력 표(상태 배지, 실패 사유, 다시 보내기). `SUBMITTED` 가 있으면 15초 간격으로 새로고침(`router.refresh`).
- **`/calls`** (사이드바 "통화 기록"): 번호·기간·유형 필터(URL state), 표 + 녹음 있는 행에 재생 버튼(`<audio controls preload="none" src="/api/pbx/recordings/{token}">`, sender 이상).
- **대화방 오른쪽 카드**(`ThreadRecipientCard`): "최근 통화" 5건 + `/calls?phone=…` 링크. PBX 미설정·오류면 섹션 숨김(하이웍스와 같이 실패 격리 — 대화방은 계속 동작).
- `web/lib/access.ts` 에 `/fax`·`/calls` 규칙 추가(백엔드와 동일 조건).

## 8. 테스트 계획

- 백엔드(pytest + respx, 실제 PBX 호출 없음)
  - 클라이언트: 헤더·타임아웃·`status!=success`·5xx·시간 초과 → 오류 코드, 로그에 번호·URL 미포함(caplog).
  - 팩스: PDF 검증·번호 검증·권한·CSRF, 발송 성공/거부/시간 초과(UNKNOWN, 재전송 없음), 서명 URL(만료·위조·상태·횟수 상한·404 통일), 로그 매칭(커서 전진·404 중단·파일명 매칭·2시간 UNKNOWN), 동시 발송 상한.
  - CDR: 파라미터 변환, 응답 축약(`recording_url`·`recfile` 미노출), 권한(전체 조회 admin).
  - 녹음: 토큰 위조·만료·다른 사용자·경로 검사(`..`, 다른 테넌트), Range 중계 206, 감사 기록.
  - 마이그레이션 0024 업·다운.
- 웹(Vitest): 팩스 폼 검증·상태 배지, 통화 표·재생 버튼 권한 표시, `access.ts` 규칙, 대화방 카드 실패 격리.
- 운영(읽기 전용): 키 등록 후 연결 테스트, CDR 1회 조회(건수만), 녹음 스트리밍 1건(바이트 수·Content-Type 만).
- 사용자 승인 후: 실제 팩스 1건(사내 팩스 번호로) → 로그 매칭·상태 반영 확인.

## 9. 범위 밖

- 팩스 수신(불안정), click-to-call(요청 시 후속), PBX 설정 변경, 통화 기록 DB 복제·통계, 녹음 다운로드.
