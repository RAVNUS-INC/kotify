# Phase 3 코드 리뷰 — 데이터 도메인 (연락처·그룹·발신번호)

대상: `app/routes/contacts.py`, `app/routes/groups.py`, `app/routes/numbers.py`,
`app/services/contacts.py`, `app/services/groups.py`, `app/services/csv_import.py`,
`app/util/phone.py`, `app/util/csv_safe.py`, `app/util/text.py`

---

## 발견사항 (심각도 내림차순)

---

### 🔴 CRITICAL

---

**[🔴][🔢] app/services/csv_import.py:127-134 — import_contacts가 행마다 SELECT를 실행하는 N+1 쿼리**

```
근거:
  127: for row in valid_rows:
  132:     existing = db.execute(
  133:         select(Contact).where(Contact.phone == phone)
  134:     ).scalar_one_or_none()
```
valid_rows 길이가 N이면 최대 N번의 SELECT가 루프 안에서 발행된다.
CSV 1000행 import 시 1000 SELECT + 최대 1000 INSERT = 2000 쿼리.
SQLite에서 1000행 import 기준 체감 지연이 수 초 이상 발생할 수 있으며,
HTTP 타임아웃 위험이 있다.

재현 조건: 새 phone이 각기 다른 1000행 CSV를 mode="skip"으로 import.

제안:
  import 시작 전 valid_rows에서 phone 목록을 한 번에 추출하여 IN 쿼리로
  기존 연락처를 일괄 조회한 뒤 dict로 캐싱. 루프 안에서는 dict.get()만
  사용한다.
  ```python
  phones = [r["phone"] for r in valid_rows if r.get("phone")]
  existing_map: dict[str, Contact] = {}
  if phones:
      rows = db.execute(select(Contact).where(Contact.phone.in_(phones))).scalars()
      existing_map = {c.phone: c for c in rows}
  for row in valid_rows:
      existing = existing_map.get(row.get("phone"))
      ...
  ```

---

**[🔴][⚙️] app/routes/contacts.py:364-370 — ContactCreateBody 전화번호 검증 우회: 임의 문자열이 DB에 저장됨**

```
근거:
  364: @field_validator("phone")
  366: def _normalize_phone(cls, v: Optional[str]) -> Optional[str]:
  368:     if v is None:
  369:         return None
  370:     digits = "".join(c for c in v if c.isdigit())  # ← 숫자만 추출
  371:     return digits or None
```
`util/phone.py`의 `normalize_phone`을 호출하지 않고 단순히 숫자만 추출한다.
입력 `"02-1234-5678"` → `"0212345678"` (유선번호 10자리)이 검증 없이 저장된다.
`"0001234567890000"` 같은 길이 제한 없는 숫자열도 DB에 그대로 들어간다.

재현 조건: `POST /contacts` body `{"name":"테스트","phone":"02-1234-5678"}`
→ 유선번호가 contact.phone에 저장되고, 이후 발송 시 정규화 불일치 발생.

제안:
  `normalize_phone(v)`를 호출하고, 결과가 None이면
  `raise ValueError("올바른 한국 휴대폰 번호 형식이 아닙니다")`를 반환한다.
  PATCH의 `_normalize_phone_opt` 동일하게 수정.

---

**[🔴][⚙️] app/routes/groups.py:504-508 — bulk-add 전화번호 정규화가 숫자 추출만 함 (+82/국제 번호 불일치)**

```
근거:
  504: for p in body.phones:
  505:     digits = "".join(c for c in p if c.isdigit())
```
`+82-10-1234-5678` 입력 시 `digits = "821012345678"` (12자리, 선두 82).
`util/phone.py`의 `normalize_phone`이라면 `"01012345678"`로 정규화하지만,
여기서는 `"821012345678"`이 그대로 DB 조회 키로 사용된다.
Contact.phone은 항상 `"01012345678"` 형태이므로 `phone_to_contact` dict에서
매칭이 실패해 기존 연락처를 찾지 못하고 중복 연락처가 auto-create된다.

재현 조건:
  Contact(phone="01012345678") 존재 상태에서
  `POST /groups/{gid}/members/bulk-add` body `{"phones":["+82-10-1234-5678"]}`
  → `added_existing=0, created_new=1` (중복 연락처 생성).

제안:
  `digits` 추출 대신 `normalize_phone(p)`를 호출하고,
  None 반환(유효하지 않은 번호)은 invalid 카운트에 포함시켜 응답에 반영한다.

---

**[🔴][🧹] app/util/csv_safe.py:17-21 — import(읽기) 경로에 CSV injection 방어 없음**

```
근거:
  사용처 주석: "app/routes/audit_api.py, app/routes/reports.py"
  csv_import.parse_csv()에서는 safe_csv_cell을 호출하지 않는다.
```
export(쓰기)는 `safe_csv_cell`로 방어하지만, import(읽기)는 방어 없다.
CSV 파일을 import한 뒤 그 데이터를 다시 export하면 injection payload가
DB에 저장된 채로 export CSV에 통과된다.

예: 연락처 name="=HYPERLINK(\"http://evil.com\",\"click\")"
→ import 시 DB에 그대로 저장 → export 시 safe_csv_cell이 '를 붙이므로
  export는 방어되지만, 다른 경로(audit CSV의 detail 필드 등)에서 해당 이름이
  safe_csv_cell 없이 write된다면 injection 가능.

실질적 위험: 현재 export_contacts는 safe_csv_cell로 방어되어 있어
직접적 Excel 실행은 차단된다. 그러나 audit_api의 detail 필드, reports의
자유 텍스트 필드는 safe_csv_cell을 적용하지 않는 경우가 있을 수 있어
**import 단계에서의 화이트리스트 검증이 근본적 방어**다.

제안:
  parse_csv()에서 name, notes 등 자유 텍스트 필드에
  `safe_csv_cell` 적용 또는 formula prefix 탐지 후 경고 추가.
  DB 저장 전 검증이 export 의존 방어보다 안전하다.

---

### 🟠 HIGH

---

**[🟠][⚙️] app/services/csv_import.py:166-167 — import 부분 실패 시 일부만 저장되고 롤백 없음**

```
근거:
  128: for row in valid_rows:
  129:     try:
  166:     except Exception as exc:
  167:         result["errors"].append(str(exc))
```
각 행의 예외를 개별 catch하고 계속 진행한다. 100행 import 중 50번째 행에서
DB 제약 위반이 발생해도 1~49행은 이미 flush되어 있다.
라우트에서 루프 후 `db.commit()`을 호출하므로 1~49행이 커밋된다.
사용자는 "errors: [...]" 응답을 보지만 일부 데이터는 이미 DB에 들어간 상태.

재현 조건: 100행 CSV에서 70번째 행이 DB 제약 위반 유발
→ 1~69행 커밋, 70번째 에러, 71~100행 계속 처리.

제안:
  트랜잭션 경계를 명확히 한다. 옵션 A: 모두 성공하거나 모두 rollback
  (atomic import). 옵션 B: 행 단위 savepoint를 이용해 각 행을 독립적으로
  커밋/롤백 (PostgreSQL 지원, SQLite 제한적). 최소한 에러 행 발생 시
  해당 행의 flush를 `db.rollback()`하고 나머지를 계속하는 것을 명확히 문서화.

---

**[🟠][⚙️] app/routes/contacts.py:393-398 — ContactUpdateBody._normalize_phone_opt가 빈 문자열을 그대로 반환**

```
근거:
  394: def _normalize_phone_opt(cls, v: Optional[str]) -> Optional[str]:
  396:     if v is None:
  397:         return None
  398:     digits = "".join(c for c in v if c.isdigit())
  399:     return digits  # ← "" (빈 문자열) 반환 가능
```
`PATCH /contacts/{id} {"phone": ""}` 전송 시
`digits = ""`이고, `return digits`는 `""`를 반환.
`exclude_none=True`이므로 `""` (빈 문자열)은 exclude되지 않아
`update_contact(db, id, phone="")`가 호출되고 phone이 `""`로 덮어쓰인다.
이후 발송 시 `to_number = ""`로 발송 시도.

재현 조건: `PATCH /contacts/1` body `{"phone": ""}` → DB의 phone이 `""`.

제안:
  `return digits or None` 로 수정. CreateBody의 `_normalize_phone`은
  이미 `or None`이 있지만 UpdateBody는 누락되어 있다.

---

**[🟠][⚙️] app/routes/contacts.py:200-219 — groupId 필터가 DB가 아닌 Python에서 이루어져 1000건 상한 영향**

```
근거:
  201: contacts, svc_total = svc_list_contacts(..., per_page=_CONTACTS_PAGE_SIZE)
  212: if gid_int is not None:
  213:     member_ids = set(...)
  219:     contacts = [c for c in contacts if c.id in member_ids]
```
서비스에서 1000건을 먼저 로드한 뒤 Python에서 그룹 필터링한다.
총 연락처가 1001명이고 그룹 멤버가 1001번째 연락처만 포함하면,
`svc_list_contacts`가 1~1000만 반환하므로 그룹 멤버가 응답에서 누락된다.
`hasMore`는 True가 되지만 사용자는 그룹 멤버를 볼 수 없다.

재현 조건: 총 1001명의 연락처, 마지막으로 생성된 연락처만 그룹에 소속
(name 기준 정렬에서 1001번째) → `GET /contacts?groupId=g-1` → 빈 결과.

제안:
  groupId가 있을 때는 서비스 레이어 또는 DB 쿼리에서 JOIN/subquery로
  처리해 올바른 총수를 보장한다.

---

**[🟠][🔢] app/services/groups.py:299-317 — expand_groups_to_contacts가 비활성(active=0) 연락처를 포함해 발송**

```
근거:
  312: contacts = list(
  313:     db.execute(
  314:         select(Contact).where(Contact.id.in_(member_ids_q))
  315:     ).scalars().all()
  316: )
```
`Contact.active` 필터가 없다. 비활성화된 연락처도 발송 대상에 포함된다.
SPEC §6.3: "잘못된 번호 1개라도 있으면 발송 차단"과 충돌 가능.

재현 조건:
  그룹에 active=0인 연락처 포함 → 캠페인 그룹 발송 시 비활성 연락처에 발송.

제안:
  `.where(Contact.id.in_(member_ids_q), Contact.active == 1)` 추가.
  또는 호출부에서 결과를 active 기준으로 필터링.

---

**[🟠][🧹] app/routes/contacts.py:237-242 — hasMore 계산이 groupId 필터 이후 총수가 아닌 서비스 총수 기준**

```
근거:
  237: return {
  241:     "hasMore": svc_total > _CONTACTS_PAGE_SIZE,
  242: }
```
groupId가 있을 때 `svc_total`은 그룹 필터 전 전체 연락처 수(검색 반영)다.
그룹 멤버가 500명이고 전체 연락처가 1200명이면 `hasMore=True`가 반환되지만,
실제로 그룹 내 500명은 전부 응답에 들어가 있다. 클라이언트가 불필요한
추가 페이지 요청을 보내거나 "더 보기" UI를 잘못 표시한다.

제안:
  groupId 적용 후에는 `hasMore = len(rows) >= _CONTACTS_PAGE_SIZE`로 수정.

---

### 🟡 MEDIUM

---

**[🟡][⚙️] app/util/phone.py:43 — 선두 82 처리 조건이 12자리 이상으로 제한해 11자리 국제 번호 누락**

```
근거:
  43: elif cleaned.startswith("82") and len(cleaned) >= 12:
```
`"821012345678"`은 12자리 → 정상 처리 (`"01012345678"`).
`"8210123456"` (10자리: 82 + 010 + 7자리 구형)은 조건 미달 → None 반환.
SPEC §6 docstring에서 `8210-1234-5678` 형식을 허용 예시로 명시하지만
`82`+`01`+7자리 조합은 11자리이므로 조건에서 탈락.

재현 조건: `normalize_phone("8201-1234-567")` → 하이픈 제거 후 `"820112345
67"` (11자리) → None. 실제 구형 011 번호의 국제 표기.

제안:
  `len(cleaned) >= 11`로 완화하거나 별도 패턴으로 처리.
  test_phone.py의 `test_82_prefix_with_hyphen`은 12자리만 커버.

---

**[🟡][⚙️] app/util/phone.py:25 — 010-1234-56789 (9자리 subscriber) 통과 가능성**

```
근거:
  24: _PHONE_PATTERN = re.compile(r"^01[016789]\d{7,8}$")
```
패턴이 `01X` + 7~8자리를 허용한다. `010` + 8자리 = 11자리(현행 표준).
`011` + 7자리 = 10자리(구형). 이 두 케이스는 정상이다.
그러나 `010` + 7자리 = 10자리(`010-123-4567` 형태)도 패턴에 통과한다.
이 번호는 현실에서 할당되지 않지만, 패턴은 이를 유효로 처리한다.

재현 조건: `normalize_phone("010-123-4567")` → `"0101234567"` (10자리) → 통과.

제안:
  010 prefix는 8자리 구독자 번호만 허용하도록
  `^(010\d{8}|01[16789]\d{7,8})$`로 정밀화하거나 테스트에서 명시.

---

**[🟡][🧭] app/services/csv_import.py:105-169 — import 완료 응답에 실패한 행 번호/원인 미포함**

```
근거:
  167:     result["errors"].append(str(exc))
```
`errors`는 예외 메시지 문자열 목록만 포함한다. 어느 행에서 발생했는지
(row_number), 어떤 값이 문제인지(raw_data)가 없다.
`parse_csv`는 `{row_number, raw_data, error}` 구조로 `invalid_rows`를
반환하지만, `import_contacts`의 errors는 문자열만 담아 응답에서
구체적인 디버그 정보가 손실된다.

제안:
  `errors`를 `{row_index, reason}` dict 구조로 변경하거나,
  `invalid_rows`를 직접 라우트 응답의 `invalidPreview`에 포함
  (현재 포함 중이나 import 단계 에러는 누락).

---

**[🟡][⚙️] app/routes/contacts.py:580-592 — export 엔드포인트가 인증/CSRF 없이 접근 가능**

```
근거:
  580: @router.get("/contacts/export.csv")
  581: def export_contacts_route(
  582:     db: Session = Depends(get_db),
  583: ) -> Response:
```
router 레벨에서 `require_user`가 적용되어 있어 인증은 된다.
그러나 GET이므로 CSRF 보호가 없다. CSRF 공격에서 GET은 통상 안전하지만
전체 연락처 DB를 CSV로 덤프하는 엔드포인트는 민감 데이터 노출이 크다.

재현 조건: 인증된 세션에서 `<img src="/api/contacts/export.csv">` 삽입
→ 브라우저가 자동 GET 요청, CSV를 내려받지 않아도 서버가 전체 조회 실행.

제안:
  `export_contacts_route` 함수 시그니처에 `user: User = Depends(require_user)`를
  명시적으로 추가하고, 감사 로그에 export 이벤트를 기록한다.
  현재 audit.log 호출이 없어 누가 export했는지 추적 불가.

---

**[🟡][🔢] app/services/csv_import.py:37 / 189 — export_contacts가 전체 데이터를 메모리에 로드**

```
근거:
  189: contacts = list(db.execute(q).scalars().all())
```
`contact_ids=None`일 때 전체 연락처를 한 번에 메모리에 로드한 뒤 CSV 생성.
10만 연락처 시 수십 MB 메모리 사용 및 응답 지연 발생.

제안:
  `yield_per()`를 이용한 서버사이드 스트리밍, 또는 `StreamingResponse`로
  청크 단위 CSV 쓰기를 구현한다.

---

**[🟡][🧭] app/routes/contacts.py:519-577 — CSV import에 파일 크기 검증 없음**

```
근거:
  543: raw = await file.read()
```
업로드 크기 제한 없이 전체를 메모리에 읽는다. 100MB 파일 업로드 시
서버 메모리 소진 가능.

제안:
  `file.size` 또는 read loop를 이용해 최대 크기(예: 10MB)를 강제하고
  초과 시 413 응답 반환.

---

**[🟡][⚙️] app/routes/numbers.py:81-97 — dailyUsage 계산이 Campaign.created_at 기준 (발송 완료 시각 아님)**

```
근거:
  89: Campaign.created_at >= day_start,
  90: Campaign.created_at < day_end,
  91: func.coalesce(func.sum(Campaign.total_count), 0)
```
`total_count`는 "예약된 수신자 수"이지 실제 발송 완료 수가 아니다.
발송이 진행 중이거나 실패한 경우에도 total_count가 dailyUsage에 합산된다.
또한 created_at 기준이므로 전날 생성되어 오늘 발송 완료된 캠페인은 누락.

제안:
  의미를 "오늘 생성된 캠페인의 예약 건수"로 명확히 문서화하거나,
  Message 테이블의 complete_time 기준 집계로 변경.

---

**[🟡][🔢] app/services/groups.py:99-134 — add_members가 contact_id 유효성을 검증하지 않음**

```
근거:
  120: for cid in contact_ids:
  121:     if cid in existing:
  122:         continue
  123:     member = ContactGroupMember(...)
  124:     db.add(member)
```
존재하지 않는 contact_id를 전달해도 DB에 INSERT를 시도한다.
FK 제약(ondelete="CASCADE")이 있으므로 SQLite에서 FK enforcement가
활성화된 경우 IntegrityError가 발생하지만, SQLite 기본 설정에서는
FK enforcement가 비활성이므로 고아 멤버십 레코드가 생성될 수 있다.

재현 조건:
  SQLite에서 `PRAGMA foreign_keys = OFF`(기본) 상태에서
  `add_members(db, group_id=1, contact_ids=[99999])` → 고아 레코드 삽입.

제안:
  삽입 전 `Contact.id.in_(contact_ids)` 로 유효한 ID만 필터링하거나,
  DB 레벨에서 `PRAGMA foreign_keys = ON`을 항상 활성화한다.

---

### 🟢 LOW

---

**[🟢][🧹] app/util/csv_safe.py:14 — `;` 를 formula trigger로 처리하나 실제 CSV에서는 셀 구분자**

```
근거:
  14: _FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n", ";")
```
`;`는 일부 로케일(독일어 LibreOffice)에서 수식 인수 구분자로 쓰이지만,
셀 값의 첫 문자가 `;`인 경우는 formula injection이 아닌 일반 텍스트다.
`;메모` 같은 값에 `'` prefix가 붙어 Excel에서 `';메모`로 표시된다.

제안:
  현행 방어는 false positive를 낼 뿐 안전에 유리하므로 그대로 둬도 무방.
  단, `\n`과 `\r`은 CSV writer가 이미 quoting으로 처리하므로 중복 방어다.
  주석으로 의도를 명시하면 충분.

---

**[🟢][🧹] app/services/contacts.py:12 / app/services/groups.py:12 / app/routes/numbers.py:174 — _now_iso()가 세 곳에서 중복 정의**

```
근거:
  contacts.py:12: def _now_iso() -> str: ...
  groups.py:12:   def _now_iso() -> str: ...
  numbers.py:174: def _now_iso() -> str: ...
```
동일 구현이 세 파일에 각각 존재한다. DRY 위반이지만 동작은 동일하다.

제안:
  `app/util/time.py`가 이미 존재하는 것으로 보이므로 해당 파일에 통합.
  (`app/util/time.py`가 현재 untracked 상태 — git status 확인됨)

---

**[🟢][🧭] app/services/groups.py:99-104 — bulk_add_by_phones 주석의 auto_create 기본값이 실제와 상이**

```
근거:
  141: auto_create: bool = True,  # 서비스 레이어 기본값 True
  GroupMembersBulkAddBody.autoCreate = True  # 라우트 레이어도 True
```
문서 불일치 아님. 그러나 auto_create=True 기본값은 예상치 못한 연락처
자동 생성을 유발할 수 있다. 잘못된 번호가 포함된 배치에서 새 연락처가
조용히 생성되는 것은 운영상 위험.

제안:
  API 문서나 응답에 `created_new` 카운트를 명확히 표시하고 있으므로 현행
  유지는 가능하나, 기본값을 `False`로 변경하고 명시적 opt-in을 권장.

---

**[🟢][🔢] tests/test_phone.py — 테스트가 누락하는 케이스**

누락된 케이스:
1. `normalize_phone(None)` — 코드는 처리하지만 테스트 없음.
2. `"010-1234-567"` (7자리 subscriber) — 10자리 → 현재 패턴에서 통과하지만
   테스트 없음 (010 + 7자리는 현실에서 미할당).
3. `"+82-10-123-4567"` (10자리 010 + 7자리) → 정규화 후 `"0101234567"` 통과 여부.
4. `"8201-1234-567"` (11자리 국제 82 + 011 구형) — 조건 `>= 12` 미달로 None.
5. `" "` (공백만) → `None` 반환 여부.
6. `"050-1234-5678"` 인터넷 전화 → None 반환이 맞는지.

---

**[🟢][🔢] tests/test_csv_import.py — formula injection 테스트 없음**

export 후 safe_csv_cell 적용 여부를 검증하는 테스트가 없다.
`name="=HYPERLINK(...)"` 연락처를 생성 후 export_contacts를 실행하고
출력 CSV에 `'=`로 시작하는지 확인하는 케이스가 필요하다.

---

## 요약 통계표

| 심각도 | 건수 | 영역 |
|--------|------|------|
| 🔴 CRITICAL | 4 | N+1 import 쿼리, POST 전화번호 검증 우회, bulk-add 국제번호 불일치, import-only CSV injection |
| 🟠 HIGH | 6 | import 부분 롤백 없음, PATCH 빈 phone 저장, groupId Python 필터 1000건 상한, expand 비활성 포함, hasMore 오산, — |
| 🟡 MEDIUM | 7 | 82 prefix 11자리 누락, 010+7자리 패턴, import 에러 위치 누락, export 감사로그 없음, export 메모리, CSV 크기 무제한, dailyUsage 의미 불명확, add_members FK 미검증 |
| 🟢 LOW | 4 | csv_safe `;` false positive, _now_iso 중복, auto_create 기본값, 테스트 누락 |
| **합계** | **21** | |

---

## Top 위험 3

### 1. import_contacts N+1 쿼리 (🔴 CRITICAL, 🔢 알고리즘)
`csv_import.import_contacts`가 행마다 `SELECT * FROM contacts WHERE phone = ?`를
실행한다. 1000행 CSV 처리 시 최대 2000 쿼리 발행. SQLite 단일 스레드 환경에서
HTTP 타임아웃 및 서비스 응답 불능이 발생할 수 있다. 수정 비용이 낮고
(IN 쿼리로 일괄 조회) 효과가 즉각적이다.

### 2. 전화번호 검증 이중 표준 (🔴 CRITICAL, ⚙️ 기능)
`POST /contacts`와 `bulk-add`는 숫자 추출만 하고 `util/phone.normalize_phone`을
호출하지 않아 유선번호·국제 형식·길이 제한 없는 번호열이 DB에 저장된다.
CSV import는 올바르게 `normalize_phone`을 사용한다. 동일 시스템에서 경로에 따라
다른 저장값이 생겨 이후 중복 검사·발송 모두 불일치를 유발한다.

### 3. import 부분 커밋 (🟠 HIGH, ⚙️ 기능)
import 도중 예외 발생 시 이전 행은 커밋, 이후 행은 rollback되어 데이터가
부분적으로만 저장된다. 재시도 시 "skip" 모드에서는 이미 저장된 행을 건너뛰므로
최종 결과가 완전하게 보이지만, "update" 또는 "create" 모드에서는 중복 혹은
누락 레코드가 생겨 데이터 정합성이 깨진다.
