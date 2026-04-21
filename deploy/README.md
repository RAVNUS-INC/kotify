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
| 2 | 시스템 패키지 설치 (Python 3.12/3.13, Node 20, pnpm, git, sqlite3) |
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
| `kotify-update.sh` | `/settings` → System → Update 에서 호출하는 스크립트 (git pull + 양쪽 재빌드 + systemd restart) |
| `sms-backup.sh` | SQLite DB 일일 백업 스크립트 |
| `sms-backup.cron` | 백업 cron 설정 (`/etc/cron.d/`에 복사) |
| `npm-config.md` | NPM Proxy Host 설정 가이드 |

---

## 운영 명령어 참고

```bash
# 서비스 상태 (둘 다 확인)
systemctl status kotify        # FastAPI
systemctl status kotify-web    # Next.js

# 로그 확인
journalctl -u kotify -f
journalctl -u kotify-web -f
tail -f /var/log/kotify/stdout.log
tail -f /var/log/kotify/stderr.log

# 서비스 재시작
systemctl restart kotify kotify-web

# 웹 UI 업데이트 (원클릭)
# /settings → System → Update 버튼
# 내부적으로 sudo /opt/kotify/deploy/kotify-update.sh 실행:
#   git pull → pip install -e . → pnpm install && pnpm build → systemctl restart

# 백업 수동 실행
sudo -u kotify /opt/kotify/deploy/sms-backup.sh

# DB 직접 조회
sqlite3 /var/lib/kotify/sms.db ".tables"
```

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
