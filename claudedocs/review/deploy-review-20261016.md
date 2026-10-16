# 배포 전 코드 리뷰 (2026-10-16)

운영: `bb5e4c3`, alembic head `0025` (CT 에서 읽어 확인).
배포 후보: `origin/main` 4c0bc57(웹 재시작 90초 멈춤 수정 2c24502 + 문서) · `fix/msghub-review-deterministic` (5062ecd, 0c8d74c) · `jj/rcs-image-support-031ed3` (249ecc6). 열린 PR 13·14 는 GitHub Actions 버전 올림(Actions 꺼짐, 배포와 무관).
방법: 리뷰어 5명 병렬(커밋별 3, 배포 경로 1, 두 첨부 구현 비교 1), 각 브랜치를 `git archive` 로 풀어 관련 테스트 실행. 아래 '확인됨' 은 코드·실측으로 다시 확인한 것.

## 처리 결과 (브랜치 `fix/msghub-review-deterministic`, 2026-10-16, 미푸시·미배포)

사용자 지시: "fix 브랜치 먼저 병합, MO 첨부는 mo_media 테이블로 합치고 0026 하나로, 중간 항목(M1~M7) 전부 수정. 비이미지 첨부는 MMS만 내려받기 제공." 검증은 로컬뿐이다(아래). 운영 CT 는 건드리지 않았다.

| # | 처리 | 커밋 |
|---|------|------|
| B1·B2 | `origin/main`(4c0bc57) 병합 뒤 `jj/rcs-image-support-031ed3`(249ecc6) 병합. 첨부를 `mo_media` 하나로 합쳐 `source`(`RCS_URL`/`MMS_API`)·`next_fetch_at` 추가, 상태 PENDING/FETCHING/FETCHED/FAILED/UNSUPPORTED. `mo_messages.content_*`·`0026_mo_content.py`·`mo_content.py`·`/threads/mo/{id}/content`·`MessageAttachmentView` 제거, `0026_mo_media.py` 하나에 MMS 소급(실제 moKey·`content_cnt>0`·RCS 아님, `NOT EXISTS`, 깨진 JSON 행도 오류 없이). 선점·지수 간격·한 건 60초 상한을 두 source 에, 재조정 루프·웹훅 백그라운드 호출 하나, 주기 작업이 받은 첨부도 SSE. MMS 비이미지는 내려받기(octet-stream·attachment), RCS 는 사진만 | `bd593fc` |
| M1 | worker: 마이그레이션 전 단계 실패면 DB 복원 안 함. 뒤 실패면 systemd-run 별도 unit 이 `systemctl stop kotify` → 복원 → `start`(웹 버튼 경로의 worker 는 kotify cgroup 안이라 직접 stop 하면 자기도 죽음) | `cf78bac` |
| M2 | preload 사본 갱신은 **worker 가 아니라 post-restart** 에서 `install -d -m0755`·`install -m0644` — worker 는 웹 버튼 경로에서 kotify 의 `ProtectSystem=strict` 안이라 `/usr/local` 에 쓸 수 없다(`ReadWritePaths` 는 /opt·/var/lib·/var/log/kotify 뿐). post-restart 는 worker 가 systemd-run 으로 띄워 제약 밖이다. unit 에 `ExecStartPre=/usr/bin/test -r …`. deploy/README 에 사본 먼저·unit 나중 설치 순서 | `cf78bac` |
| M3 | 29002 대기 30→5초(RCS·일반). 대화방 단건 답장은 29002·[재전송] 재시도 없이 실패(502). `experimental.proxyTimeout` 120초(1,000명=100청크 순차 + 청크당 최대 5초 재시도, 근거 next.config 주석). 답장 `Idempotency-Key`(같은 키면 첫 결과 반환, 동시 중복은 409, 거부 확정이면 브라우저가 새 키). 청크 간 속도 조절은 계약 TPS 근거가 없어 넣지 않음 | `61899e5` |
| M4 | 인증 오류로 멈추면 이 청크와 남은 청크를 거부 코드로 FAILED 기록, state·카운트 확정 후 예외. 토큰 발급 실패(`AuthError`)도 확실한 미접수. 단건 답장은 502 실패 말풍선 | `61899e5` |
| M5 | 재발급은 토큰 오류(20003·20004)에만, 거부된 토큰이 지금 캐시 토큰일 때만 폐기. MO 첨부 29011 은 그 행 FAILED 후 루프 계속, 그 밖 인증 오류는 주기 중단 | `cba2b80` |
| M6 | 050 안심번호 12자리 허용(서버·웹). 대화방 답장은 형식 검사 없이 숫자만 남겨 발송 | `cba2b80` |
| M7 | RCS 401·403 은 `인증 거부 HTTP …` 로 구분해 간격 두고 재시도(3회 뒤 FAILED). deploy/README 에 배포 직후 집계 SQL·다시 PENDING 으로 돌리는 UPDATE | `bd593fc` |
| 낮음 | 업로드·예약 취소 응답에 AuthError 원문 비노출, 첨부 한 건 60초 상한, 주기 작업이 받은 첨부 SSE 알림 | `cba2b80`·`bd593fc` |

남은 낮음(손대지 않음): `to_number_raw` 에 정규화 값 저장(문서에 명시), 형식 오류 리포트 200 의 복구 불가(설계 선택, SPEC 기록), 30124 기존 행 비용 0원, rcs DNS rebinding 여지·사진 캐시 `max-age=86400`·BLOB 으로 DB·백업 증가, post-restart 롤백 때 백업 이후 데이터 유실(기존).

검증(로컬, 병합 트리): pytest 969개·ruff, 웹 typecheck·lint·Vitest 26파일 239개. alembic: 0025 DB(RCS·MMS·대체 키·깨진 JSON·글만 회신 5행)에서 `upgrade head` → mo_media 3행(RCS 1·MMS 2), `mo_messages` 컬럼 변화 없음 → `downgrade 0025`(mo_media 삭제, 회신 5행 유지) → 다시 `upgrade head`, head 는 `0026` 하나. 운영 NPM `proxy_read_timeout`·통신사 RCS 주소 실제 응답·msghub `/mo/v1/file` 실제 응답은 확인하지 못했다.

## 배포 차단 (높음)

| # | 문제 | 근거 | 확신 |
|---|------|------|------|
| B1 | 두 브랜치가 같은 alembic 리비전 `0026`(down `0025`) — `0026_mo_content.py`, `0026_mo_media.py`. 파일명이 달라 git 충돌로 안 잡힘. 함께 두면 `upgrade head` 가 `Multiple head revisions` 로 실패 → worker 롤백(B2 경로) | 리뷰어가 0025 DB 에서 실측 | 확인됨 |
| B2 | 두 브랜치 병합 시 8개 파일 충돌(HANDOFF.md, deploy/README.md, threads.py, webhook.py, chat.py, test_thread_read_migration.py, ThreadView.tsx, web/types/chat.ts). 같은 이름의 `attachment`/`MessageAttachment` 를 서로 다른 모양으로 정의 | `git merge-tree` | 확인됨 |

두 첨부 구현은 **중복이 아니라 채널이 다르다**: fix 는 MMS MO(`GET /mo/v1/file/{moKey}`, 문서 경로), rcs 는 RCS 양방향 `fileMessage.fileUrl`(통신사 주소 직접). 둘 다 필요하다.
통합 권장안: fix 를 먼저 병합하고, MO 첨부 저장은 rcs 의 `mo_media` 테이블(별도 테이블·선점 UPDATE·CSP sandbox)로 합쳐 `source`(`RCS_URL`/`MMS_API`)·`next_fetch_at` 컬럼을 더한다. 0026 은 하나로 다시 쓰고(`mo_messages` 는 그대로), fix 의 `fetch_mo_content`·MMS 재시도 정책·moTitle 표시·비이미지 내려받기를 가져온다. 미정: 비이미지 첨부 처리(MMS 는 내려받기 제공, RCS 는 이미지만 — 제안).

## 배포 전 수정 권장 (중간)

| # | 위치 | 문제 | 확신 |
|---|------|------|------|
| M1 | `deploy/kotify-update-worker.sh:74-76` (main, 기존) | 배포 실패 롤백이 **서비스가 도는 중에** `sms.db` 를 덮어쓰고 WAL·SHM 을 지움 → DB 손상 위험, 백업 이후 수신 MO·리포트 유실. B1 이 그대로 나가면 실제로 탐 | 경로 확인됨, 손상은 추정 |
| M2 | `deploy/kotify-web.service` (main) | 90초 멈춤 수정은 preload 사본(`/usr/local/lib/kotify/kotify-web-shutdown.cjs`)과 unit 을 CT 에 **수동 설치**해야 효과. 운영 CT 에 둘 다 없음(확인). 업데이트 버튼만 누르면 효과 없음. 순서를 틀려 unit 먼저 넣으면 web 이 `MODULE_NOT_FOUND` 로 기동 실패 반복. 수정 자체는 Next 14.2 standalone 에서 실측(5초 만에 정상 종료) | 확인됨 |
| M3 | fix: `compose.py:907-918` (`_RATE_LIMIT_WAIT = 30`) | 일반 모드 29002 재시도가 웹 요청 안에서 30초 대기 → Next rewrite 기본 프록시 타임아웃 30초(`proxy-request.js`, next.config 에 설정 없음)로 브라우저는 500. 백엔드는 계속 발송, 대화방 답장은 멱등키가 없어 다시 누르면 **같은 SMS 두 번**. 이 커밋으로 생긴 회귀 | 타임아웃 확인됨, 이후 동작 추정 |
| M4 | fix: `auth.py:33`, `compose.py:404-411, 938-945` | 토큰 실패가 캠페인 중단 경로를 타면서 캠페인이 `DISPATCHING`(예약은 `RESERVED`)·`pending_count=전체` 로 멈춤. 나머지 청크는 행이 없어 재조정도 못 함. 같은 멱등키 재시도는 이 캠페인을 성공으로 돌려줌. 단건 답장은 502 실패 말풍선 → 500 으로 바뀜 | 확인됨 |
| M5 | fix: `client.py _call`, `mo_content.py` | 20001·29025(IP)·29011(권한) 등 토큰과 무관한 인증 오류에도 공유 토큰을 버리고 재발급. `/mo/v1/file` 이 29011 이면 60초마다 재발급(하루 1,440회+) → 50010 발급 제한에 걸리면 **모든 발송 정지**. 동시 요청이면 막 받은 새 토큰까지 버림 | 재발급 동작 실측, 29011 수신은 추정 |
| M6 | fix: `app/util/phone.py:54` | 정규식 `^(?:0\d{8,10}\|1[5-9]\d{6})$` 이 12자리 050 안심번호를 거부(확인). 그 번호에서 온 기존 대화방은 답장 불가(422), 캠페인은 400. 웹 `isSendableNumber` 도 같음 | 확인됨 |
| M7 | rcs: `mo_media.py download` | RCS 사진을 인증 없이 통신사 `fileUrl` 로 직접 받음(문서에 규정 없음, 실주소로 받아 본 적 없음). 401/403 이면 즉시 FAILED·재시도 없음 → 운영 새 사진 전부 "불러올 수 없음". 배포 직후 `mo_media.error` 분포 확인 필요 | 추정 |

## 낮음

- fix 0026 소급이 RCS 여부를 안 가림(`content_cnt>0 AND mo_key NOT LIKE 'syn-%'`) — 리뷰어 확인상 RCS 행은 content_cnt 0 이라 실제 영향 없음.
- 업로드(`campaigns.py:951`)·예약 취소(`:723`) 응답에 `AuthError` 원문(httpx 예외 문구) 노출.
- 재조정 루프 안 첨부 받기가 순차(fix 20건×30초, rcs 5건×20~30초) → 같은 주기의 재조정·팩스 추적 지연. rcs 는 한 건 전체 시간 상한 없음.
- 재조정 루프가 나중에 받은 MMS 첨부는 SSE 알림이 없어 열린 대화방이 "받아 오는 중" 으로 남음.
- `to_number_raw` 에 정규화 값이 저장돼 "원본 보존" 주석과 다름.
- 형식 오류 리포트를 200 으로 받으면 우리 파서 버그일 때 msghub 재전송으로 복구 불가(설계 선택, 운영 문서에 기록 권장).
- 30124 를 성공으로 바꿔도 기존 행 비용은 0원 그대로.
- rcs: DNS 검사와 실제 연결 사이 재조회(DNS rebinding 여지, 웹훅 토큰 유출 전제), 재시도 3회가 60초 간격이라 약 3분 장애에 소진, 사진 캐시 `max-age=86400`, 사진 BLOB 으로 DB·백업 증가.
- post-restart 롤백 때 백업 이후 데이터 유실(기존).

## 확인했고 문제없던 것

- 테스트: 5062ecd 새 테스트 14개 중 13개가 수정 전 코드에서 실패(버그를 실제로 잡음), 수정 후 21개 통과 · 0c8d74c 관련 59개 통과 · rcs 31개 통과 · preload·post-restart 12개 통과.
- 같은 cliKey 재시도의 이중 발송 없음(29002 는 요청 전체 거부), 재시도 대기 중 SQLite 쓰기 잠금 없음, MO 배치 내 dedupe 정확.
- 첨부는 둘 다 DB BLOB 이라 파일 경로·디렉터리 권한 문제 없음, 조회 라우트는 대화방과 같은 `require_user`(viewer+), nosniff·SVG/HTML inline 제외.
- rcs SSRF 방어(https·공인 IP·리다이렉트마다 재검사), 형식은 파일 앞부분으로 판정, 선점 UPDATE 로 중복 다운로드 방지.
- 수신번호 정규화 규칙이 기존 `_norm_to_number` 와 같아 대화방이 갈리지 않음.
- 결과코드 집계가 실패 CSV·대시보드·리포트·비용 상한에서 같은 기준(`DELIVERED_CODES`).
- 각 0026 마이그레이션 단독 upgrade/downgrade 정상, alembic 연결은 FK pragma 꺼져 CASCADE 삭제 없음.
