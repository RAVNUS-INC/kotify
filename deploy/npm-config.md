# Nginx Proxy Manager — sms.example.com 설정 가이드

NPM(Nginx Proxy Manager)에서 kotify를 외부에 노출하는 방법입니다.

---

## 사전 확인

- NPM 관리자 화면에 접속할 수 있는 계정 준비
- Proxmox CT에 할당된 IP 주소 확인 (예: `192.168.1.100`)
- `sms.example.com` DNS가 NPM 서버 IP를 가리키고 있는지 확인

---

## 1. NPM 관리자 화면 접속

브라우저에서 NPM 관리자 URL로 접속합니다.  
(예: `http://npm-서버-IP:81`)

---

## 2. Proxy Hosts 메뉴 진입

상단 메뉴에서 **Hosts → Proxy Hosts** 클릭 후  
오른쪽 상단 **Add Proxy Host** 버튼 클릭.

---

## 3. Details 탭 설정

| 항목 | 값 |
|---|---|
| **Domain Names** | `sms.example.com` |
| **Scheme** | `http` |
| **Forward Hostname / IP** | CT의 사내망 IP (예: `192.168.1.100`) |
| **Forward Port** | `8080` |
| **Cache Assets** | **OFF** (HTMX는 동적 콘텐츠 — 캐시 비활성) |
| **Block Common Exploits** | **ON** |
| **Websockets Support** | **OFF** (본 시스템은 WebSocket 미사용) |

---

## 4. SSL 탭 설정

| 항목 | 값 |
|---|---|
| **SSL Certificate** | **Request a new SSL Certificate** |
| **Provider** | Let's Encrypt |
| **Force SSL** | **ON** |
| **HTTP/2 Support** | **ON** |
| **HSTS Enabled** | **ON** |
| **Email Address for Let's Encrypt** | 담당자 이메일 입력 |

> **주의**: Let's Encrypt 발급을 위해 `sms.example.com`이 외부에서 접근 가능해야 합니다.  
> 사내망 전용 도메인이라면 사내 CA 인증서를 사용하거나 DNS Challenge 방식을 선택하세요.

---

## 5. Advanced 탭 설정 (선택)

**Custom Nginx Configuration** 입력란에 아래 내용을 붙여넣습니다:

```nginx
client_max_body_size 10m;
proxy_read_timeout 120s;
proxy_connect_timeout 30s;
```

- `client_max_body_size 10m`: 대량 수신자 목록 붙여넣기 시 본문 크기 제한 완화
- `proxy_read_timeout 120s`: 대량 발송 요청 처리 시간 확보
- `proxy_connect_timeout 30s`: CT 연결 타임아웃

---

## 6. 저장 및 확인

**Save** 버튼 클릭.

SSL 인증서 발급에 수십 초가 소요됩니다. 완료 후:

1. 브라우저에서 `https://sms.example.com` 접속
2. Setup Wizard 화면(`/setup`)으로 자동 리다이렉트 되는지 확인
3. 주소창에 자물쇠(HTTPS) 표시 확인
4. 헬스체크 확인: `https://sms.example.com/healthz` → `{"status":"ok"}` 응답

---

## 문제 해결

| 증상 | 원인 및 해결 |
|---|---|
| 502 Bad Gateway | CT 서비스가 꺼져 있음 → `systemctl status sms` 확인 |
| SSL 발급 실패 | DNS가 NPM 서버를 가리키지 않음 → DNS 전파 대기 후 재시도 |
| 접속 불가 | CT 방화벽 또는 사내망 라우팅 확인 |
| /setup이 안 뜨고 다른 페이지 | 이미 Setup이 완료된 상태 (정상) |
