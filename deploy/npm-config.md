# Nginx Proxy Manager — sms.example.com 설정 가이드

NPM(Nginx Proxy Manager)에서 kotify를 외부에 노출하는 방법입니다.
외부에 대면하는 것은 **Next.js(포트 3000)**이며, FastAPI(포트 8080)는
Next.js 내부 `rewrites()`로만 호출되므로 외부에서 접근할 수 없습니다.

---

## 사전 확인

- NPM 관리자 화면에 접속할 수 있는 계정 준비
- Proxmox CT에 할당된 IP 주소 확인 (예: `192.168.1.100`)
- `sms.example.com` DNS가 NPM 서버 IP를 가리키고 있는지 확인
- CT에서 `kotify.service`(FastAPI)와 `kotify-web.service`(Next.js)가 모두 실행 중인지 확인:
  ```bash
  systemctl status kotify kotify-web
  ```

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
| **Forward Port** | `3000` (Next.js) |
| **Cache Assets** | **OFF** (Next.js가 자체 캐시 헤더를 관리) |
| **Block Common Exploits** | **ON** |
| **Websockets Support** | **ON** — chat SSE 스트림 및 Next.js HMR 통과용 |

> **왜 3000인가?** Next.js가 외부 대면이고 FastAPI는 Next.js의 `next.config.mjs`
> → `rewrites()` → `FASTAPI_URL` (기본 `http://localhost:8000`, 운영은 `http://127.0.0.1:8080`)을
> 통해서만 내부적으로 호출된다. NPM은 Next.js만 알면 된다.

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

## 5. Advanced 탭 설정

**Custom Nginx Configuration** 입력란에 아래 내용을 붙여넣습니다:

```nginx
client_max_body_size 10m;
proxy_read_timeout 300s;
proxy_connect_timeout 30s;

# SSE (Server-Sent Events) for /chat/* — 버퍼링 해제 필수
proxy_buffering off;
proxy_cache off;

# Next.js가 이미 X-Forwarded-* 헤더를 처리하도록 `--proxy-headers` 없이도 동작
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-Host $host;
```

- `client_max_body_size 10m`: 대량 수신자 목록 / MMS 이미지 업로드 대비
- `proxy_read_timeout 300s`: SSE 스트림 연결 유지를 위해 긴 timeout
- `proxy_buffering off` + `proxy_cache off`: SSE chunked 응답이 즉시 전달되도록 (버퍼링되면 chat 메시지가 뭉쳐서 도착)
- `X-Forwarded-*` 헤더: 뒤쪽 FastAPI에서 `ProxyHeadersMiddleware`가 원본 클라이언트 IP/Scheme을 복원

---

## 6. 저장 및 확인

**Save** 버튼 클릭.

SSL 인증서 발급에 수십 초가 소요됩니다. 완료 후:

1. 브라우저에서 `https://sms.example.com` 접속
2. (첫 배포) Setup Wizard 화면(`/setup`)으로 자동 리다이렉트 되는지 확인
3. 주소창에 자물쇠(HTTPS) 표시 확인
4. 헬스체크 확인:
   - Next.js: `https://sms.example.com/` → 200 OK (로그인 페이지 또는 대시보드)
   - FastAPI (Next.js 프록시 경유): `https://sms.example.com/api/healthz` → `{"status":"ok"}`
5. 로그인 후 `/chat/` 한 건 열어서 SSE 실시간 업데이트가 끊김 없이 도착하는지 확인 (버퍼링 이슈 감지)

---

## 문제 해결

| 증상 | 원인 및 해결 |
|---|---|
| 502 Bad Gateway (메인 페이지) | `kotify-web.service`가 꺼져 있음 → `systemctl status kotify-web` 확인 |
| 502 Bad Gateway (`/api/*`만) | `kotify.service`(FastAPI)가 꺼져 있거나 `FASTAPI_URL` 오설정 → `systemctl status kotify` + `journalctl -u kotify-web -n 30` |
| SSE 끊김 / chat 메시지 뭉침 | NPM Advanced 탭의 `proxy_buffering off` 누락 → 5번 단계 재확인 |
| SSL 발급 실패 | DNS가 NPM 서버를 가리키지 않음 → DNS 전파 대기 후 재시도 |
| 접속 불가 | CT 방화벽 또는 사내망 라우팅 확인 |
| `/setup`이 안 뜨고 다른 페이지 | 이미 Setup이 완료된 상태 (정상) |
| 로그인 후 무한 리다이렉트 | Keycloak Redirect URI가 `https://sms.example.com/auth/callback`과 정확히 일치하는지 확인 |
