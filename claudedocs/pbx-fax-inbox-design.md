# 받은 팩스 보기 — 설계안

> 상태: **구현(로컬, 2026-10-16)·결정 완료** — 열람 sender 이상, 실패 수신도 표시, PDF 영구 보관, PBX 에 남은 기존 수신도 모두 가져오기(커서 이전 로그를 한 번 훑는 backfill)
> 선행: [`pbx-integration-design.md`](./pbx-integration-design.md)(팩스 발송·로그 추적), SPEC §8.6

## 0. 전제 (PBX 세션 실측 + kotify CT 확인)

| 항목 | 사실 |
|---|---|
| 수신 경로 | 02-3663-9887 → PBX 가 2초 CNG 감지 → 팩스면 가상 팩스 id 2 "RAVNUS", 아니면 복합기 내선 998. 2026-10-16 01:06 첫 수신 성공(로그 93) |
| PDF 위치 | PBX `/var/lib/vitalpbx/fax/recvd/fax-in-<epoch>.<seq>.pdf` |
| PDF 내려받는 API·웹 경로 | **없음** (`/static/<tenant>/fax/` 404, 팩스 뷰어는 PBX 웹 UI 안에서만) |
| 로그 | `GET /virtual_faxes/log/{id}` — 발신·수신 공용 증가 ID, 없는 ID 는 200 자리표시(`device_id` null). 수신 성공은 `type "Incoming"`, `status "Received"`, `file "fax-in-….pdf"`, `sender "\"<번호>\" <<번호>>"` |
| kotify CT → PBX SSH | `10.0.5.10:55530` 도달, ed25519 호스트 키 제공(고정 가능). CT 에 OpenSSH 10.0 `sftp` 있음 |
| kotify 서비스 제약 | `ProtectHome=true`·`ProtectSystem=strict`, 쓰기 가능은 `/var/lib/kotify` 등 → 키·known_hosts 는 `/var/lib/kotify` 아래 |

## 1. 방식

### 1.1 새 수신 감지 — **기존 로그 커서 재사용**
- 지금 팩스 발송 추적이 쓰는 `pbx.fax_log_cursor` 스캐너를 **항상** 돌린다(현재는 보내는 중인 팩스가 있을 때만). 60초마다 커서 다음 ID 부터 읽고, 빈 ID 3개 연속이면 멈춘다 — 평소에는 1분에 1~3회 GET.
- 읽은 실제 로그마다: `Outgoing` → 기존처럼 발송 작업과 매칭, `Incoming` → 받은 팩스 행 생성(로그 ID 유일 키라 중복 없음).
- SFTP 폴더 목록 비교는 쓰지 않는다: 로그에 보낸 번호·상태·오류가 있고 파일 이름도 있어, 폴더 목록은 정보가 적고 실패 수신을 못 본다.

### 1.2 PDF 가져오기 — **SFTP 읽기 전용, 파일 이름 지정 get** (PBX 세션 추천안 채택)
- 로그의 `file` 이 `^fax-in-\d+\.\d+\.pdf$` 일 때만 `sftp` 로 그 파일 하나를 받는다(목록 조회·경로 조작 없음). 받은 내용은 `%PDF-` 시그니처·최대 20MB 확인 후 DB 에 BLOB 저장(보낸 팩스와 같은 방식, 기존 DB 백업에 포함).
- 실행: 시스템 `sftp`(새 Python 의존성 없음) `-F /dev/null -i /var/lib/kotify/pbx_sftp_ed25519 -o BatchMode=yes -o StrictHostKeyChecking=yes -o UserKnownHostsFile=/var/lib/kotify/pbx_known_hosts -P 55530`. 타임아웃 30초.
- 키: kotify CT 에서 ed25519 키 쌍을 만들고(개인 키 600, kotify 소유, 저장소·로그에 안 남김) **공개 키만** PBX 세션에 전달. 호스트 키는 지금 스캔한 값을 known_hosts 에 고정.
- 실패(접속·파일 없음)는 3회까지 다음 주기에 재시도, 이후 "PDF 못 가져옴"으로 표시하고 화면에서 "다시 가져오기" 가능.

다른 안과 비교:

| 안 | 장점 | 단점 |
|---|---|---|
| **SFTP pull (채택)** | PBX 는 계정 1개만, 읽기 전용·폴더 한정, kotify 가 주기·재시도 통제, 키 인증 | PBX 계정 관리, 키 파일 관리 |
| PBX 가 kotify 로 push(수신 후 스크립트) | 즉시 반영 | PBX(암호화된 VitalPBX)에 사용자 스크립트·후크 필요, 업그레이드에 깨지기 쉬움, kotify 에 인바운드 인증 경로 추가 |
| PBX 웹으로 recvd 공개 | 구현 쉬움 | 녹음처럼 인증 없는 노출 위험 재발 — 하지 않음 |

### 1.3 PBX 쪽 요청 사항 (PBX 세션이 처리, 사용자 승인 후)
1. 계정 `kotify-fax`(예시 이름) — 키 인증만, 셸 없음(`internal-sftp`), `/var/lib/vitalpbx/fax/recvd` 읽기 전용(chroot 또는 ACL), 비밀번호 로그인 금지.
2. 공개 키 등록 — kotify CT `/var/lib/kotify/pbx_sftp_ed25519.pub`(2026-10-16 생성, 주석 `kotify-fax@kotify`). 고정한 PBX 호스트 키: `[10.0.5.10]:55530` ED25519 `SHA256:pmLDDSMLd4MEeiW282hEnu9vv8xjqkFjpuGUKfwhKck`(`/var/lib/kotify/pbx_known_hosts`). 2026-10-16 PBX 세션에 요청 전달.
3. 접속 허용 출발지 10.0.5.204 만(가능하면).
4. kotify 에 알려 줄 것: 계정 이름, chroot 기준의 파일 경로.

## 2. 데이터 모델 — 새 테이블 `fax_inbox` (alembic `0025`)

| 컬럼 | 설명 |
|---|---|
| id | PK |
| pbx_log_id | UNIQUE — 로그와 1:1 |
| received_at | 로그 `unix_date` (UTC ISO) |
| sender_number | `sender` 에서 뽑은 숫자만 (없으면 빈 값) |
| status | `RECEIVED` / `FAILED` (로그 상태) |
| error | 실패 사유(번호 없음) |
| pbx_file | 로그 파일 이름 |
| pdf_blob / file_size_bytes | 가져온 PDF (가져오기 전 NULL) |
| fetch_status / fetch_attempts | `PENDING`·`FETCHED`·`FETCH_FAILED`·`NONE`(실패 수신) / 시도 수 |
| first_viewed_at / first_viewed_by | 처음 연 시각·사람 (안 읽음 표시용, 팀 공유) |
| created_at | |

## 3. API·화면·권한

- `GET /fax/inbox?limit&cursor` — 목록(보낸 번호 + 하이웍스/주소록 이름, 상태, 크기, 열람 여부)
- `GET /fax/inbox/{id}/pdf` — 권한 확인 후 PDF inline 전달, 첫 열람 기록, 감사 로그 `FAX_INBOX_VIEW`
- `POST /fax/inbox/{id}/refetch` — PDF 다시 가져오기(admin)
- 화면: `/fax` 를 **보낸 팩스 / 받은 팩스** 탭(URL `?tab=inbox`)으로 나누고, 받은 팩스 표에 받은 시각·보낸 곳·상태·안 읽음 표시·보기 버튼. 사이드바 팩스 항목에 안 읽은 수 표시는 하지 않는다(필요하면 후속).
- 권한(결정 필요): §5 질문 1.
- 개인정보: 보낸 번호·PDF 는 로그에 남기지 않는다(기존 규칙).

## 4. 테스트

- 백엔드(pytest·respx·sftp 는 subprocess 목): 수신 로그 → 행 생성·중복 없음, 발신 매칭과 같은 스캔에서 함께 처리, 자리표시·빈 ID, 파일 이름 검증(`../`·다른 이름 거부), PDF 시그니처·크기, SFTP 실패 재시도·3회 후 FETCH_FAILED, 권한·감사·첫 열람 기록, 마이그레이션 0025.
- 웹(Vitest): 탭 전환, 받은 팩스 표(이름·상태·안 읽음), 보기 링크.
- 운영: 키 생성·호스트 키 고정 → PBX 계정 생성 후 기존 로그 93번 PDF 1건 가져오기(크기·시그니처만 확인) → 사용자와 외부에서 02-3663-9887 로 실제 수신 시험.

## 5. 결정 필요

1. 받은 팩스를 볼 수 있는 사람: admin 만 / sender 이상 / 로그인한 모두(viewer 포함)
2. 수신 실패 기록(보낸 번호·사유)도 목록에 보일지
3. PDF 보관 기간: 영구(보낸 팩스와 같음) / 일정 기간 후 삭제
4. 기존 수신 로그(74·93 등 이전 것)도 가져올지, 배포 이후 수신만 볼지
