# E2E 검증 체크리스트

운영 시작 전 단계별로 수행해야 할 검증 절차입니다.
각 단계를 순서대로 진행하고, 완료 시 `[x]`로 체크하세요.

---

## 1. U+ msghub 사전 준비

> msghub 계정과 RCS 브랜드/챗봇은 이미 등록되어 있다고 가정합니다.
> 미등록 상태라면 운영 리드타임(수 영업일)을 고려하여 **가장 먼저** 진행하세요.

- [ ] msghub 포털에서 계정 활성 상태 확인
- [ ] API Key / API Password 확보 (JWT 인증용)
- [ ] RCS 브랜드 ID (Brand ID) 확보
- [ ] RCS 챗봇 ID (Chatbot ID) 확보
- [ ] 발신번호 목록 확인 (msghub 포털의 Caller Number 관리)
- [ ] 소스 IP 화이트리스트 (msghub가 제한하는 경우) — CT 외부 IP 등록
- [ ] 요금제/잔액 확인 (후불: 잔액 충분, 선불: 선충전)

---

## 2. Keycloak 사전 준비

- [ ] Realm `sms-sys` 생성
- [ ] Client `sms-sys` 생성 (Access Type: `Confidential`, Standard Flow Enabled: ON)
- [ ] Client Secret 메모 (Credentials 탭)
- [ ] Valid Redirect URIs에 추가: `https://sms.example.com/auth/callback`
- [ ] Web Origins에 추가: `https://sms.example.com`
- [ ] Client Roles 생성: `viewer`, `sender`, `admin`
- [ ] 본인 사용자 계정에 역할 미사전 할당 (Setup Wizard 완료 시 첫 로그인 계정에 `admin` 자동 부여)

---

## 3. CT 배포

- [ ] Proxmox에서 CT 생성: Debian 12 또는 13, 1 vCPU, 1 GB RAM, 8 GB disk
- [ ] CT 네트워크 설정: 사내망 고정 IP 할당
- [ ] 아웃바운드 허용 확인:
  - msghub API (`api.msghub.uplus.co.kr:443` 또는 전용선 `1.209.4.60/75:443`)
  - Keycloak 서버
  - NTP (UDP 123)
  - GitHub (git clone) 또는 사내 git 미러
- [ ] CT root 콘솔 접속
- [ ] 부트스트랩 스크립트 실행:
  ```bash
  bash /opt/kotify/deploy/ct-bootstrap.sh
  ```
  스크립트가 설치하는 것: Python 3.12/3.13, Node 20, pnpm, 코드 git clone, 백엔드 venv,
  **Next.js pnpm install + pnpm build**, alembic 마이그레이션, 두 systemd 서비스 등록.
- [ ] systemd 상태 확인 (둘 다 active):
  ```bash
  systemctl status kotify        # FastAPI 8080
  systemctl status kotify-web    # Next.js 3000
  ```
- [ ] 헬스체크 통과 확인:
  ```bash
  curl http://127.0.0.1:8080/healthz          # FastAPI
  curl -I http://127.0.0.1:3000/              # Next.js (200 또는 /login으로 302)
  ```
- [ ] setup.token 메모:
  ```bash
  cat /var/lib/kotify/setup.token
  ```

---

## 4. NPM 설정

- [ ] NPM 관리자 화면에서 Proxy Host 추가 (`deploy/npm-config.md` 참고)
- [ ] Domain: `sms.example.com`, Forward: **`<CT IP>:3000`** (Next.js — 외부 대면)
- [ ] **Websockets Support ON** (SSE 스트림 통과)
- [ ] **Advanced Nginx**: `proxy_buffering off` + `proxy_read_timeout 300s`
- [ ] Let's Encrypt SSL 인증서 발급 완료
- [ ] Force SSL ON 확인
- [ ] 헬스체크 HTTPS 확인:
  ```
  https://sms.example.com/api/healthz → 200 OK, {"status":"ok"}
  ```
  (Next.js가 `/api/*`를 FastAPI로 rewrite — 이게 돌면 두 서비스 간 프록시도 정상)

---

## 5. Setup Wizard

- [ ] `https://sms.example.com` 접속 → `/setup`으로 자동 리다이렉트 확인
- [ ] **Step 1**: setup.token 입력 → 검증 성공
- [ ] **Step 2**: Keycloak 정보 입력 (Issuer URL, Client ID=`sms-sys`, Client Secret) → "연결 테스트" 성공
- [ ] **Step 3**: msghub 정보 입력 (API Key, API Password) → "인증 테스트" 성공 (JWT 발급 확인)
- [ ] **Step 3** 환경은 상용 `production` 또는 검수 `qa` 중 하나만 선택 가능하고, 임의 값은 저장되지 않음
- [ ] **Step 4**: RCS 브랜드/챗봇 ID 입력 → "조회 테스트" 성공
- [ ] **Step 5**: Keycloak 로그인 (본인 계정) → 대시보드 진입 확인
- [ ] 본인 계정에 `admin` 역할 자동 부여 확인 (Keycloak 콘솔 또는 `/settings` 접근 가능 여부)
- [ ] `/var/lib/kotify/setup.token` 파일이 자동 삭제되었는지 확인:
  ```bash
  ls /var/lib/kotify/setup.token  # "No such file" 이어야 함
  ```
- [ ] `/setup` 재접근 시 404 응답 확인

---

## 6. master.key 백업

- [ ] `/var/lib/kotify/master.key` 내용을 안전한 위치에 백업:
  ```bash
  cat /var/lib/kotify/master.key
  ```
  → 1Password, 사내 비밀 저장소 등 **DB와 분리된** 위치에 저장
- [ ] 백업 위치를 팀 내에 문서화 (담당자 2명 이상 접근 가능)

---

## 7. 웹훅 수신 확인

msghub는 발송 결과를 웹훅으로 전송합니다. 외부에서 kotify로의 인바운드가 필요합니다.

- [ ] msghub 포털에서 웹훅 URL 등록:
  - Report: `https://sms.example.com/api/webhook/msghub/report`
  - MO(수신 메시지, 사용 시): `https://sms.example.com/api/webhook/msghub/mo`
- [ ] 웹훅 서명 시크릿 저장 (msghub 포털에서 발급받아 Setup Wizard 또는 `/settings`에서 입력)
- [ ] 테스트 발송 전 webhook endpoint가 200 응답하는지 확인 (단, 서명 검증 때문에 외부 curl로는 403 정상)

---

## 8. 본인 번호 발송 테스트 (RCS → SMS Fallback)

- [ ] `/send/new` 페이지 진입 (FastAPI의 `/compose`가 아님)
- [ ] 발신번호: 등록된 번호 중 하나 선택
- [ ] 수신자: 본인 휴대폰 번호 1개 입력 (예: `010-XXXX-XXXX`)
- [ ] 본문: `테스트 발송입니다.` (짧은 텍스트 → RCS 단방향 SMS형 경로)
- [ ] 미리보기 확인:
  - 수신자 1명 기준 예상 비용 9~17원 (RCS 단방향 17원 / SMS fallback 9원)
  - 장문은 RCS/LMS 모두 27원
  - 비용은 VAT 별도 앱 추정값이며 공급자 확정 청구액이 아님
- [ ] "발송하기" 클릭
- [ ] 본인 휴대폰에서 RCS 또는 SMS 수신 확인 (단말/통신사 RCS 지원 여부에 따라 달라짐)
- [ ] `/campaigns/[id]` 에서 캠페인 상태 `COMPLETED` + 채널별 결과 확인
- [ ] `/audit` 에서 `SEND` 감사 로그 확인

### 8.1 이미지 포함 발송 테스트 (RCS MMS → MMS Fallback)

- [ ] `/send/new`에서 이미지 첨부
- [ ] 본문 + 이미지로 미리보기
- [ ] 수신자 1명 기준 예상 비용 RCS MMS(`RPMSMMX001`) / MMS fallback 모두 85원(VAT 별도) 확인
- [ ] 본인 번호로 발송 → RCS 이미지 또는 MMS 수신 확인
- [ ] DB/공급자 조회에서 한 첨부에 서로 다른 MMS·RCS file ID가 있고, RCS 본문은 RCS ID, fallback은 MMS ID를 사용함
- [ ] 만료됐거나 예약 시각 전에 만료되는 첨부는 공급자 요청 전에 재업로드 안내로 차단됨

### 8.2 서버 기준 미리보기 검증 (발송 없이 확인)

- [ ] 수신자 1명에서 `가` 45자는 90바이트·단문, 46자는 92바이트·장문(27원)으로 표시
- [ ] 일반 문자 채널의 단문은 9원, RCS 채널의 단문은 9~17원으로 표시
- [ ] 같은 수신자 문자열의 중복은 비용 계산에서 한 번만 반영
- [ ] 본문·수신자·채널·이미지 변경 직후 이전 견적을 숨기고 확인 중에는 발송 차단
- [ ] 이모지 등 EUC-KR 미지원 문자와 2000바이트 초과 본문은 오류·발송 차단
- [ ] 견적 통신 실패 시 오류를 표시하고 `다시 확인`으로 복구 가능

### 8.3 예약·MO·리포트 경계 검증

- [ ] 현재부터 30일 이내 예약은 접수되고 30일을 초과하는 예약은 화면/API에서 차단됨
- [ ] SMS/MMS 회신에서 공급자 `moNumber`가 우리 대표번호, `moCallback`이 고객 번호일 때 대화방의 고객 번호와 발신번호가 올바르게 저장됨
- [ ] RCS 회신에서 `phone`과 `chatbotId`가 각각 고객 번호와 등록 Caller로 연결됨
- [ ] 웹훅 처리 중 일시 DB 오류로 400을 반환한 뒤 공급자가 재전송하고, 동일 `msgKey`/`moKey`가 중복 저장되지 않음
- [ ] 90일을 넘긴 조회에 `OVER_DATE`가 오면 메시지가 실패로 종료되고 다음 미완료 메시지가 계속 재조정됨

---

## 9. 실패 케이스 검증

- [ ] 잘못된 번호 포함 발송 시도:
  - 수신자에 `010-0000-0000` (잘못된 형식) 입력
  - 발송 전 차단 또는 에러 메시지 표시 확인 (UI의 검증 + 서버 검증 2중 방어)
- [ ] msghub 인증 오류 시뮬레이션:
  - `/settings`에서 msghub API Password를 임의 값으로 변경
  - 발송 시도 → 503 에러 + 친절한 안내 메시지 확인
  - API Password 원복 후 재발송 성공 확인
- [ ] 권한 우회 시도:
  - `viewer` 역할 사용자로 로그인 → `/send/new` 접근 시 403 또는 `/` 로 리다이렉트 확인

---

## 10. 백업 검증

- [ ] 백업 스크립트 수동 실행:
  ```bash
  sudo -u kotify /opt/kotify/deploy/sms-backup.sh
  ```
- [ ] 백업 파일 생성 확인:
  ```bash
  ls -lh /var/backups/kotify/
  # kotify-YYYYMMDD.db 파일 존재 확인
  ```
- [ ] 파일 크기 > 0 확인:
  ```bash
  du -h /var/backups/kotify/kotify-$(date +%Y%m%d).db
  ```
- [ ] (분기 1회 권장) 별도 CT에서 백업 복원 후 데이터 동일성 확인:
  ```bash
  # 별도 CT에서
  cp kotify-YYYYMMDD.db /var/lib/kotify/sms.db
  systemctl start kotify kotify-web
  # 이력 조회, 로그인 등 정상 동작 확인
  ```

---

## 11. 모니터링 설정

- [ ] logrotate 설정으로 로그 파일 회전:
  ```bash
  cat > /etc/logrotate.d/kotify << 'EOF'
  /var/log/kotify/*.log {
      daily
      rotate 30
      compress
      delaycompress
      missingok
      notifempty
      postrotate
          systemctl kill -s USR1 kotify || true
          systemctl kill -s USR1 kotify-web || true
      endscript
  }
  EOF
  ```
- [ ] systemctl status 정기 확인 또는 외부 모니터링 연동 (Uptime Kuma 등):
  - 모니터링 대상 1: `https://sms.example.com/` (Next.js 200)
  - 모니터링 대상 2: `https://sms.example.com/api/healthz` (FastAPI 프록시 경유 `{"status":"ok"}`)
- [ ] 백엔드 로그에서 msghub `PUT /client/v1/healthCheck`가 60초 이내 주기로 성공하고 반복 오류가 없음
- [ ] 설정의 n8n 테스트를 실행해 로그인한 사용자의 Telegram에서 `[테스트]` 알림 수신 확인
- [ ] n8n 실행 기록에서 테스트 요청의 `lastSender.id`가 로그인 이메일이고 Telegram 전송 노드가 성공했는지 확인
- [ ] `notification_deliveries` 상태 집계에서 새 회신 알림이 `DELIVERED`이며 `FAILED`가 계속 쌓이지 않는지 확인(페이로드·본문은 출력하지 않음)
- [ ] 점검 환경에서 n8n을 일시 중단한 뒤 회신 1건이 `FAILED`로 남고, 복구 후 60초 주기 재시도로 `DELIVERED`가 되는지 확인
- [ ] 알림 채널 설정 (서비스 다운 시 담당자에게 통보)

---

## 12. 브라우저 런타임 감사 (Phase 10d)

배포 완료 후 실제 운영 환경에서 수행합니다.

### 12.1 Lighthouse

Chrome DevTools → Lighthouse에서 아래 카테고리 측정. 각 페이지 × desktop 모드.

- [ ] `/login`, `/`, `/campaigns`, `/reports`, `/notifications` 측정
- [ ] Performance > 90, Accessibility > 95, Best Practices > 90, SEO > 90 목표

### 12.2 Core Web Vitals

- [ ] FCP < 1.8s, LCP < 2.5s, CLS < 0.1, TBT < 200ms
- [ ] **Counter tabular-nums로 CLS 0 유지** 확인 (자릿수 변화 시 layout shift 없음)

### 12.3 60fps 유지

- [ ] DevTools → Performance 녹화 → 페이지 로드 후 1.2s 이내 모든 연출 종료
- [ ] `/reports`처럼 다중 연출(Sparkline × 4 + AnimatedBars × 7 + Progress × 4) 페이지에서 60fps 유지 확인

### 12.4 Reduced Motion

- [ ] DevTools → Rendering → "Emulate CSS prefers-reduced-motion" → `reduce`
- [ ] Counter, Sparkline, Progress, Rise가 즉시 최종값으로 점프 확인
- [ ] `PulseDot`이 정지 확인 (globals.css 미디어 쿼리 동작)

### 12.5 axe-core

- [ ] axe DevTools 확장으로 각 페이지 실사
- [ ] critical/serious 이슈 0건 목표

측정 결과는 `claudedocs/phase-10d-runtime-audit.md`의 "_측정 중_" 칸에 기입.

---

## 체크리스트 완료 기준

위 12개 섹션의 모든 항목이 체크된 상태에서:

1. 본인 번호로 RCS 또는 SMS 1회 이상 정상 수신 (fallback 경로 포함)
2. `/audit` 에 발송 이력 기록
3. 백업 파일 정상 생성
4. master.key 안전하게 보관 완료
5. Phase 10d 런타임 감사 완료

위 5가지가 확인되면 운영 시작 가능합니다.
