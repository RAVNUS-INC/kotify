# E2E 검증 체크리스트

운영 시작 전 단계별로 수행해야 할 검증 절차입니다.  
각 단계를 순서대로 진행하고, 완료 시 `[x]`로 체크하세요.

---

## 1. NCP 사전 준비

> 발신번호 등록은 영업일 3-4일이 소요됩니다. **가장 먼저** 진행하세요.

- [ ] NCP 콘솔에서 SENS Project 생성
- [ ] serviceId 확보 (형식 예: `ncp:sms:kr:XXXXXXXXXX:sens`)
- [ ] Sub Account에서 Access Key + Secret Key 발급
- [ ] 발신번호 등록 신청: `02-1234-5678`, `02-1234-5678`, `02-1234-5678`
- [ ] 영업일 3-4일 후 발신번호 승인 확인 (NCP 콘솔 → SENS → 발신번호 관리)

---

## 2. Keycloak 사전 준비

- [ ] Realm `sms-sys` 생성
- [ ] Client `sms-sys` 생성 (Access Type: Confidential, Standard Flow Enabled: ON)
- [ ] Client Secret 메모 (Credentials 탭)
- [ ] Valid Redirect URIs에 추가: `https://sms.example.com/auth/callback`
- [ ] Client Roles 생성: `viewer`, `sender`, `admin`
- [ ] 본인 사용자 계정에 역할 미사전 할당 (Setup Wizard 완료 시 첫 로그인한 계정에 `admin` 자동 부여됨)

---

## 3. CT 배포

- [ ] Proxmox에서 CT 생성: Debian 12, 1 vCPU, 1 GB RAM, 8 GB disk
- [ ] CT 네트워크 설정: 사내망 고정 IP 할당
- [ ] 아웃바운드 허용 확인: `sens.apigw.ntruss.com:443`, Keycloak 서버, NTP
- [ ] CT root 콘솔 접속
- [ ] 부트스트랩 스크립트 실행:
  ```bash
  bash /opt/sms/deploy/ct-bootstrap.sh
  ```
- [ ] 스크립트 완료 후 systemd 상태 확인:
  ```bash
  systemctl status sms
  ```
- [ ] 헬스체크 통과 확인:
  ```bash
  curl http://127.0.0.1:8080/healthz
  # 기대값: {"status":"ok"}
  ```
- [ ] setup.token 메모:
  ```bash
  cat /var/lib/sms/setup.token
  ```

---

## 4. NPM 설정

- [ ] NPM 관리자 화면에서 Proxy Host 추가 (`deploy/npm-config.md` 참고)
- [ ] Domain: `sms.example.com`, Forward: `<CT IP>:8080`
- [ ] Let's Encrypt SSL 인증서 발급 완료
- [ ] Force SSL ON 확인
- [ ] 헬스체크 HTTPS 확인:
  ```
  https://sms.example.com/healthz → 200 OK, {"status":"ok"}
  ```

---

## 5. Setup Wizard

- [ ] `https://sms.example.com` 접속 → `/setup`으로 자동 리다이렉트 확인
- [ ] Step 1: setup.token 입력 → 검증 성공 확인
- [ ] Step 2: Keycloak 정보 입력 (Issuer URL, Client ID, Client Secret) → "연결 테스트" 성공
- [ ] Step 3: NCP 정보 입력 (Access Key, Secret Key, Service ID) → "인증 테스트" 성공
- [ ] Step 4: 발신번호 목록 확인 (02-1234-5678, 02-1234-5678, 02-1234-5678)
- [ ] Step 5: Keycloak 로그인 (본인 계정)
- [ ] 로그인 후 Dashboard 진입 확인
- [ ] 본인 계정에 `admin` 역할 자동 부여 확인 (Keycloak 콘솔 또는 `/admin` 접근 가능 여부)
- [ ] `/var/lib/sms/setup.token` 파일이 자동 삭제되었는지 확인:
  ```bash
  ls /var/lib/sms/setup.token  # "No such file" 이어야 함
  ```
- [ ] `/setup` 재접근 시 404 응답 확인

---

## 6. master.key 백업

- [ ] `/var/lib/sms/master.key` 내용을 안전한 위치에 백업:
  ```bash
  cat /var/lib/sms/master.key
  ```
  → 1Password, 사내 비밀 저장소 등 **DB와 분리된** 위치에 저장
- [ ] 백업 위치를 팀 내에 문서화 (담당자 2명 이상 접근 가능하도록)

---

## 7. 사용자 작성 영역 구현

이 시스템은 아래 두 파일을 **사용자가 직접 구현**해야 합니다 (스텁 제공됨):

- [ ] `app/ncp/signature.py` — NCP SENS API HMAC-SHA256 서명 생성 구현
  ```bash
  .venv/bin/pytest tests/test_signature.py -v
  # 모든 테스트 통과 확인
  ```
- [ ] `app/util/phone.py` — 전화번호 정규화 함수 구현
  ```bash
  .venv/bin/pytest tests/test_phone.py -v
  # 모든 테스트 통과 확인
  ```
- [ ] 구현 후 서비스 재시작:
  ```bash
  systemctl restart sms
  systemctl status sms
  ```

---

## 8. 첫 발송 테스트

- [ ] `/compose` 페이지 진입
- [ ] 수신자: 본인 휴대폰 번호 1개 입력 (예: `010-XXXX-XXXX`)
- [ ] 발신번호: 등록된 번호 중 하나 선택
- [ ] 본문: `테스트 발송입니다.`
- [ ] 미리보기 확인: 유형 `SMS`, 바이트 수 ~26 B 확인
- [ ] "발송하기" 클릭
- [ ] 본인 휴대폰에서 문자 수신 확인
- [ ] `/campaigns` 에서 캠페인 상태 `COMPLETED` + `success` 카운트 확인
- [ ] `/admin/audit` 에서 `SEND` 감사 로그 확인

---

## 9. 실패 케이스 검증

- [ ] 잘못된 번호 포함 발송 시도:
  - 수신자에 `010-0000-0000` (잘못된 형식) 입력
  - 발송 전 차단 또는 에러 메시지 표시 확인
- [ ] NCP 인증 오류 시뮬레이션:
  - `/admin/settings`에서 `NCP Secret Key`를 임의 값으로 변경
  - 발송 시도 → 503 에러 + 친절한 안내 메시지 확인
  - Secret Key 원복 후 재발송 성공 확인

---

## 10. 백업 검증

- [ ] 백업 스크립트 수동 실행:
  ```bash
  sudo -u sms /opt/sms/deploy/sms-backup.sh
  ```
- [ ] 백업 파일 생성 확인:
  ```bash
  ls -lh /var/backups/sms/
  # sms-YYYYMMDD.db 파일 존재 확인
  ```
- [ ] 파일 크기 > 0 확인:
  ```bash
  du -h /var/backups/sms/sms-$(date +%Y%m%d).db
  ```
- [ ] (분기 1회 권장) 별도 CT에서 백업 복원 후 데이터 동일성 확인:
  ```bash
  # 별도 CT에서
  cp sms-YYYYMMDD.db /var/lib/sms/sms.db
  systemctl start sms
  # 이력 조회, 로그인 등 정상 동작 확인
  ```

---

## 11. 모니터링 설정

- [ ] logrotate 설정으로 로그 파일 회전:
  ```bash
  cat > /etc/logrotate.d/sms << 'EOF'
  /var/log/sms/*.log {
      daily
      rotate 30
      compress
      delaycompress
      missingok
      notifempty
      postrotate
          systemctl kill -s USR1 sms || true
      endscript
  }
  EOF
  ```
- [ ] systemctl status 정기 확인 또는 외부 모니터링 연동 (Uptime Kuma 등):
  - 모니터링 대상: `https://sms.example.com/healthz`
  - 기대 응답: HTTP 200, `{"status":"ok"}`
- [ ] 알림 채널 설정 (서비스 다운 시 담당자에게 통보)

---

## 체크리스트 완료 기준

위 11개 섹션의 모든 항목이 체크된 상태에서:

- 본인 번호로 SMS 1회 이상 정상 수신
- `/admin/audit` 에 발송 이력 기록
- 백업 파일 정상 생성
- master.key 안전하게 보관 완료

위 4가지가 확인되면 운영 시작 가능합니다.
