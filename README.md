# 사내 SMS 공지 시스템

NCP SENS SMS v2 API 기반 사내 문자 공지 발송 시스템.

운영자가 웹 UI에서 다수 인원에게 SMS/LMS 공지를 발송하고, 발송 이력과 NCP 수신결과를 영구 보관·조회합니다.

## 빠른 시작 (개발 환경)

### 방법 A — uv 사용 (권장)

```bash
uv sync
SMS_DEV_MODE=true uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

### 방법 B — 표준 venv 사용

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e .
SMS_DEV_MODE=true .venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

`SMS_DEV_MODE=true` 로 실행하면 DB와 마스터 키를 `./var/` 아래에 생성합니다.

### 마이그레이션

```bash
uv run alembic upgrade head
```

### 테스트

```bash
uv run pytest tests/test_text.py tests/test_codes.py -v
```

## 배포 (운영 환경)

Proxmox LXC CT(Debian 12)에 systemd 서비스로 배포합니다.

```bash
# CT root 콘솔에서
bash <(curl -fsSL https://raw.githubusercontent.com/RAVNUS-INC/sms-sys/main/deploy/ct-bootstrap.sh)
```

상세 절차: [deploy/README.md](deploy/README.md)

## E2E 검증

운영 시작 전 단계별 검증 절차: [claudedocs/E2E-CHECKLIST.md](claudedocs/E2E-CHECKLIST.md)

## 사용자 작성 영역

이 시스템은 다음 두 파일을 **직접 구현**해야 합니다 (스텁 제공, 테스트 포함):

| 파일 | 내용 | 테스트 |
|---|---|---|
| `app/ncp/signature.py` | NCP SENS API HMAC-SHA256 서명 생성 | `tests/test_signature.py` |
| `app/util/phone.py` | 전화번호 정규화 (`010-1234-5678` → `01012345678`) | `tests/test_phone.py` |

구현 후 테스트로 검증:

```bash
uv run pytest tests/test_signature.py tests/test_phone.py -v
```

## 구성

- **스택**: Python 3.12 + FastAPI + Jinja2 + HTMX + SQLite + Authlib(Keycloak OIDC)
- **시크릿**: `.env` 없음. 마스터 키(`/var/lib/sms/master.key`) + DB Fernet 암호화
- **첫 실행**: `/setup` wizard에서 Keycloak/NCP 설정 후 자동 폐쇄

자세한 내용은 [명세서](claudedocs/SPEC.md)를 참조하세요.
