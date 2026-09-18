# U+ 메시지허브 최신 가이드 대조 검토

검토일: 2026-09-18
대상: `https://doc.msghub.uplus.co.kr/` 공개 REST API 가이드와 현재 작업 트리
방법: 공식 페이지의 인증, SMS/MMS, RCS, 컨텐츠, 리포트, 예약, MO, 모니터링 문서를 수집해 코드·테스트와 대조했다. 공급자 실계정 요청은 하지 않았고, MO 번호 검증과 리포트 재조정은 in-memory DB와 mock 응답으로 재현했다.

## 구현 상태

아래 발견사항은 수정 전 동작을 기록한 것이다. 2026-09-18 현재 코드에는 전 항목을 반영했다.

| 발견사항 | 반영 내용 |
|---|---|
| SMS/MMS MO 번호 반전 | `moNumber`를 우리 수신번호, `moCallback`을 고객 번호로 처리하고 RCS 형식과 분리했다. 기존 역방향 payload는 등록 Caller를 기준으로 호환한다. |
| RCS에 MMS 파일 ID 사용 | 업로드 시 MMS와 RCS에 각각 등록하고 채널별 ID·만료 시각을 저장한다. RCS 본문과 MMS fallback은 각자의 ID를 사용한다. |
| 잘못된 환경 값 허용 | API와 UI를 `production`·`qa`로 제한하고 레거시 잘못된 저장값은 안전하게 거부한다. |
| 예약 30일 상한 누락 | API 경계에서 현재부터 30일을 초과하는 예약을 거부한다. |
| 파일 만료 미검사 | 즉시 또는 예약 발송 시각을 기준으로 MMS·RCS 파일 만료를 검사한다. |
| 재조정 조회 고착 | 오래된 행부터 안정적으로 조회하고 `OVER_DATE`·`INVALID_KEY`를 최종 실패로 닫는다. |
| healthCheck 누락 | 60초 주기 루프에서 `PUT /client/v1/healthCheck`를 호출하며 실패가 재조정을 막지 않게 했다. |
| 로컬 API 문서의 구 URL | SMS/MMS 발송과 multipart MMS 경로를 현재 `/xms/*` 경로로 갱신했다. |

자동 검증은 mock 공급자와 임시 DB를 사용한다. U+ QA 계정에서 실제 MO, RCS 이미지와 MMS fallback, 30일 경계 예약, 웹훅 재전송을 확인하는 절차는 운영 전 E2E 체크리스트에 남겼다.

최종 구현 검증은 백엔드 비포트 테스트 706개와 로컬 포트 통합 테스트 7개, 프런트엔드 테스트 154개를 통과했다. Ruff, TypeScript, ESLint, diff 공백 검사와 Next.js 프로덕션 빌드 18개 페이지도 통과했다. 임시 SQLite에서 현재 Alembic head `0023`까지 upgrade, `0018` downgrade, 재upgrade를 검증했고 `0021`의 채널별 첨부 열 생성·제거도 확인했다.

## 즉시 수정이 필요한 문제

### P1 — SMS/MMS MO의 발신번호와 수신번호를 반대로 해석한다

공식 [MO 가이드](https://doc.msghub.uplus.co.kr/rest-api/05%EB%B6%80%EA%B0%80%EC%84%9C%EB%B9%84%EC%8A%A4/0502mo/) 예시에서 `moNumber`는 우리 서비스의 MO 수신번호(대표번호), `moCallback`은 고객의 발신 휴대폰 번호다. 현재 [schemas.py](/Users/stopdragon/Documents/kotify/app/msghub/schemas.py:304)는 `number=moNumber`, `callback=moCallback`으로 매핑하고, [webhook.py](/Users/stopdragon/Documents/kotify/app/routes/webhook.py:250)는 `callback`이 활성 Caller인지 검사한다. 따라서 대표번호를 `moNumber`로 보내는 정상 SMS/MMS MO가 고객 휴대폰 번호를 Caller로 검사받아 거부된다.

재현 결과: 활성 Caller를 `0212345678`로 만들고 공식 의미에 맞춰 `moNumber=0212345678`, `moCallback=01099998888`을 보낸 경우 HTTP 200 ACK는 반환하지만 DB 저장 건수는 0이었다. 공급자는 성공으로 인식하므로 해당 회신은 재전송되지 않아 영구 유실된다.

수정 방향은 SMS/MMS에서 `mo_number=moCallback`(고객 번호), `mo_callback=moNumber`(우리 대표번호)로 저장하고, 활성 Caller 검증은 `moNumber`에 적용하는 것이다. RCS 양방향은 현재처럼 `phone`을 고객 번호, `chatbotId`를 우리 채널로 처리하므로 두 형식을 분리해야 한다. 이 변경에는 MO 회귀 테스트와 기존 대화방 그룹핑 테스트가 필요하다.

### P1 — RCS 이미지 발송에 MMS용 파일 ID를 재사용한다

공식 [컨텐츠 관리 가이드](https://doc.msghub.uplus.co.kr/rest-api/03%EC%B1%84%EB%84%90/0302mnt-contents/)는 업로드 URL을 `/file/v1/{ch}`로 정의하고, RCS 파일과 MMS 파일을 채널별로 등록한다. 현재 [campaigns.py](/Users/stopdragon/Documents/kotify/app/routes/campaigns.py:943)는 모든 이미지를 `channel="mms"`로만 업로드한다. 이후 [compose.py](/Users/stopdragon/Documents/kotify/app/services/compose.py:478)는 동일한 ID를 RCS `media=maapfile://...`와 MMS fallback 양쪽에 넣는다.

공식 RCS 발송 예시는 `RPMSMTX001`/`RPMSMMX001`에서 RCS 등록 파일을 사용하고, 파일 가이드에는 채널별 파일 형식·크기·만료가 별도로 적혀 있다. 현재 경로는 RCS 이미지 발송 때 파일 ID/채널 불일치로 `21003`, `55815` 계열 오류 또는 RCS 미전달을 일으킬 수 있다. RCS와 MMS 파일을 각각 등록·보관하거나, 발송 채널에 맞는 ID를 선택하도록 모델과 업로드 API를 분리해야 한다.

## 높은 우선순위의 동작·설정 문제

### P1 — UI가 허용하는 환경 값과 클라이언트가 지원하는 환경 값이 다르다

설정 화면은 `production · staging · sandbox`를 안내하고 [ProviderSettingsForm.tsx](/Users/stopdragon/Documents/kotify/web/components/settings/ProviderSettingsForm.tsx:194) 그대로 저장한다. 그러나 [client.py](/Users/stopdragon/Documents/kotify/app/msghub/client.py:38)의 `_HOSTS`는 `production`, `qa`만 갖는다. `staging` 또는 `sandbox`를 저장하면 설정 저장 뒤 클라이언트 생성 시 `KeyError`가 발생하며 발송·인증 테스트가 정상 오류 응답이 아닌 서버 오류로 끝난다. 공식 가이드는 인터넷 환경을 상용/검수(`production`/`qa`)로만 구분한다.

환경을 `production`/`qa` 선택값으로 제한하고 Pydantic에서 검증하거나, 실제 지원 환경을 추가할 때만 호스트 매핑과 함께 추가해야 한다. 기존 저장값이 잘못된 경우도 클라이언트 생성 전에 명시적인 설정 오류로 반환해야 한다.

### P2 — 예약 발송 최대 30일 제한을 로컬에서 검사하지 않는다

공식 [SMS/MMS 가이드](https://doc.msghub.uplus.co.kr/rest-api/02%EB%A9%94%EC%8B%9C%EC%A7%80%EB%B0%9C%EC%86%A1/0202xms/)는 예약을 현재 시점부터 최대 30일까지로 제한한다. [parse_reserve_time](/Users/stopdragon/Documents/kotify/app/services/compose.py:154)는 최소 리드 타임만 검사하고 30일 상한이 없다. UI에서 장기 예약을 허용한 뒤 공급자에서 거절되면 캠페인·청크별 오류 처리에 의존하게 되므로, API 경계에서 30일 상한을 검증하고 회귀 테스트를 추가해야 한다.

### P2 — 만료된 업로드 파일을 발송 전에 차단하지 않는다

공식 [컨텐츠 가이드](https://doc.msghub.uplus.co.kr/rest-api/03%EC%B1%84%EB%84%90/0302mnt-contents/)는 등록 파일에 유효기간이 있고 만료 파일은 사용할 수 없다고 명시한다. [campaigns.py](/Users/stopdragon/Documents/kotify/app/routes/campaigns.py:968)는 `file_expires_at`을 저장하지만 [compose.py](/Users/stopdragon/Documents/kotify/app/services/compose.py:466)는 존재·소유권만 검사한다. 예약 발송 또는 오래된 초안은 공급자 요청이 `21029`로 실패할 수 있다. 발송 시각 기준으로 만료를 검사하고 재등록 안내를 제공해야 한다.

### P2 — 리포트 재조정의 오래된 미완료 행이 조회 상한을 계속 점유한다

공식 [리포트 가이드](https://doc.msghub.uplus.co.kr/rest-api/02%EB%A9%94%EC%8B%9C%EC%A7%80%EB%B0%9C%EC%86%A1/0208report_v12/)의 `sent` 조회는 최대 90일이고, `OVER_DATE`는 조회기간 초과 상태다. 현재 [reconcile.py](/Users/stopdragon/Documents/kotify/app/services/reconcile.py:104)는 `PENDING/REG/ING/FB_PENDING`를 시간순 없이 최대 200건으로 자른다. [report.py](/Users/stopdragon/Documents/kotify/app/services/report.py:373)의 `_record_no_result`는 `FAILED` 행만 `result_code`를 기록한다. 따라서 91일 이상 된 `REG` 행은 `OVER_DATE`를 받아도 계속 미완료로 남고 매 주기 앞의 200건을 점유해 최근 미완료 메시지의 재조정을 지연시킨다.

재현 결과: 오래된 `REG` 200건과 최근 `REG` 1건을 만들고 오래된 키에 `OVER_DATE`, 최근 키에 `DONE`을 반환하는 mock으로 재조정하면 두 주기 모두 같은 오래된 200건만 조회됐다. `OVER_DATE/INVALID_KEY`를 상태별 종료 상태로 기록하거나 대상에서 제외하고, 쿼리에 `sent_at` 정렬을 넣어 최근 행이 굶지 않게 해야 한다.

## 가이드 반영을 권장하는 운영 개선

- 공식 [모니터링 API](https://doc.msghub.uplus.co.kr/rest-api/06%EB%AA%A8%EB%8B%88%ED%84%B0%EB%A7%81/0601-monitoring/)는 1분 이하 간격의 `PUT /client/v1/healthCheck` 호출을 권장한다. 현재 msghub 클라이언트에는 health check 호출과 세션 장애 알람 연계가 없다. 운영 장애를 빠르게 감지하려면 별도 주기 작업으로 추가한다.
- 공식 리포트는 처리 결과를 120초 안에 200으로 ACK하지 않으면 동일 리포트를 재전송하고, 최대 100건 배치·중복 수신 방지를 요구한다. 현재 웹훅의 멱등 처리는 양호하지만, `400`이 발생하는 DB 장애·프로세스 재시작 시나리오에 대해 실제 공급자 재전송을 QA에서 확인할 필요가 있다.
- 로컬 [msghub-api-guide.md](/Users/stopdragon/Documents/kotify/claudedocs/msghub-api-guide.md), [msghub-template-api.md](/Users/stopdragon/Documents/kotify/claudedocs/msghub-template-api.md), [msghub-migration-spec.md](/Users/stopdragon/Documents/kotify/claudedocs/msghub-migration-spec.md)는 일부 구버전 `/msg/v1/sms`, `/msg/v1/mms`와 현재 가이드의 `/xms/sms/v1`, `/xms/mms/v1`를 혼용한다. 실행 코드는 현재 endpoint를 사용하지만 문서가 운영자·후속 개발자의 잘못된 구현을 유도할 수 있으므로 최신 공식 URL과 `api-send` 호스트로 통일해야 한다.

## 최초 검토 당시 검증 상태

- 공개 가이드 23개 페이지를 임시 디렉터리에 수집해 대조했다. 인증의 SHA512 이중 해싱, 토큰 수명, RCS v1.1/양방향 endpoint, SMS/MMS 10건 제한, 예약 30일, 리포트 90일 조회·120초 ACK, 파일 채널·만료 규칙을 확인했다.
- 관련 회귀 테스트 묶음(`MO`, SMS fallback, RCS 양방향 요청, 비용, 리포트 비용)은 `.venv/bin/pytest` 기준 39 passed(경고 1건)였다.
- `.venv/bin/pytest -q`: 기존 작업 트리에서 670 passed, 2 failed, 7 errors. 실패 2건은 현재 동시 변경 중인 `0020` 마이그레이션 기대치와 기존 테스트 기준 불일치이며, 7건은 sandbox에서 테스트용 로컬 포트 bind가 차단된 환경 오류다. 별도 승격 실행으로 `tests/test_post_restart_script.py`는 7 passed.
- 이 검토는 코드 수정 보고서가 아니라 발견사항 보고서다. 기존 사용자 변경 파일은 보존했다. P1 두 건(MO 번호 해석, RCS/MMS 파일 채널)을 먼저 수정하고, 수정 후 전체 테스트와 U+ QA 계정의 실제 MO·RCS 이미지·예약 경로를 검증해야 한다.
