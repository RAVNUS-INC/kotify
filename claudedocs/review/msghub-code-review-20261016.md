# msghub 연동 코드 리뷰 (2026-10-16)

기준: [claudedocs/msghub-api/](../msghub-api/00-README.md) (현행 공식 문서 정리본). main `f51e8cb` 기준, 읽기 전용 리뷰.
범위: 클라이언트·인증(`app/msghub/*`), 리포트(`routes/webhook.py`·`services/report.py`·`reconcile.py`), MO·대화방 답장(`webhook.py`·`services/chat.py`), 캠페인 발송(`services/compose.py`·`routes/campaigns.py`).
'확인됨' 은 코드 경로를 직접 다시 읽어 확인한 것, '추정' 은 msghub 실제 동작이 문서에 없어 결과가 갈릴 수 있는 것.

## 처리 결과 (브랜치 `fix/msghub-review-deterministic`, 2026-10-16, 미푸시 — 이후 배포 전 리뷰 [deploy-review-20261016.md](deploy-review-20261016.md) 반영)

아래 리뷰 본문은 리뷰 시점 그대로 두고 처리 결과만 여기 적는다. 검증은 로컬 테스트(pytest·ruff·웹 typecheck·lint·vitest)뿐이고 운영·msghub 실제 응답으로는 확인하지 않았다. 보류 항목(3·4·6·7)은 리뷰 세션이 위임받은 기본안대로 처리했다.

| # | 처리 | 내용 |
|---|------|------|
| 1 | 수정 | `AuthError` 를 `MsghubAuthError` 하위로 — 토큰 실패가 첫 청크에서 캠페인을 멈춘다(`5062ecd`) |
| 2 | 수정 | 사전 갱신 실패 시 30초 넘게 남은 토큰을 계속 쓰고 30초 뒤 재시도(`5062ecd`) |
| 3 | 수정 | `MsghubClient._call`·`fetch_mo_content`: 토큰 오류(20003·20004)일 때만, 거부된 토큰이 지금 캐시한 것과 같을 때만 버리고 1회 재발급·재요청. 그 밖의 인증 오류는 바로 올림(배포 전 리뷰 M5 반영) |
| 4 | 수정 | `30124` 는 전달 성공(집계·과금). 단말 전달 가능 4개·성공 불확실 3개(`codes.UNCERTAIN_CODES`)는 실패(0원)로 확정하되 양방향 대체 SMS 를 보내지 않고, 수신자 배지 '결과 불확실'·말풍선 '결과 불확실'(주의 색)로 구분. 성공 판정을 쓰는 집계(캠페인·대시보드·리포트·비용 상한·알림 담당자·답장 기본 채널) 모두 `DELIVERED_CODES` 기준 |
| 5 | 수정 | 배치 내 moKey 중복은 duplicates 로 건너뜀(`5062ecd`) |
| 6 | 수정 | RCS 사진 브랜치와 합쳐 `mo_media` 테이블 하나(`source` RCS_URL/MMS_API, alembic `0026` 하나, `mo_messages` 는 그대로). MMS 는 `GET /mo/v1/file/{moKey}` 로 받아 보관(10MB), 지수 간격 재시도·7일 만료, 사진이 아니면 내려받기. 대화방에 `moTitle`·첨부, 목록·알림 `[사진]`/`[첨부 파일]`. 조회 `GET /api/chat/media/{mo_id}` |
| 7 | 수정 | 서버가 숫자만 남긴 국내 번호(휴대폰·0 시작 9~11자리·15xx~19xx 8자리, `+82`→0)로 정규화해 dedupe·발송. 틀린 값이 있으면 `POST /campaigns` 400 `invalid_recipients`(값 목록), 미리보기 `valid=false`. 웹 입력도 같은 규칙으로 즉시 표시·제출 차단, 안내 문구 정정("이름·그룹" 제거) |
| 8 | 수정 | 29002 를 5초 뒤 같은 cliKey 로 1회 재시도(처음 30초였으나 웹 요청 프록시 제한 때문에 배포 전 리뷰 M3 로 단축). 대화방 단건 답장은 재시도하지 않음. 청크 사이 속도 조절은 넣지 않음(계약 TPS 근거 없음) |

참고(낮음):

| 항목 | 처리 |
|------|------|
| health check 간격 | 재조정과 분리한 태스크, 시작 간격 50초(요청 시간 차감) |
| mnt-api 에 api 토큰 사용 | **확인 필요** — 코드 변경 없음. 운영 업로드 성공 기록으로 공용 여부를 확인할 것 |
| 예약 응답 `data` 형태 | 객체·객체 배열 모두 받고 그 밖은 빈 값(취소만 불가). 업로드 응답·`/msg/v1/sent` 도 같은 방어, 응답 본문이 객체가 아니면 `PARSE_ERROR` |
| 인증 ReadError·token 누락 | 수정(`5062ecd`) |
| 요청 단위 [재전송] 코드 | `RESEND_CODES` 는 5초 뒤 같은 cliKey 로 1회 재발송(RCS·일반 모두). 단말 전달 가능 코드는 재발송하지 않음 |
| 리포트 영구 형식 오류 | 본문·`rptLst` 형식 오류는 반영 없이 200, 일부 항목만 틀리면 그 항목만 건너뛰고 나머지 반영·200 (ERROR 로그, 값 없이 구조만). 토큰 불일치 401 은 보안상 유지 |
| 모르는 MO 형식 | 아는 목록 키가 없으면 WARNING(구조만) 후 기존대로 10000 |
| chatbotId 단일 | **확인 필요** — 현재 단일 채널이라 코드 변경 없음 |
| `49` 접두사·`describe`·docstring | 49 접두사 제거, 호출처 없는 `describe` 삭제, `MsghubServerError` docstring 정정 |
| LMS/MMS 제목 | RCS fallback 제목을 첫 줄 앞 20자로(개행 제거). 직접 LMS/MMS 의 빈 `title` 은 필수 여부가 문서에 없어 유지 — **확인 필요** |
| `#{..}`·`{{..}}` 이스케이프 | 공식 문서에 이스케이프 문법이 없어 코드 변경 없음 — **확인 필요**(사용자 본문에 이 문법이 있을 때 실제로 치환되는지) |

## 수정 권장 (중간)

| # | 위치 | 문제 | 근거 | 확신 |
|---|------|------|------|------|
| 1 | `app/msghub/auth.py:25` | 토큰 발급 실패 `AuthError` 가 `MsghubError` 계열이 아님 → compose 의 `except MsghubAuthError`(캠페인 중단)를 못 타고 일반 예외로 청크마다 FAILED·재인증 반복. 비밀번호 변경 후 1만 명 발송이면 인증 요청 ~1000회(50010 발급 횟수 초과 위험), 업로드 라우트는 500 | 01-auth, 09 §20000~20004·50010 | 확인됨 |
| 2 | `app/msghub/auth.py:126-143, 203-240` | 만료 10분 전 갱신이 5xx·파싱 오류로 실패하면 아직 유효한 토큰이 있어도 예외 → 인증 서버 순간 장애 동안 모든 발송 청크 실패 | 01-auth §토큰 수명(사전 갱신은 '권장') | 확인됨 |
| 3 | `app/msghub/client.py:56-66` | 서버가 토큰을 거부(20xxx)해도 캐시 무효화 안 함 → 로컬 만료까지 최대 ~50분 같은 토큰으로 계속 실패 | 09 §20004·29011·29025 | 추정 |
| 4 | `app/services/report.py:154, 360-382` | 리포트에서 `10000` 외 전부 실패 처리. 양방향 답장(RPCSAXX001)이면 곧바로 대체 SMS. 문서가 "단말 전달 가능"이라 한 41007·54004·55806·55820, 성공/성공불확실 30124·32114·55821·56003 도 실패로 보고 → 같은 답장 이중 수신·비용 0 집계 | 09 §재전송이 필요한 코드, 코드표 | 추정(리포트에 이 코드가 오는지 문서에 없음) |
| 5 | `app/routes/webhook.py:384-433` (+ `app/db.py:56 autoflush=False`) | MO 한 배치 안에 같은 moKey(또는 moKey 없이 같은 번호·시각·본문)가 두 번 오면 사전 조회가 미flush 행을 못 봐 UNIQUE 위반 → 배치 전체 롤백·20004 → msghub 재전송마다 같은 실패, 같은 배치 정상 MO 도 저장 안 됨 (리뷰어 재현 스크립트로 400 확인) | 19-mo §웹훅 | 동작 확인됨, 발생 빈도 추정 |
| 6 | `app/routes/webhook.py:407-412`, `app/services/chat.py:526-538` | MMS·RCS MO 첨부를 받아 오지 않음(`/mo/v1/file/{moKey}` 호출 코드 없음). 사진만 보낸 MO 는 빈 말풍선, 7일 지나면 원본 소실. MMS 제목 `moTitle` 도 대화방에 안 보임 | 19-mo §MMS MO 컨텐츠 조회(7일 보관, URL 24h 일회성) | 확인됨 |
| 7 | `app/routes/campaigns.py:185`, `compose.py:282, 896` | 수신번호를 서버가 검증·정규화하지 않고 입력 그대로 `recvInfoLst[].phone` 으로 보냄(이름·`+82`·20자 초과 가능). 요청 단위 거부면 같은 청크 정상 9명도 실패. dedupe 도 원문 문자열 기준이라 `010-1234-5678`·`01012345678` 이 둘 다 발송됨(의도된 주석 있음) | 02-xms §recvInfoLst(phone 20자, 국제번호 규칙) | 검증 부재 확인됨, 청크 전파는 추정 |
| 8 | `app/services/compose.py:931-939` | 일반(sms) 모드엔 29002(CPS 초과) 재시도가 없어 해당 청크 10명을 명시 거부로 FAILED 확정, 재조정에서도 제외 → 영구 미발송. RCS 모드는 30초 뒤 채널 전환 재시도가 있어 두 모드가 다름. 청크 사이 속도 조절도 없음 | 09 §재전송(29002 "잠시 후 다시 시도"), 02-xms §TPS | 확인됨 |

## 참고 (낮음)

- health check 간격이 60초 + outbox·팩스 추적·재조정 시간이라 항상 1분을 넘음 (`app/main.py:101, 126-145`, 21-monitoring "1분 이하").
- mnt-api(파일 업로드·통계)에 api 호스트 토큰을 씀. 10-mnt-auth 는 mnt-api 에 별도 인증 경로를 둠 — 공용 가능 여부 문서에 없음, 운영 업로드 성공 기록 확인 필요.
- 예약 응답 `data` 가 객체가 아니면 `inner.get` AttributeError → 접수된 예약을 FAILED 로 기록하고 webReqId 를 잃음 (`schemas.py:145-151`).
- 인증·갱신이 `httpx.ReadError`·`RemoteProtocolError` 와 `data.token` 누락(KeyError)을 재시도·AuthError 변환 없이 흘림 (`auth.py:187, 238`).
- 요청 단위 [재전송] 코드(21400 등)도 재전송 없이 FAILED(불확실)로 두고 재조정에만 맡김 (`compose.py:410-418`).
- 리포트 배치가 영구 형식 오류여도 400 → 72시간 재전송, 토큰 불일치 401 은 문서 미정의 응답 (`webhook.py:151-194`).
- 모르는 MO 페이로드 형식(키 0건)을 로그 없이 10000 성공으로 응답해 msghub 큐에서 삭제 (`schemas.py:403-410`, `webhook.py:319-323`). 운영에서 쓰는 `rcsBiLst` 형식은 현행 MO 문서에 없음.
- 양방향 답장 chatbotId 가 전역 설정 하나 — 양방향 채널이 둘 이상이 되면 다른 채널 replyId 와 섞임 (`client.py:374`). 현재 단일 채널이라 미발생.
- `codes.py` 의 `49` 접두사 재시도는 현행 코드표에 근거 없음(49xxx 대역 없음), `describe()` 는 호출처 없음, `MsghubServerError` docstring 의 29012 는 실제 분류와 다름.
- LMS/MMS 직접 발송은 항상 `title: ""`, RCS fallback 은 본문 앞 20자로 제목 생성(개행 포함 가능). 사용자 본문의 `#{..}`·`{{..}}` 를 이스케이프하지 않아 msghub 치환 대상이 될 수 있음.

## 문서와 일치함을 확인한 것

호스트 3종·경로·메서드 전부, apiPwd 해시 공식과 randomStr 20자, 토큰 1h/10분 전·refresh 25h/30분 전, 발송 요청 필드명, 동보 10명 청크, 즉시(`data[]`)·예약(`{regDt, webReqId}`) 응답 구분, 예약 취소 v1 + `resvCnclReason`, `/msg/v1/sent` 10건·`reqDt`·status 5종, 파일 업로드 multipart `reqFile`·`filePart`, 리포트 웹훅 필드명과 200/400 사용, 재전송 코드 15개 목록, MO 웹훅 필드명·응답 규약(10000/20xxx), 양방향 `/rcs/bi/v1.1` 필드·`header="0"`·cliKey 20자 이내, 대체 SMS `-fb` 23자 이내, 통합 RCS messagebaseId·mergeData 키, fbInfoLst 규칙, SMS 90/LMS 2000 byte 경계, 예약 30일 상한.

## 문서가 답하지 않아 판단 못 한 것

리포트에 성공불확실·[재전송] 코드가 실제로 오는지, 웹훅 재시도 횟수·401 취급, 서버 측 토큰 무효화 조건, mnt-api 토큰 공용 여부, 90 byte 계산 인코딩, LMS title 필수 여부, 통합 RCS 본문 최대 길이, mergeData 키 누락 시 동작, `rcsBiaLst`·`rcsBirLst` 의미.
