# Phase 1 — 아키텍처 & 보안(횡단 관심사) 코드 리뷰

리뷰 대상: 인증/인가, 암호화/비밀값, CSRF, 레이어 경계, 데이터 모델, 에러/로깅
범위: `app/main.py`, `app/config.py`, `app/db.py`, `app/models.py`, `app/auth/*`, `app/security/*`, `web/middleware.ts`, `web/lib/{api,auth}.ts`, `web/app/(app)/layout.tsx` + 횡단 검증을 위한 `app/routes/{auth,setup,webhook,settings}.py`, `app/services/{audit,setup_service}.py`, `app/msghub/auth.py`, `alembic/versions/*`

전반 평가: 인증/인가 설계는 견고하다. 2-tier guard, RBAC 의존성, Fernet 암호화, CSRF 타이밍 안전 비교, OIDC PKCE, 세션 고정 방어(`session.clear()`), 시크릿 쓰기 전용 처리, 마이그레이션-모델 일치 등 핵심 통제가 일관되게 적용돼 있다. CRITICAL은 없으며, HIGH 2건은 모두 "구성 의존" 또는 "PII 로그"로 운영 절차/로깅 정책으로 막을 수 있는 부류다.

---

## 🟠 HIGH

```
[🟠][⚙️ 기능] app/routes/webhook.py:68-73 + app/routes/setup.py:309-322 — setup wizard가 webhook_token을 설정하지 않아, 운영 배포 직후 모든 msghub 웹훅(발송 리포트/MO)이 401로 거부됨
  근거: setup/complete의 payload(309-322줄)에는 keycloak.*, msghub.api_key/api_pwd/env/brand_id/chatbot_id,
        app.public_url, session.secret, setup.first_admin_email/pending_first_admin만 저장된다.
        msghub.webhook_token은 포함되지 않는다. 반면 _verify_token(webhook.py:68-73)은
        토큰 미설정 + dev_mode=False(운영)일 때 무조건 거부한다. 따라서 wizard만 거친 신규 운영 설치는
        webhook_token이 비어 있고, msghub가 보내는 발송 결과 리포트와 고객 MO 답장이 전부 401로 버려진다.
        리포트가 들어오지 않으면 Message.status가 영구 PENDING으로 남고, Campaign 완료/실패 집계
        (report.py:244-247의 COMPLETED/PARTIAL_FAILED 전이)와 비용 집계가 갱신되지 않는다.
        webhook_token은 오직 settings PATCH(settings.py:404 msghubWebhookToken)로만 사후 설정 가능하다.
  재현: fresh install → wizard 완료 → msghub 콘솔에 (아직 토큰 없는) URL 등록 → 발송 →
        리포트 웹훅이 401 → 발송 상태가 영원히 PENDING.
  제안: setup/complete payload에 webhook_token을 자동 생성(secrets.token_hex(16))하여 저장하고,
        응답 next 단계 또는 /settings/webhooks 화면에서 완성된 URL을 운영자에게 노출하라.
        최소한 wizard 완료 응답에 "webhook_token 미설정" 경고를 추가해 사후 설정을 강제하라.
```

```
[🟠][🔢 알고리즘/보안] app/routes/webhook.py:121 — SMS fallback 실패 로그에 수신자 전화번호 평문 기록 (PII 유출)
  근거: log.exception("SMS fallback 발송 실패: msg_id=%s, phone=%s", msg.id, msg.to_number) 가
        고객 전화번호 원문을 로그에 남긴다. crypto.py 헤더 주석은 "절대 금지: 키/시크릿 로그 노출"을
        명시하나 PII(전화번호)는 통제 대상에서 빠져 있다. 본 시스템은 대량 발송 시스템으로 수신자 번호가
        핵심 개인정보(PIPA 적용 대상)이며, 발송 실패는 정상 운영 중에도 빈번해 로그에 다량의 번호가 축적된다.
        uvicorn 로그가 systemd journald/파일로 흘러 로그 접근 권한자에게 전화번호가 노출된다.
  제안: 전화번호를 마스킹(예: 010****1234)하거나 msg_id만 남겨라. report.py:185의 cli_key 로그도
        cli_key가 전화번호 파생 키일 수 있으므로 동일 검토. 프로젝트 전역 PII 로깅 정책 수립 권장.
```

---

## 🟡 MEDIUM

```
[🟡][⚙️ 기능/보안] app/auth/oidc.py:34-48 + app/routes/auth.py:108-124 — OIDC 콜백이 userinfo 폴백 시 ID 토큰 검증 실패를 조용히 흡수, claims가 비어도 진행 가능 경로 존재
  근거: callback(auth.py:113-116)은 authorize_access_token 실패를 광범위 except로 잡아 로그인 페이지로
        리다이렉트만 한다(에러 로그 없음). 이후 119줄 claims = token.get("userinfo") or token.get("id_token") or {}
        에서 token.get("id_token")는 보통 "검증된 dict"가 아니라 raw JWT 문자열일 수 있어, 그 경우
        claims가 문자열이 되고 parse_user_from_claims(dict 가정)에서 .get 호출이 깨지거나 빈 값으로 흐른다.
        userinfo 폴백(121-124)도 실패를 흡수해 claims={} → sub 없음 → no_sub 리다이렉트로만 끝난다.
        Authlib authorize_access_token는 nonce/state/서명을 내부 검증하므로 인증 우회 위험은 낮지만,
        실패 원인이 전혀 로깅되지 않아 운영 중 로그인 장애의 근본 원인 진단이 불가능하다(B904 예외체인 끊김의
        진단적 영향).
  제안: authorize_access_token except에 logger.warning(exc_info=True) 추가(시크릿 비노출 주의).
        token.get("id_token") 분기는 dict 여부를 isinstance로 확인 후 사용. claims 타입 가드 추가.
```

```
[🟡][🧹 코드품질/보안] app/security/csrf.py:53-60 — 운영에서 SMS_DISABLE_CSRF=1이 설정돼도 차단하지 않고 "로그 후 계속 진행" (fail-open 성향)
  근거: dev_mode=False인데 SMS_DISABLE_CSRF=1이면 에러 로그만 남기고 일반 검증 경로로 흐른다(우회는 안 됨).
        의도(우회 무력화)는 맞으나, 환경변수 자체를 운영 이미지에서 읽을 수 있다는 것은 위험 신호다.
        os.getenv 호출이 매 요청 발생하며, 실수로 dev_mode까지 켜지면 즉시 전역 CSRF 무력화로 이어진다
        (두 플래그가 동일 환경에서 토글되는 단일 장애점). 테스트 전용 토글을 런타임 코드에 두는 것 자체가 리스크.
  제안: 운영 빌드에서 SMS_DISABLE_CSRF 자체를 무시(상수 False)하거나, pytest conftest fixture로만
        주입하도록 분리. 운영 코드 경로에서 환경변수 검사를 제거하면 단일 장애점이 사라진다.
```

```
[🟡][⚙️ 기능/보안] app/routes/setup.py:134-219 — test-keycloak / test-msghub 가 setup 토큰 검증 없이 호출 가능 (require_setup_mode + CSRF만), SSRF·자격증명 오라클 노출
  근거: 두 엔드포인트는 dependencies=[require_setup_mode, verify_csrf]만 갖는다. verify_token으로 setup
        토큰을 검증하지 않으므로, bootstrap 미완료 상태에서 CSRF 토큰만 얻으면(=GET /setup/status로 누구나 발급)
        누구나 호출 가능하다. test-keycloak은 _validate_keycloak_issuer로 사설망 IP는 막지만 임의 외부
        http(s) host로 GET을 보내는 blind SSRF/포트스캔 프록시로 악용될 수 있고(localhost 명시 허용 예외도 존재),
        연결 실패 메시지에 f"연결 실패: {exc}"로 내부 예외 텍스트를 그대로 반환(setup.py:153,207,211)해
        대상 인프라 정보를 흘린다. test-msghub는 입력 자격증명의 유효성을 응답으로 알려주는 오라클이 된다.
        실 위험은 "bootstrap 완료 전" 창에 한정되고 require_setup_mode가 완료 후 404를 보장하므로 MEDIUM.
  제안: test-* 엔드포인트에도 setup 토큰(세션 setup_token_verified 또는 body token) 검증을 선행시켜라.
        exc 원문 대신 일반화된 메시지를 반환(complete_setup의 keycloak_unreachable도 동일)하라.
```

```
[🟡][🧹 코드품질] app/services/setup_service.py:68-137 complete_setup() — 사용되지 않는 죽은 코드 (라우트는 인라인 구현 사용)
  근거: setup.py:complete_setup 라우트(243-347)는 SettingsStore.set을 직접 호출하는 인라인 구현을 쓴다.
        setup_service.complete_setup(68-137)은 그와 중복된 별도 구현이며 라우트에서 호출되지 않는다
        (grep 결과 setup_service.complete_setup 호출처 없음 — generate/verify/delete_setup_token만 사용).
        게다가 이 죽은 함수는 first_admin user를 name="Admin", roles=["admin"]로 upsert하는 로직을 담고 있어,
        실제 경로(auth.callback의 first_admin_email anchor)와 정책이 어긋난다. 향후 누군가 이 함수를 되살리면
        승격 정책 불일치 버그가 재발한다.
  제안: setup_service.complete_setup를 삭제하거나, 라우트가 이 서비스를 호출하도록 일원화하라(레이어 경계
        — 비즈니스 로직이 라우트에 인라인된 상태). 토큰 관리 함수만 남기는 것이 깔끔하다.
```

```
[🟡][⚙️ 기능] app/auth/deps.py:133 ROLE_PRIORITY vs oidc.py:130 system_roles — 역할 어휘 불일치 (owner/operator는 OIDC 단계에서 폐기됨)
  근거: ROLE_PRIORITY=("owner","admin","sender","operator","viewer")는 owner/operator를 포함하나,
        parse_user_from_claims(oidc.py:130)의 system_roles={"viewer","sender","admin"}는 owner/operator를
        필터로 제거한다. 즉 Keycloak에서 owner/operator를 부여해도 로그인 시점에 사라져 viewer로 강등된다.
        web/lib/auth.ts:3 Role 타입과 settings.py primary_role도 owner/operator를 1급 시민으로 다루지만,
        실제로는 절대 세션/DB에 들어올 수 없는 값이라 죽은 분기다. 권한 상승 위험은 아니나(오히려 보수적),
        운영자가 owner role을 만들어 부여했는데 동작하지 않는 혼란을 유발한다.
  제안: 역할 어휘를 한 곳(상수)으로 통일하라. owner/operator를 지원할 거면 system_roles에 추가하고,
        아니면 ROLE_PRIORITY/TS Role에서 제거해 단일 진실 소스를 유지하라.
```

```
[🟡][⚙️ 기능] app/security/crypto.py:51-64 get_fernet @lru_cache — 키 로테이션/재로딩 불가, 키 파일 교체 후에도 구 키를 영구 캐시
  근거: get_fernet은 lru_cache(maxsize=1)로 첫 호출 시 로드한 Fernet 인스턴스를 프로세스 생명주기 내내 캐시한다.
        master.key를 교체(로테이션)해도 캐시가 무효화되지 않아 구 키로 계속 암복호화한다. Fernet은
        MultiFernet 기반 키 로테이션을 지원하지만 현재 단일 키 + 캐시 구조라 로테이션 경로가 아예 없다.
        crypto.py 헤더에 로테이션 언급이 없고, 키 유출 시 재키잉 절차가 부재하다(데이터 보안 관점 부채).
  제안: 키 로테이션이 요구사항이면 MultiFernet(신키, 구키) 패턴 + 캐시 무효화 훅을 도입하라.
        요구사항이 아니면 "로테이션 미지원"을 crypto.py 주석에 명시해 운영 기대치를 맞춰라.
```

```
[🟡][⚙️ 기능/UX] web/middleware.ts:29-37 vs web/app/(app)/layout.tsx:10-11 — 2-tier guard가 "쿠키 존재"만 검사, 만료/위조 세션은 layout/FastAPI까지 가서야 차단 (이중 리다이렉트)
  근거: 미들웨어는 sms_session 쿠키의 "존재"만 본다(서명·만료 검증 없음 — Edge에서 secret 접근 불가하므로
        설계상 불가피). 만료되거나 위조된 쿠키를 든 요청은 미들웨어를 통과한 뒤 layout.tsx의 getSession()
        →FastAPI /auth/me 401→ redirect('/login')에서 비로소 차단된다. 보안 우회는 아니다(서버 측 /auth/me가
        세션을 실제 검증하므로 인가는 안전). 다만 만료 쿠키 사용자는 보호 페이지를 시도→layout에서 재리다이렉트
        하는 추가 왕복을 겪고, getSession 실패가 try/catch로 null 처리(auth.ts:50-52)되어 네트워크 장애와
        인증 실패가 구분되지 않는다.
  제안: 현 설계는 인가 측면에서 안전하므로 유지 가능. UX 개선이 필요하면 /auth/me 401 응답 시 미들웨어가
        Set-Cookie로 만료 쿠키를 제거하도록 협조시켜라. 우선순위 낮음.
```

---

## 🟢 LOW

```
[🟢][🔢 알고리즘/보안] app/security/crypto.py:98-109 mask() + app/routes/settings.py:440-441 — 짧은 시크릿/웹훅 토큰의 끝 4자 admin에게 노출
  근거: mask()는 길이>4면 끝 4자를 노출한다. webhook_token(hex 32자)의 끝 4자가 GET /settings/provider로
        모든 admin에게 보인다. webhook_token은 웹훅의 유일한 인증 수단(URL obscurity)이라 4자 노출은
        엔트로피를 16비트 깎는다(나머지 112비트로 여전히 안전). session.secret 끝 4자 노출도 동일하게 minor.
  제안: 매우 민감한 시크릿(session.secret, webhook_token)은 끝 4자 대신 "설정됨" 플래그만 노출하는
        것을 고려. 현 상태로도 실질 위험은 낮음.
```

```
[🟢][🧹 코드품질] app/main.py:119-130 lifespan vs 144-158 모듈 레벨 — 세션 시크릿/msghub 클라이언트 초기화가 모듈 임포트 시점과 lifespan 양쪽에서 중복 실행
  근거: _session_secret은 모듈 로드 시(149-158) 한 번 읽혀 add_session_middleware에 박히고(208),
        lifespan(110-115)에서 get_session_secret을 또 호출한다(반환값 미사용 — 단순 캐시 워밍?).
        msghub 클라이언트도 lifespan(118)에서 생성되나 get_msghub_client/aget_msghub_client가 지연 생성도 한다.
        기능상 문제는 없으나, SessionMiddleware secret은 "모듈 로드 시점" 값에 고정되어 setup/complete가
        새 session.secret을 저장해도 프로세스 재시작 전까지 반영 안 됨(setup.py:341-345가 restartRecommended로
        이미 안내 — 인지된 제약). 의도는 맞으나 흐름이 분산돼 추적이 어렵다.
  제안: lifespan:110-115의 미사용 get_session_secret 호출 목적을 주석화하거나 제거. 초기화 지점을 일원화.
```

```
[🟢][🧹 코드품질] app/auth/deps.py:27-41 parse_user_roles — 정의됐으나 require_role/get_current_user는 자체 인라인 json.loads 사용 (헬퍼 미활용)
  근거: parse_user_roles 헬퍼가 있으나 require_role(176-178), /me(auth.py:45-53) 등은 동일한 json.loads
        try/except를 인라인 반복한다. 로직 중복으로 향후 한 곳만 고치면 누락 위험.
  제안: 역할 파싱을 parse_user_roles 단일 함수로 수렴.
```

```
[🟢][⚙️ 기능] app/models.py:298-336 MoMessage / app/routes/webhook.py:223,260 — 고객 MO 원문(mo_msg)·raw_payload(전체 페이로드, 전화번호 포함) 무기한 저장, 보존정책·인덱스 부재
  근거: receive_mo는 raw_payload(전체 JSON, 고객 번호·내용 포함)와 mo_msg(고객 텍스트)를 영구 저장한다.
        retention/expiry 컬럼이나 정리 잡이 없고, mo_number 인덱스는 있으나 PII 최소수집·보존 원칙
        (PIPA) 관점에서 무기한 원문 보관은 부채다. audit_logs.detail도 email을 평문 JSON으로 저장(audit.py:52)
        하나 이는 감사 목적상 허용 범위.
  제안: MO 원문/raw_payload에 보존기간(예: 90일) + 주기적 파기 잡을 도입하라. 요청 범위 밖이면 백로그로.
```

---

## 요약 통계표

### 심각도별
| 심각도 | 건수 |
|--------|------|
| 🔴 CRITICAL | 0 |
| 🟠 HIGH | 2 |
| 🟡 MEDIUM | 7 |
| 🟢 LOW | 4 |
| **합계** | **13** |

### 렌즈별 (주 렌즈 기준)
| 렌즈 | 건수 |
|------|------|
| 🧭 UX | 0 (1건 부차) |
| ⚙️ 기능(엣지케이스·버그) | 7 |
| 🧹 코드품질 | 4 |
| 🔢 알고리즘(정확성·성능) | 2 |

대부분 발견이 보안/기능 성격이며, 순수 알고리즘 성능 이슈는 없음(데이터 모델 인덱싱은 양호 — campaigns/messages/contacts/mo_messages 모두 적절히 인덱스됨, 마이그레이션-모델 일치 확인).

---

## Top 위험 3

1. **🟠 webhook_token 미설정으로 운영 직후 발송 리포트/MO 전면 차단** (webhook.py:68-73 + setup.py:309-322)
   wizard가 토큰을 만들지 않는데 운영 모드는 토큰 없으면 401 거부 → Message가 영구 PENDING, 캠페인 집계·비용
   미갱신. 신규 배포의 핵심 기능(발송 결과 추적)이 사일런트하게 깨진다. 운영 절차로만 가려질 뿐 코드 결함.

2. **🟠 SMS fallback 로그의 전화번호 평문 노출** (webhook.py:121)
   대량 발송 시스템의 핵심 PII인 수신자 번호가 실패 로그에 원문 기록. 발송 실패는 빈번해 로그에 다량 누적되고,
   journald/로그파일 접근자에게 PIPA 적용 개인정보가 노출된다.

3. **🟡 setup test-* 엔드포인트의 토큰 미검증 SSRF/자격증명 오라클** (setup.py:134-219)
   bootstrap 완료 전 창에서 setup 토큰 없이(CSRF만으로) 임의 외부 host로 GET 프록시 + 내부 예외 메시지 반환 +
   msghub 자격증명 유효성 오라클. require_setup_mode가 완료 후 404로 막아 노출 창이 제한적이라 MEDIUM이나,
   설치 전 인터넷 노출 환경에서는 실질 위험.
