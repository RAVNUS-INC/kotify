# 배포 가이드

kotify Proxmox LXC CT 배포 절차 요약입니다.

---

## 배포 순서

### 1. Proxmox에서 CT 생성

| 항목 | 값 |
|---|---|
| OS | Debian 12 (Bookworm) |
| CPU | 1 vCPU |
| RAM | 1 GB |
| Disk | 8 GB |
| 네트워크 | IP 할당 (아웃바운드 허용 필요) |

CT 생성 후 **아웃바운드 허용 필요**:
- `sens.apigw.ntruss.com:443` (NCP SENS API)
- Keycloak 서버 주소:포트
- NTP 서버 (UDP 123)

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
- Python 3.12, 필수 패키지 설치
- NTP 동기화
- `sms` 시스템 사용자/그룹 생성
- 디렉토리 생성 및 권한 설정
- Python 가상환경 생성 및 의존성 설치
- DB 초기화 (alembic upgrade head)
- systemd 서비스 등록 및 시작
- 백업 cron 설치

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
- Forward to: `<CT IP>:8080`
- SSL: Let's Encrypt + Force SSL ON

---

### 5. Setup Wizard 실행

```
https://sms.example.com/setup
```

Wizard 단계:
1. setup.token 입력 및 검증
2. Keycloak 연결 정보 입력 및 테스트
3. NCP SENS 인증 정보 입력 및 테스트
4. 발신번호 확인
5. 첫 관리자 로그인 (Keycloak으로 리다이렉트)

---

### 6. master.key 백업

Wizard 완료 직후 반드시 수행:

```bash
cat /var/lib/kotify/master.key
```

→ 1Password, 사내 비밀 저장소 등 **DB와 분리된 안전한 위치**에 보관.

> **중요**: master.key를 분실하면 DB의 모든 암호화된 설정값(NCP 키, Keycloak 시크릿)을  
> 복호화할 수 없습니다. DB를 초기화하고 Setup Wizard를 재실행해야 합니다.

---

### 7. 본인 번호로 테스트 발송

1. `https://sms.example.com/compose` 접속
2. 본인 번호 1개 입력
3. 테스트 문자 발송
4. 수신 확인

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
| `ct-bootstrap.sh` | CT 초기 설정 자동화 스크립트 |
| `kotify.service` | systemd 서비스 유닛 파일 |
| `sms-backup.sh` | SQLite DB 일일 백업 스크립트 |
| `sms-backup.cron` | 백업 cron 설정 (`/etc/cron.d/`에 복사) |
| `npm-config.md` | NPM Proxy Host 설정 가이드 |

---

## 운영 명령어 참고

```bash
# 서비스 상태
systemctl status kotify

# 로그 확인
journalctl -u kotify -f
tail -f /var/log/kotify/stdout.log
tail -f /var/log/kotify/stderr.log

# 서비스 재시작
systemctl restart kotify

# 백업 수동 실행
sudo -u kotify /opt/kotify/deploy/sms-backup.sh

# DB 직접 조회
sqlite3 /var/lib/kotify/sms.db ".tables"
```
