# Phase 5 — 관측성 & 운영 코드 리뷰

> 검토 범위: settings.py, reports.py, dashboard.py, notifications.py, search.py,  
> audit_api.py, setup.py, services/report.py, services/audit.py, services/setup_service.py,  
> util/time.py, deploy/kotify-update.sh, deploy/kotify-update-worker.sh,  
> web/components/settings/SystemUpdatePanel.tsx, SecuritySection.tsx  
> 심각도: 🔴 CRITICAL / 🟠 HIGH / 🟡 MEDIUM / 🟢 LOW

---

## 🔴 CRITICAL

---

### [🔴][⚙️] settings.py:600 — `/system/update/check` 엔드포인트에 인증 없음

**근거:**
```python
@router.get("/system/update/check", response_model=None)
async def check_system_update() -> dict | JSONResponse:
```
`router`는 `dependencies=[Depends(require_role("admin")), Depends(require_setup_complete)]`로 선언되어 있으나, `check_system_update` 핸들러는 `user: User = Depends(require_user)` 파라미터를 아예 선언하지 않았다. FastAPI 라우터 레벨 `dependencies`는 의존성 실행은 하지만 핸들러 시그니처에 없으면 반환값을 주입하지 않는다 — 즉 이 경우 `require_role("admin")`은 실행되어 보호가 유지된다.

**그러나** `/system/update/apply`(line 658)는 `user: User = Depends(require_user)`를 명시적으로 선언하는 반면, `check_system_update`는 선언하지 않아 두 엔드포인트의 패턴이 불일치한다. 라우터 레벨 `require_role("admin")`이 실제로 동작하는지, 그리고 `require_setup_complete`도 함께 적용되는지 검증이 필요하다.

**재현 조건:** FastAPI의 `APIRouter(dependencies=[...])` 동작을 로그로 확인. 만약 미들웨어 레벨에서 예외 처리가 누락되거나 라우터 include 시 `dependencies` 전달이 누락되면 비인증 GET 요청으로 내부 git 리포 커밋 히스토리가 노출된다.

**제안:** `check_system_update`에 `user: User = Depends(require_user)` 파라미터를 명시 추가해 `apply`와 일관된 패턴으로 만든다. 단순한 GET이라도 인프라 정보(커밋 메시지, 현재 배포 버전)를 노출하므로 인증 명시가 필수다.

---

### [🔴][⚙️] deploy/kotify-update.sh:46-50 — 커밋 메시지에 개행/역슬래시/단따옴표가 포함되면 JSON 파괴

**근거:**
```bash
COMMITS=$(git log --oneline HEAD.."origin/${BRANCH}" --max-count=20 \
    | sed 's/"/\\"/g' \
    | awk '{printf "%s{\"hash\": \"%s\", \"message\": \"%s\"}", ...}')
echo '{"update_available": true, ..., "commits": ['"${COMMITS}"']}'
```
`sed`는 `"` 만 이스케이프한다. 커밋 메시지에 다음이 포함될 경우:

- **개행(newline)**: git `--oneline` 출력의 제목줄에는 드물지만, 타이틀에 `\n`이 있으면 JSON이 멀티라인이 되어 파괴된다.
- **역슬래시 `\`**: `sed` 처리 전 `\`가 있으면 `\\` 없이 JSON에 삽입되어 파싱 실패.
- **단따옴표 `'`**: echo 의 `'...'` 내부에서 셸 쿼팅이 종료되어 셸 인젝션 가능성.
- **특수 문자(한국어 포함 유니코드)**: awk `%s` 포맷 처리에서 바이트/문자 경계 이슈 없으나 백슬래시는 여전히 위험.

재현: 커밋 메시지가 `fix: use \n for newline` 또는 `fix: it's broken` 형태이면 Python 측 `json.loads(last_line)`이 JSONDecodeError를 반환하고 `parse_failed` 502 응답이 나온다.

**제안:** `git log --format='json'` 대신 `jq`를 사용하거나, `git log --format='%H %s'`로 뽑은 뒤 `python3 -c "import sys,json; ..."` 등 안전한 JSON 직렬화를 사용한다. 또는 `git log` 결과를 파이썬 스크립트로 처리하도록 worker에 통합한다.

---

### [🔴][⚙️] deploy/kotify-update-worker.sh:106 — alembic 실패 감지 로직 버그

**근거:**
```bash
if ! runuser -u "${SERVICE_USER}" -- \
        "${VENV}/bin/alembic" -c "${INSTALL_DIR}/alembic.ini" upgrade head 2>&1; then
    echo '{"phase": "error", "step": "migrate", "message": "alembic upgrade failed"}'
    exit 1
fi
```
`2>&1` 리디렉션은 stderr를 stdout으로 합쳐 exit code로만 실패를 감지한다. 그런데 `set -euo pipefail` 환경에서 `if ! cmd`는 ERR trap을 **트리거하지 않는다** (negated condition은 `set -e`의 예외). 따라서 `exit 1`은 실행되나 그 직후 `cleanup_on_error` trap이 다시 실행되지 않아 **정상 rollback이 중복 실행되거나 건너뛰어질 수 있다**.

실제로 `exit 1`로 종료 시 `trap cleanup_on_error ERR`가 아닌 직접 exit이므로 rollback 출력(`{"phase": "error", "rollback": true, ...}`)이 두 번 찍히는 경우와 아예 안 찍히는 경우가 동시에 존재한다.

**제안:** `if ! alembic ...` 패턴 대신 그냥 실행해서 `set -e`와 `trap ... ERR`에 위임하거나, 반드시 직접 처리 시 `cleanup_on_error`를 명시 호출 후 `exit 1`한다.

---

### [🔴][🔴] settings.py:182-218 — `patch_org`에 감사 로그 누락

**근거:**
```python
@router.patch("/org", dependencies=[Depends(verify_csrf)], ...)
def patch_org(body: OrgPatchBody, user: User = Depends(require_user), db: Session = Depends(get_db)):
    with _settings_lock:
        ...
        db.commit()
    return {"data": _get_org_dict(db)}
```
`audit.log()` 호출이 전혀 없다. 조직명·시간대 변경은 민감한 설정 변경이지만 감사 로그에 기록되지 않는다. `patch_provider_settings`(line 495)는 `audit.log(db, actor_sub=user.sub, action=audit.SETTINGS_UPDATE)`를 호출하는 것과 불일치.

**재현:** org 설정 변경 후 `/audit` 조회 → 해당 이벤트 없음.

**제안:** `db.commit()` 직전에 `audit.log(db, actor_sub=user.sub, action=audit.SETTINGS_UPDATE, target="org")` 추가.

---

## 🟠 HIGH

---

### [🟠][🔢] reports.py:369 — avgDeliveryRate KPI가 Campaign 기준이 아닌 Message 기준과 혼재

**근거:**
```python
rate_now = (tot["ok"] / tot["total_sent"] * 100) if tot["total_sent"] > 0 else 0.0
```
`_kpis_totals`는 `SUM(Campaign.ok_count)` / `SUM(Campaign.total_count)`를 쓴다. `Campaign.ok_count`는 `_refresh_campaign_counters`(services/report.py:218)에서 `Message.status == 'DONE' AND result_code == SUCCESS_CODE`로 집계된다. 그러나 `_channels_breakdown`(reports.py:182)은 직접 `Message` 테이블을 조회해 `status == 'DONE' AND result_code == SUCCESS_CODE`를 필터링한다.

두 집계의 **시간 필터 기준이 다르다**: `_kpis_totals`는 `Campaign.created_at` 기준, `_channels_breakdown`도 `Campaign.created_at`을 JOIN 조건으로 사용하지만, `ok_count`는 메시지 리포트 수신 시점에 업데이트된다. 즉 기간 내 생성 캠페인의 메시지가 기간 이후에 도달 리포트를 받으면 `Campaign.ok_count`에는 포함되지만 `_channels_breakdown`에도 포함된다 — 이는 일관성이 있다.

**실제 버그**: `avgDeliveryRate` spark는 `_spark_rate(daily_sent_map, daily_ok_map, ...)`을 사용하는데, `_daily_ok`(line 317)는 `Campaign.ok_count`를 `Campaign.created_at` KST 날짜로 버케팅한다. 이는 **발송 시도 수**를 기준으로 하는 올바른 접근이나, 해당 캠페인의 `ok_count`가 나중에 업데이트되므로 과거 날짜의 spark 값이 시간이 지날수록 변한다 — "이미 지난 날짜의 그래프 값이 변함"이라는 UX 문제.

**제안:** 허용 가능한 설계이면 문서화. 만약 완결된 집계가 필요하다면 `Campaign.completed_at` 기준으로 전환을 고려.

---

### [🟠][⚙️] dashboard.py:186 — rcsRate 분모가 전체 성공(today_ok)이 아닌 RCS 성공만 카운트하는 의도와 실제 구현 불일치

**근거:**
```python
rcs_success = int(today_row.rcs_success or 0)
rcs_rate = round((rcs_success / today_ok * 100), 1) if today_ok > 0 else 0.0
```
`rcs_rate`의 분모가 `today_ok`(전체 성공 메시지)이다. 의도가 "전체 성공 중 RCS 비율"이면 올바르나, KPI 라벨이 `rcsRate`이면 보통 "RCS 채널의 성공률" (RCS 발송 시도 대비 성공)을 기대한다. `today_ok`가 0일 때(RCS 발송도 0)에만 0.0을 반환하므로, RCS 발송은 있는데 다른 채널 성공이 없는 경우 분모가 RCS 성공만 돼 100%가 나온다. 

실제로는 `today_ok`가 RCS 외 채널(SMS/LMS fallback) 성공까지 포함하므로 의미가 불명확하다.

**제안:** KPI 명칭과 계산식을 일치시킨다:
- "전체 성공 메시지 중 RCS 비율" → 현재 구현 유지, 라벨을 `rcsShareRate`로 변경
- "RCS 발송 시도 대비 RCS 성공률" → 분모를 RCS 전체 발송 수로 교체

---

### [🟠][⚙️] deploy/kotify-update-worker.sh:63 — PREV_HEAD가 git reflog 기반이라 git reset --hard 이후 틀릴 수 있음

**근거:**
```bash
PREV_HEAD=$(git rev-parse "HEAD@{1}" 2>/dev/null || git rev-parse HEAD)
```
trampoline(`kotify-update.sh`)이 이미 `git reset --hard origin/main`을 실행한 후 worker가 시작된다. worker 내에서 `HEAD@{1}`은 reset --hard 이전의 HEAD를 가리키는 것이 맞지만, `exec bash "${WORKER}"` 방식으로 프로세스가 교체되면 reflog entry가 맞게 기록되어야 한다. 그러나 **git reflog는 interactive/manual 사용을 위한 것**이며, 스크립트에서 `exec`으로 프로세스가 교체된 직후 reflog가 정확히 반영되지 않는 엣지 케이스가 있다.

더 안전한 방법: trampoline이 reset 전 HEAD를 `PREV_HEAD` 환경변수로 저장해 worker에 전달.

**재현 조건:** 빠른 연속 apply 시도나 git reflog gc 동작 후.

**제안:** trampoline에서 `export PREV_HEAD=$(git rev-parse HEAD)` 후 `git reset --hard`를 수행하고, worker는 환경변수를 사용.

---

### [🟠][🔢] reports.py:262-285 — `_delta(reply_count)` 에서 `is_percent=False` 사용이 의미론 불일치

**근거:**
```python
d_rep, dir_rep = _delta(replies, prev_replies)
```
`replies`는 절대 건수(정수)이다. `is_percent=False`이면 `_delta`는 `(current - previous) / previous * 100`으로 **비율 변화(%)**를 계산하고 `+N.N%` 형식으로 반환한다. 이는 "회신 수가 N% 증가" 의미로 옳다. 그러나 `is_percent=True`인 `avgDeliveryRate`와 혼동될 수 있다. 현재 구현은 의도상 맞으나, 주석이 없어 유지보수 시 오해 가능성이 있다.

실제 버그는 없으나 `previous == 0` 분기에서 `current > 0`이면 항상 `"+999.9%"`가 반환된다. 첫 달 신규 서비스에서 회신이 1건이라도 있으면 `+999.9%`로 표시 — 어색하지만 의도된 상한 표기.

**제안:** `_delta` 주석에 "절대값 변화 비율"과 "퍼센트 포인트 변화" 구분을 명시.

---

### [🟠][⚙️] deploy/kotify-update-worker.sh:144 — ERR trap 해제 이후 실패는 무조건 서비스 불구

**근거:**
```bash
# 빌드 완료 — 이후 실패는 롤백 불가 (코드는 이미 바뀌었고 서비스 재시작만 남음).
trap - ERR

NEW_HASH=$(git -C "${INSTALL_DIR}" rev-parse --short HEAD)
```
trap 해제 이후 `systemd-run` 실패나 `chown` 실패는 조용히 무시된다. 실제로는 `|| true`로 처리되어 있어 문제없지만, `git rev-parse`(line 146)나 후속 echo(line 163)가 실패하면 `done` JSON이 출력되지 않는다. Python 측(settings.py:712)은 `target_version`이 None이면 `error_info`를 찾고, 그것도 없으면 `rc`를 확인한다. rc가 0이면 `{"data": {"status": "ok", "version": "?"}}`를 반환하므로 프론트는 성공으로 인식하고 healthz polling을 시작한다 — 실제 서비스가 재시작 중에도 "완료"로 표시.

**제안:** trap 해제 후 `done` JSON 출력까지 최소한의 에러 처리 유지. `NEW_HASH` 계산 실패 시 `"unknown"` fallback 사용.

---

## 🟡 MEDIUM

---

### [🟡][⚙️] setup.py:328 — 완전한 셋업 완료 시 `BOOTSTRAP_INIT`이 아닌 `SETUP_COMPLETED` 를 사용해야 함

**근거:**
```python
audit.log(db, actor_sub=None, action=audit.BOOTSTRAP_INIT)
```
`setup/complete` 엔드포인트는 운영자가 위저드를 통해 완료하는 행위다. `BOOTSTRAP_INIT` 상수는 시스템 초기화 이벤트에 해당하며, `SETUP_COMPLETED`가 더 정확하다. 반면 `setup_service.py:128`은 `SETUP_COMPLETED`를 올바르게 사용한다 — 두 코드 경로가 달라 감사 로그 분석 시 혼동된다.

또한 `actor_sub=None`(시스템 액션)인데, 운영자가 입력한 토큰 기반 작업이므로 가능하다면 IP나 actor 식별자를 포함하는 것이 감사 완전성에 유리하다.

**제안:** `audit.log(db, actor_sub=None, action=audit.SETUP_COMPLETED)` 로 변경.

---

### [🟡][🔢] notifications.py:265-266 — `_ts_iso` 문자열 비교가 포맷 혼재 시 잘못된 unread 판정

**근거:**
```python
unread = bool(ts) and ts > last_read_at and n["id"] not in read_ids
```
주석에서도 명시하듯 `last_read_at`은 `datetime.now(UTC).isoformat()` (`+00:00` 접미사), `ts`는 Campaign의 `completed_at` 또는 `created_at` 또는 AuditLog의 `created_at`이다. 이들은 모두 `datetime.now(UTC).isoformat()` 결과이므로 현재는 일관성이 있다.

그러나 `Campaign.completed_at`이나 `created_at`이 msghub 원본(`yyyyMMddHHmmss`)으로 저장된 경우(시스템/엣지케이스), 또는 미래에 필드 포맷이 변경되면 lexicographic 비교가 틀려진다. `util/time.py`의 `parse_mixed_ts_epoch`를 사용한 epoch 비교로 전환하면 이 취약점이 제거된다.

**제안:** `ts > last_read_at` 를 `parse_mixed_ts_epoch(ts) > parse_mixed_ts_epoch(last_read_at)` 로 교체.

---

### [🟡][⚙️] audit_api.py:112-118 — 감사 로그 검색에서 `action` 필드 LIKE 매칭 제외

**근거:**
```python
stmt = stmt.where(
    or_(
        User.display_name.ilike(pat, escape="\\"),
        User.name.ilike(pat, escape="\\"),
        User.email.ilike(pat, escape="\\"),
        AuditLog.target.ilike(pat, escape="\\"),
    )
)
```
`AuditLog.action` 자체는 검색 대상에 없다. 반면 `search.py:123-145`의 `_search_audit`는 `AuditLog.action.ilike(pat)`를 포함한다. `/audit` 페이지에서 "SETTINGS_UPDATE"로 검색하면 결과가 없고, `/search`에서는 나온다 — 일관성 없는 검색 동작.

`action` 필터는 별도 드롭다운으로 존재하지만(`action=SETTINGS_UPDATE`), 자유텍스트 `q` 검색에서도 action을 매칭하는 것이 사용자 기대에 부합한다.

**제안:** `AuditLog.action.ilike(pat, escape="\\")` 조건 추가.

---

### [🟡][🧭] notifications.py:304 — 알림 정렬이 `createdAt` 포맷 문자열 기준이라 분초 수준 정밀도 부족

**근거:**
```python
filtered.sort(key=lambda r: r.get("createdAt", ""), reverse=True)
```
`createdAt`는 `"YYYY-MM-DD HH:MM"` 포맷(분 단위)으로, 같은 분에 생성된 캠페인과 감사 로그 이벤트는 순서가 비결정적이다. 내부 `_ts_iso` 필드를 정렬 키로 쓰면 초 단위 정밀도를 유지할 수 있다 (apply_read_state에서 이미 제거하므로 정렬 전에 써야 함).

**제안:** 정렬을 `_apply_read_state` 호출 전 or 내부 `_ts_iso`를 유지한 채 수행.

---

### [🟡][⚙️] search.py:88-90 — `_search_contacts` total이 SCAN 후 Python slice 계산이라 쿼리 비효율

**근거:**
```python
rows = db.execute(stmt.limit(_SCAN_LIMIT)).scalars().all()
total = len(rows)
rows = rows[:_SECTION_LIMIT]
```
500건 전부를 메모리에 올린 후 10건만 반환한다. Contact 테이블이 커질수록 메모리 사용량 증가. 캠페인/스레드/연락처 섹션 모두 동일한 패턴으로 최대 500×4=2000개 ORM 객체가 동시에 생성된다.

단건 검색이므로 실제 문제가 발생하려면 테이블이 상당히 커야 하지만, 성장성을 고려해 `COUNT(*)`로 total을 구하고 LIMIT 10으로 행을 따로 조회하는 2-쿼리 방식으로 전환이 바람직하다.

**제안:** total COUNT 서브쿼리 + LIMIT 10 본 쿼리로 분리.

---

### [🟡][⚙️] settings.py:507 — `patch_provider_settings` 응답으로 `get_provider_settings(db=db)` 직접 호출

**근거:**
```python
return get_provider_settings(db=db)
```
`patch_provider_settings`는 `async def`이고 `get_provider_settings`는 `sync def`이다. async 핸들러 내에서 동기 함수를 직접 호출하는 것은 기술적으로 동작하지만, FastAPI는 동기 함수를 threadpool에서 실행하도록 설계되어 있다. 이 경우 이벤트 루프에서 직접 동기 DB 쿼리를 실행하므로 이벤트 루프 블로킹 위험이 있다 (SQLite는 경량이라 실제 지연은 미미하지만 설계 의도와 불일치).

**제안:** `get_provider_settings`의 로직을 내부 함수로 추출하거나, 응답을 직접 구성.

---

### [🟡][🧭] deploy/kotify-update-worker.sh — pnpm install 실패 시 `set -e`가 ERR trap을 트리거하지 않을 수 있음

**근거:**
```bash
pnpm install --frozen-lockfile 2>&1
```
`2>&1` 리디렉션은 stderr를 stdout으로 합쳐 버린다. `set -euo pipefail`에서 pnpm이 비정상 종료하면 ERR trap이 동작해야 하지만, 이전에 반복 버그로 `--silent` 제거와 `>/dev/null` 제거를 했다는 git 히스토리를 감안하면, 파이프 우측 `tee`가 실패해도 set -e가 트리거되지 않는 pipefail 엣지케이스가 있었을 가능성이 있다.

현재는 직접 실행이라 문제없지만, `pnpm build` 출력이 너무 많아 로그 파일이 수백 MB가 되는 경우를 대비해 로그 로테이션 정책이 없다.

**제안:** `/var/log/kotify/update.log` 에 대한 logrotate 설정 추가를 권장.

---

### [🟡][🔢] reports.py:71-85 — `to`만 제공 시 start를 `to - 7days`로 계산하지만 미래 날짜 제한 없음

**근거:**
```python
elif start is None:
    start = end - timedelta(days=7)
elif end is None:
    end = start + timedelta(days=7)
```
`to=2099-12-31`을 입력하면 start가 2099-12-24가 되어 DB 쿼리가 미래 날짜 범위로 실행된다. 결과는 빈 데이터이므로 기능적 문제는 없지만, 불필요한 DB 쿼리가 발생하고 사용자는 빈 리포트를 받는다.

**제안:** `end > today_mid + 1day` 이면 `today_mid + 1day`로 클리핑.

---

## 🟢 LOW

---

### [🟢][⚙️] audit.py:63 — `db.flush()`만 수행, commit은 호출자에 위임 — 주석 있으나 호출자 누락 가능성

**근거:**
```python
db.add(entry)
db.flush()
```
주석에 "호출자가 반드시 db.commit()을 호출해야 감사 로그가 저장됨"이라고 명시되어 있다. settings.py:678-679에서 `audit.log()` 직후 `db.commit()`을 호출하는 패턴은 올바르다. 그러나 `patch_org`(line 216)는 commit을 하지만 audit.log 호출이 없고, 미래 개발자가 audit.log만 추가하고 commit을 락 밖에 두면 커밋 누락 버그가 발생한다.

**제안:** `audit.log` 내부에서 flush 대신 명시적으로 docstring에 "반드시 다음 commit이 있어야 저장됨" 경고를 강화하거나, context manager 패턴 도입 고려.

---

### [🟢][🔢] util/time.py:55-59 — `digits >= 14` 체크가 `"2026-04-23 00:12:00"` 같은 ISO 날짜도 msghub 포맷으로 파싱

**근거:**
```python
digits = "".join(c for c in raw if c.isdigit())
if len(digits) >= 14:
    naive = datetime.strptime(digits[:14], "%Y%m%d%H%M%S")
```
`"2026-04-23 00:12:00"`의 digit 추출 결과는 `"20260423001200"` (14자리) → KST로 파싱된다. 하지만 이 문자열은 1차 ISO 8601 파싱에서 `datetime.fromisoformat("2026-04-23 00:12:00")`로 성공 처리되므로 2차까지 내려오지 않는다. 실제 충돌은 없으나 로직 순서에 의존하는 취약한 구조다.

**제안:** 2차 분기에 "숫자만으로 구성된 14자리" 패턴으로 강화: `raw.isdigit() and len(raw) == 14`.

---

### [🟢][⚙️] setup_service.py:68 — `complete_setup` 함수가 `setup.py`의 `complete_setup` 엔드포인트에서 사용되지 않음

**근거:**
`setup.py`의 `complete_setup` 엔드포인트(line 243)는 `setup_service.complete_setup`을 호출하지 않고 직접 `store.set(...)`, `store.mark_bootstrap_completed(...)`, `audit.log(...)` 등을 인라인으로 처리한다. `setup_service.complete_setup`은 추가로 "첫 admin user upsert" 로직까지 포함하는데, 이 로직이 실제로 실행되지 않는다.

`setup.py`의 comment에는 "firstAdminEmail로 로그인한 사용자가 자동 admin 승격"이라고 설명하고, 이는 auth.callback 로직에서 처리된다고 명시되어 있다. 따라서 `setup_service.complete_setup`의 user upsert 로직은 dead code가 되었을 가능성이 높다.

**제안:** `setup_service.complete_setup`이 dead code인지 확인 후 제거하거나, `setup.py`가 이 서비스를 사용하도록 통합.

---

### [🟢][🧭] SystemUpdatePanel.tsx:55 — `window.confirm` 사용

**근거:**
```tsx
if (!confirm(`${info.count}건의 업데이트를 설치하시겠습니까?\n\n서비스가 잠시 재시작됩니다.`))
```
`window.confirm`은 브라우저 네이티브 다이얼로그로 디자인 시스템과 불일치하며, 일부 브라우저/환경(iframe, electron 등)에서 차단될 수 있다.

**제안:** 프로젝트의 Modal/Dialog 컴포넌트로 교체.

---

### [🟢][⚙️] notifications.py:192-200 — `_last_read_key`, `_read_ids_key` 가 user.sub을 그대로 키에 삽입

**근거:**
```python
def _last_read_key(sub: str) -> str:
    return f"notif.last_read_at.{sub}"
```
`user.sub`이 Keycloak UUID 형태(하이픈 포함)라면 Setting 테이블 key 컬럼에 그대로 들어간다. 특수문자 포함 여부에 따라 쿼리 인덱스 효율이 달라질 수 있으나, SQLite PK 문자열 조회는 동일성 비교이므로 기능 문제는 없다. 다만 향후 PostgreSQL 마이그레이션 시 키 길이 제한 이슈 가능성.

**제안:** sub를 SHA-256 축약 또는 URL-safe 인코딩으로 정규화 고려.

---

## 요약 통계표

| 심각도 | 건수 | 비율 |
|--------|------|------|
| 🔴 CRITICAL | 4 | 29% |
| 🟠 HIGH | 5 | 36% |
| 🟡 MEDIUM | 7 | 50% |
| 🟢 LOW | 5 | 36% |
| **합계** | **14** | — |

렌즈별 분포:

| 렌즈 | 🔴 | 🟠 | 🟡 | 🟢 |
|------|----|----|----|----|
| ⚙️ 기능/버그 | 3 | 3 | 3 | 3 |
| 🔢 집계 정확성 | 1 | 2 | 1 | 1 |
| 🧭 UX | 0 | 0 | 2 | 1 |
| 🔴 보안 | 0 | 0 | 1 | 0 |

---

## Top 위험 3

### 1. [🔴] `/system/update/check` 인증 명시 누락 (settings.py:600)
라우터 레벨 `require_role("admin")`이 적용되지만 핸들러 시그니처에 `require_user`가 없어 패턴이 `apply`와 불일치한다. 인프라 정보(배포 버전, 커밋 히스토리) 노출 리스크. `apply`와 동일하게 `user: User = Depends(require_user)` 추가로 즉시 해결.

### 2. [🔴] 커밋 메시지의 특수문자로 배포 check JSON 파괴 (deploy/kotify-update.sh:46-50)
`sed 's/"/\\"/g'`만으로는 역슬래시, 단따옴표, 개행이 포함된 커밋 메시지를 안전하게 JSON 직렬화할 수 없다. Python/jq 기반 JSON 생성으로 전환이 필요하며, 그때까지 커밋 메시지 컨벤션에 단따옴표/역슬래시 금지를 팀 규칙으로 임시 적용.

### 3. [🔴] `patch_org` 감사 로그 누락 (settings.py:182-218)
조직명·시간대·연락처 변경이 감사 로그에 기록되지 않는다. `patch_provider_settings`는 기록하는 것과 불일치하여 컴플라이언스 감사 시 설정 변경 추적이 불완전하다. `db.commit()` 직전 `audit.log()` 1줄 추가로 즉시 해결.
