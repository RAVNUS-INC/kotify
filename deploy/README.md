# 배포 가이드

kotify Proxmox LXC CT 배포 절차 요약입니다.
FastAPI 백엔드 + Next.js 프론트엔드가 단일 컨테이너에 공존합니다.

---

## 배포 전제

- **완전 새 설치**: 기존 CT가 있다면 폐기 후 새로 생성하는 것을 전제로 합니다.
- **설정은 DB에 저장**: `.env` 파일을 쓰지 않습니다. 모든 시크릿은 `master.key`로 암호화되어 `sms.db`에 저장되며 Setup Wizard에서 입력합니다.
- **DB는 자동 구축**: `ct-bootstrap.sh` 실행 중 `alembic upgrade head`가 빈 파일에서 최신 스키마까지 한 번에 구축합니다. 이전 데이터 이관 불필요.

---

## 배포 순서

### 1. Proxmox에서 CT 생성

| 항목 | 값 |
|---|---|
| OS | Debian 12 (Bookworm) 또는 13 (Trixie) |
| CPU | 1 vCPU |
| RAM | 1 GB |
| Disk | 8 GB |
| 네트워크 | IP 할당 (아웃바운드 허용 필요) |

CT 생성 후 **아웃바운드 허용**:
- U+ msghub API 엔드포인트 (`api.msghub.uplus.co.kr:443` 또는 전용선 IP 1.209.4.60/75)
- Keycloak 서버 주소:포트
- NTP 서버 (UDP 123)
- GitHub (git clone용) — 사내 git 미러를 쓰면 해당 주소

---

### 2. CT 진입 후 부트스트랩 실행

CT 콘솔에서 root로 실행합니다.

**방법 A — curl pipe (git clone 불필요):**
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/RAVNUS-INC/kotify/main/deploy/ct-bootstrap.sh)
```

**방법 B — git clone 후 직접 실행:**
```bash
git clone https://github.com/RAVNUS-INC/kotify.git /opt/kotify
bash /opt/kotify/deploy/ct-bootstrap.sh
```

스크립트가 자동으로 수행하는 작업:

| 단계 | 내용 |
|---|---|
| 1 | OS 확인 (Debian 12/13) |
| 2 | 시스템 패키지 설치 (Python 3.12/3.13, Node 20, pnpm, git, sqlite3, sudo) |
| 3 | NTP 동기화 (msghub JWT 시간 검증을 위해 필수) |
| 4 | `kotify` 시스템 사용자/그룹 생성 |
| 5 | 디렉토리 생성 (`/opt/kotify`, `/var/lib/kotify`, `/var/log/kotify`, `/var/backups/kotify`) |
| 6 | 코드 git clone |
| 7a | Python 가상환경 + 백엔드 의존성 (`.venv/bin/pip install -e .`) |
| 7b | **pnpm install + pnpm build (Next.js 프로덕션 빌드)** |
| 8 | DB 초기화 (`alembic upgrade head`) |
| 9 | systemd 서비스 등록: `kotify.service` (FastAPI 8080) + `kotify-web.service` (Next.js 3000) |
| 10 | 서비스 기동 확인 + 헬스체크 |
| 11 | 백업 cron 설치 |

최소 구성 CT에도 웹 UI 업데이트에 필요한 `sudo`를 설치한다. `sudo`가 없는 상태에서는
sudoers 설정을 설치하지 않고 경고하므로, 해당 경고가 있으면 패키지 설치 상태를 먼저 확인한다.

---

### 3. setup.token 확인

```bash
cat /var/lib/kotify/setup.token
```

이 토큰은 Setup Wizard 첫 단계에서 입력합니다. 메모해 두세요.

---

### 4. NPM 설정

`deploy/npm-config.md` 가이드를 참고하여
Nginx Proxy Manager에서 `sms.example.com` Proxy Host를 추가합니다.

핵심 설정:
- **Forward to**: `<CT IP>:3000` (Next.js — 외부 대면)
- **SSL**: Let's Encrypt + Force SSL ON
- **WebSocket Support ON** — chat SSE 스트림 통과용
- FastAPI(8080)는 외부에 노출되지 않음. Next.js가 `next.config.mjs`의 `rewrites()`로 `/api/*`를 내부에서만 FastAPI로 프록시.

---

### 5. Setup Wizard 실행

```
https://sms.example.com/setup
```

Wizard 단계:

1. **setup.token 입력** 및 검증
2. **Keycloak 연결 정보** 입력 및 테스트 (issuer, client_id=`sms-sys`, client_secret)
3. **msghub 인증 정보** 입력 및 테스트 (API Key, API Password)
4. **RCS 브랜드/챗봇 ID** 확인 (사전 등록된 상태)
5. **첫 관리자 로그인** (Keycloak으로 리다이렉트 → 로그인 성공 시 `admin` 역할 자동 부여)

---

### 6. master.key 백업

Wizard 완료 직후 반드시 수행:

```bash
cat /var/lib/kotify/master.key
```

→ 1Password, 사내 비밀 저장소 등 **DB와 분리된 안전한 위치**에 보관.

> **중요**: master.key를 분실하면 DB의 모든 암호화된 설정값(msghub API Password, Keycloak 시크릿)을
> 복호화할 수 없습니다. DB를 초기화하고 Setup Wizard를 재실행해야 합니다.

---

### 7. 본인 번호로 테스트 발송

1. `https://sms.example.com/send/new` 접속
2. 본인 번호 1개 입력
3. 짧은 텍스트 입력 (예: "테스트 발송입니다.")
4. 미리보기 → 예상 비용 / 채널(RCS 양방향 → SMS fallback) 확인
5. 발송
6. 본인 휴대폰에서 RCS 또는 SMS 수신 확인 (RCS 미지원 단말이면 SMS fallback 경로)
7. `/campaigns/{id}`에서 상태 `COMPLETED` + 채널별 결과 확인
8. `/audit`에서 `SEND` 감사 로그 확인

---

## E2E 검증

상세한 단계별 검증 절차:

```
claudedocs/E2E-CHECKLIST.md
```

---

## 파일 설명

| 파일 | 설명 |
|---|---|
| `ct-bootstrap.sh` | CT 초기 설정 자동화 스크립트 (Python + Node + 빌드 + systemd 전부 처리) |
| `kotify.service` | systemd 유닛 — FastAPI (uvicorn 8080) |
| `kotify-web.service` | systemd 유닛 — Next.js (node server 3000) |
| `kotify-sudoers` | 웹 UI 원클릭 업데이트 허용용 sudoers fragment |
| `kotify-update.sh` | `/settings` → System → Update 에서 호출하는 스크립트 (git pull 후 worker 로 넘김) |
| `kotify-update-worker.sh` | 실제 업데이트 (의존성·마이그레이션·빌드, 실패 시 git·DB 롤백) + 재시작 예약 |
| `kotify-post-restart.sh` | 재시작 후 기동 확인 — 실패하면 이전 커밋으로 롤백·재빌드 |
| `kotify-backup.sh` | SQLite DB 일일 백업 스크립트 |
| `kotify-backup.cron` | 백업 cron 설정 (`/etc/cron.d/`에 복사) |
| `npm-config.md` | NPM Proxy Host 설정 가이드 |

---

## 운영 명령어 참고

```bash
# 서비스 상태 (둘 다 확인)
systemctl status kotify        # FastAPI
systemctl status kotify-web    # Next.js

# systemd 서비스 기동·종료 기록
journalctl -u kotify -f
journalctl -u kotify-web -f
# FastAPI 애플리케이션·접근 로그 (유닛의 StandardOutput/StandardError 대상)
tail -f /var/log/kotify/stdout.log
tail -f /var/log/kotify/stderr.log

# 서비스 재시작
systemctl restart kotify kotify-web

# 웹 UI 업데이트 (원클릭)
# /settings → System → Update 버튼
# 내부적으로 sudo /opt/kotify/deploy/kotify-update.sh 실행:
#   git pull → pip install -e . → alembic upgrade → pnpm install && pnpm build
#   (여기까지 실패하면 git·DB 자동 롤백, 재시작 안 함)
#   → systemd-run 으로 kotify-post-restart.sh: 재시작 → /healthz 가 새 버전으로
#     응답하는지 최대 120초 확인 → 실패하면 이전 커밋으로 롤백·재빌드·재시작
#     (이번 배포에 마이그레이션 변경이 있었을 때만 DB 를 pre-migrate 백업으로 복원)
# 결과 확인:
tail -n 50 /var/log/kotify/update.log

# CT 콘솔에서 root로 수동 업데이트 (소스와 패키지의 서비스 계정 읽기 권한 유지)
(umask 022; bash /opt/kotify/deploy/kotify-update.sh apply)

# 백업 수동 실행
sudo -u kotify /opt/kotify/deploy/kotify-backup.sh

# DB 직접 조회
sqlite3 /var/lib/kotify/sms.db ".tables"
```

별도 DB 스냅샷은 백업 파일 자체에 `0600` 권한을 적용한다. 백업용 `umask 077`을
업데이트 프로세스까지 전달하면 checkout·패키지 설치 결과가 root 전용이 되어
`kotify` 계정의 마이그레이션이 `PermissionError`로 실패할 수 있다. 이 경우 롤백 상태를
확인하고 위 수동 업데이트 명령의 일반 설치 권한으로 재설치한다.

### 대화방 읽음 경계 0019 배포·호환

대화방 리뷰 후속 수정에는 스키마 `0019`와 읽음 API 계약 변경이 포함된다. 이 절은 배포 시
따를 절차이며, 이번 작업에서 운영 마이그레이션이나 배포를 수행했다는 기록이 아니다.

- 기존 업데이트 worker의 pre-migrate DB 백업과 `alembic upgrade head` 절차를 사용한다.
  `0019`는 `thread_reads.last_read_mo_id`와 `phone` 인덱스를 추가하고 기존 caller별 행을 보존한다.
  `mo_messages`를 재구축하거나 삭제하지 않는다.
- 기존 읽음 시각 이전에 서버가 받은 `received_at`의 연속 ID 구간만 보수적으로 이관한다.
  공급자 시각만 과거인 지연 회신이나 불명확한 이력은 읽음으로 추정하지 않으므로 일부 과거
  대화가 안읽음으로 다시 표시될 수 있다. 수신 이력을 삭제해 이를 정리하지 않는다.
- 백엔드와 Next.js를 같은 릴리스로 빌드·재시작한다. 새 읽음 API는
  `{ "lastReadMessageId": 42 }` JSON을 요구하며 구 프런트엔드의 본문 없는 요청은 HTTP 422다.
  배포 후 기존에 열어 둔 대화방 탭도 새로고침해 새 클라이언트를 로드한다. API의 페이지
  metadata와 상세 `lastInboundMessageId` 역시 새 프런트엔드와 함께 적용한다.
- 기존 서비스·헬스체크 확인에 더해 Alembic revision이 `0019`인지, 대화 조회 응답에
  `lastInboundMessageId`와 목록 metadata가 있는지 확인한다. 읽음은 사용자별이 아닌 고객 번호별
  팀 공유 상태이며 읽음 요청은 화면에서 실제 관측한 수신 ID만 전송한다.
- 배포 실패 시 기존 worker의 이전 코드·pre-migrate DB 백업 동시 복원 절차를 따른다.
  새 backend만 남기거나 이전 웹 번들만 선택적으로 재시작하지 않는다. 롤백 시점 이후의 발송·회신
  데이터는 백업 복원 범위와 함께 확인한다. 로컬 임시 DB에서 전체 upgrade(`0019`) →
  downgrade(`0018`) → 재upgrade는 검증했지만 운영 복구 검증을 대신하지 않는다.

현재 MO 삭제 경로가 없다는 전제로 수신 ID를 읽음 경계에 사용한다. 향후 MO 삭제·보관을
도입할 때에는 SQLite ID 재사용 방지 순번도 함께 설계해야 한다.

### CT SSH 재로딩 실패

Proxmox CT에서 `ssh.socket`으로 기동된 SSH가 `systemctl reload ssh` 직후
`Received SIGHUP; restarting.` → `fatal: Cannot bind any address.`로 종료된다면,
Proxmox의 **CT 콘솔**에서 일반 서비스 방식으로 전환할 수 있다.
Debian의 [동일 오류 보고](https://bugs.debian.org/cgi-bin/bugreport.cgi?bug=1128329)와
[OpenSSH 패키지 안내](https://sources.debian.org/src/openssh/1%3A10.3p1-4/debian/README.Debian)를 참고한다.

```bash
systemctl disable --now ssh.socket
systemctl stop ssh.service
systemctl reset-failed ssh.service
systemctl enable --now ssh.service
systemctl status ssh.service --no-pager -l
ss -ltnp 'sport = :22'
```

`active (running)`과 22번 포트의 `LISTEN`을 확인한 뒤 등록한 공개키로 접속한다.
2026-09-18 운영 CT에서 위 전환 후 서비스 실행과 Mac에서의 공개키 SSH 접속을 확인했다.
공개키 인증·호스트 키 검증은 유지하고, 접속 주소와 키 원문은 저장소에 기록하지 않는다.

### Keycloak 역할 진단

일반 요청과 `/api/auth/me`는 세션의 사용자 식별자로 DB 사용자를 조회하고, DB의 최신 역할·프로필을
사용한다. 역할·프로필·`last_login_at`은 검증된 로그인 콜백에서만 갱신한다. 다른 로그인에서 권한이
변경되면 기존 세션도 다음 요청부터 그 DB 역할을 따르며, DB에서 삭제한 사용자는 기존 세션으로
복원되지 않는다. 잘못된 형식의 DB 역할 값에는 권한을 부여하지 않는다.
Keycloak에서만 역할을 변경한 경우에는 `/api/auth/login`으로 새 인증을 거쳐 DB에 반영해야 한다.
매 요청마다 Keycloak을 조회하지 않으며, 최초 관리자 이메일 정책과 로그인 진단은 유지한다.

새 로그인 감사 이벤트의 `detail.role_diagnostics`에는 클레임의 역할 필드 존재 여부·형태,
설정된 클라이언트와 `azp`의 일치 여부, 인식한 역할과 최종 적용 역할이 기록된다.
표시할 수 있는 역할은 `viewer`, `sender`, `admin`으로 제한하고 다른 역할은 개수만 남긴다.
클라이언트 이름·토큰 원문·인증 코드·쿠키·프로필 값을 진단 데이터에 넣지 않는다.
이 기록은 권한을 추가하지 않으며, 기존 로그인 이벤트에는 소급 적용되지 않는다.

진단 배포 후 문제가 발생한 사용자가 Kotify에서 로그아웃·재로그인하면 운영자가 다음처럼
진단 필드만 조회한다. 기존 감사 로그 화면은 상세 JSON을 표시하지 않으므로 서버에서 확인한다.

```bash
sqlite3 -readonly /var/lib/kotify/sms.db \
  "SELECT id, created_at, json_extract(detail, '$.role_diagnostics') FROM audit_logs WHERE action = 'LOGIN' AND json_type(detail, '$.role_diagnostics') = 'object' ORDER BY id DESC LIMIT 10;"
```

원인별 조치는 다음과 같다. 변경 전 Keycloak의 **Clients → 설정된 클라이언트 → Client scopes →
Evaluate**에서 해당 사용자에 대한 토큰을 평가한다. 앱에 설정한 실제 client ID를 기준으로 확인한다.

| 확인 결과 | 조치 |
|---|---|
| Access Token에는 `sender`가 있고 ID Token에는 없음 | 앱의 전용 client scope에 있는 역할 매퍼의 **Add to ID token**과 연결된 역할 scope를 확인한다. 공유 scope 변경이 다른 앱에 미치는 영향도 고려하고, 필요한 설정을 수정한 뒤 재로그인한다. |
| 설정된 클라이언트에는 없고 다른 클라이언트에만 `sender`가 있음 | 역할이 Kotify가 실제 사용하는 클라이언트에 할당됐는지 확인하고 역할 매핑을 바로잡는다. |
| 설정된 클라이언트의 ID 클레임에는 `sender`가 있으나 파서 결과에는 없음 | `azp` 선택·클레임 형태를 재현해 파서 수정과 회귀 테스트를 진행한다. 확인되지 않은 Access Token을 임의 디코딩해 권한에 사용하지 않는다. |
| 로그인에서 적용한 역할은 `sender`인데 이후 DB가 `viewer`가 됨 | 최신 `LOGIN` 진단과 DB 값을 대조하고 후속 로그인에서 적용된 역할을 확인한다. 현재 소스의 일반 요청은 쿠키의 과거 역할을 DB에 다시 저장하지 않는다. 배포 버전도 확인한다. |

Keycloak은 기본적으로 역할을 Access Token에 추가하며 ID Token 포함 여부는 역할 매퍼로
설정한다([공식 역할 매핑 문서](https://www.keycloak.org/docs/latest/server_admin/#_role_mappings)).
필드가 없다는 사실만으로 매퍼 누락을 단정하지 말고 클라이언트 scope·역할 할당도 함께 확인한다.

#### 그룹에서 상속한 클라이언트 역할을 ID 토큰에 포함하기

2026-09-18 운영 진단에서 사용자에게 그룹 상속 `sender`가 있지만 공용 `client roles`
매퍼의 **Add to ID token**이 꺼져 있어 ID 토큰의 `resource_access`가 누락된 사례를 확인했다.
Kotify 클라이언트의 **Client scopes → 전용 scope → Mappers → Configure a new mapper**에
다음 전용 매퍼를 추가한다. 기존 그룹·역할 할당과 공용 `roles` scope는 유지한다.

| 항목 | 값 (`kotify`가 실제 client ID인 예시) |
|---|---|
| Mapper type | `User Client Role` |
| Name | `kotify-client-roles-id-token` |
| Client ID | `kotify` 선택 |
| Client Role prefix | 비움 |
| Multivalued / Claim JSON Type | On / String |
| Token Claim Name | `resource_access.kotify.roles` |
| Add to ID token | On |
| Access / lightweight access / userinfo / introspection | Off (기존 공용 매퍼 설정 유지) |

저장 후 `/api/auth/login`으로 새 인증을 시작한다. Keycloak SSO로 화면이 자동 통과돼도
새 콜백이 실행돼야 한다. 감사 이벤트에서 `azp_client.roles.known_roles`와 `parsed_roles`에
`sender`가 있고 `viewer_fallback_used=false`인지 확인한다. 첫 관리자 계정이면 최종 역할에
`admin`이 추가될 수 있다. 기존 앱 세션의 단순 새로고침은 새 토큰 검증을 대신하지 않는다.
2026-09-18 해당 전용 매퍼 저장 후 실제 재로그인에서 `sender` 클레임, 파싱 결과, 최종 DB 역할과
`viewer_fallback_used=false`를 확인했다. 최초 관리자 정책 대상 계정의 최종 역할은 `admin`·`sender`였다.

DB의 `users.roles`는 현재 권한 판정 기준이며, `last_login_at`은 이후 검증된 로그인에서만 갱신된다.
수정 전 기록의 시각은 일반 요청으로 갱신됐을 수 있으므로 과거 로그인 시각과 역할 적용 이력은
`LOGIN` 감사 이벤트로 확인한다. 과거 세션과 현재 DB 역할이 다른 것은 정상적으로 발생할 수 있어
`auth_session_role_mismatch` 경고는 제거했다. 로그인 진단 필드는 그대로 기록된다.

2026-09-18 05:25 UTC에 배포한 `9acc87d`는 기존 세션의 역할 덮어쓰기를 유지하고 불일치 경고를
추가한 버전이었다. 위 DB 기준 권한 정책은 이후 로컬 수정에 해당하며, 이번 작업에서는 운영에
배포하지 않았다. 앞선 그룹 역할 매퍼 설정·운영 로그인 검증 이력과 구분한다.

---

## 포트 배치

```
        외부 (HTTPS 443)
            │
            ▼
  ┌─────────────────────┐
  │ Nginx Proxy Manager │ (TLS 종단)
  └──────────┬──────────┘
             │ HTTP
             ▼
  ┌─────────────────────┐
  │  kotify-web.service │ (Next.js, 0.0.0.0:3000 → 외부 대면)
  │                     │
  │   /api/* rewrite    │
  │         ▼           │
  │ ┌─────────────────┐ │
  │ │ kotify.service  │ │ (FastAPI, 127.0.0.1:8080 → 내부만)
  │ │ uvicorn         │ │
  │ │  └ /webhook/*   │ │ ← msghub webhook 수신 (공개 경로는 Next.js가 프록시)
  │ │  └ /auth/*      │ │
  │ │  └ /healthz     │ │
  │ └─────────────────┘ │
  └─────────────────────┘
```

---

## 재배포 체크리스트

새 버전 출시 시:

1. `/settings` → System → Update 버튼 클릭 (권장)
2. 또는 수동:
   ```bash
   cd /opt/kotify && git pull
   .venv/bin/pip install -e .
   .venv/bin/alembic upgrade head
   cd web && pnpm install && pnpm build
   systemctl restart kotify kotify-web
   ```
3. 헬스체크 확인:
   ```bash
   curl -I https://sms.example.com/
   curl https://sms.example.com/api/healthz
   ```
