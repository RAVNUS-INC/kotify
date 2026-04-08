# 사내 SMS 공지 시스템

NCP SENS SMS v2 API 기반 사내 문자 공지 발송 시스템.

운영자가 웹 UI에서 다수 인원에게 SMS/LMS 공지를 발송하고, 발송 이력과 NCP 수신결과를 영구 보관·조회합니다.

## 빠른 시작

### 의존성 설치

```bash
uv sync
```

### 개발 서버 실행

```bash
# WAL 모드 SQLite를 ./var/에 생성
SMS_DEV_MODE=true uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

### 마이그레이션

```bash
uv run alembic upgrade head
```

### 테스트

```bash
uv run pytest tests/test_text.py tests/test_codes.py -v
```

## 구성

- **스택**: Python 3.12 + FastAPI + Jinja2 + HTMX + SQLite + Authlib(Keycloak OIDC)
- **시크릿**: `.env` 없음. 마스터 키(`/var/lib/sms/master.key`) + DB Fernet 암호화
- **첫 실행**: `/setup` wizard에서 Keycloak/NCP 설정 후 자동 폐쇄

자세한 내용은 [명세서](claudedocs/SPEC.md)를 참조하세요.
