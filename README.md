# kotify

> Korean broadcast notification system powered by Naver Cloud Platform (NCP).

[![Tests](https://github.com/RAVNUS-INC/kotify/actions/workflows/test.yml/badge.svg)](https://github.com/RAVNUS-INC/kotify/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

A self-hostable web application for sending mass SMS announcements via NCP SENS,
built specifically for Korean phone numbers and Korean operators.

**Languages**: [English](#english) | [한국어](#한국어)

---

## English

### Features

- Mass SMS dispatch via NCP SENS API (up to 1,000 recipients per campaign)
- Keycloak OIDC authentication with role-based access (viewer / sender / admin)
- Real-time delivery status polling and history
- Korean phone number normalization (010-1234-5678, +82-10-1234-5678, etc.)
- Encrypted secrets storage (Fernet) — no `.env` file required
- Web-based setup wizard for first-time configuration
- Single-file deployment via Proxmox LXC bootstrap script
- Audit logging for all sensitive actions
- 1,000 recipient limit (NCP API constraint enforced)

### Architecture

- **Backend**: FastAPI + SQLAlchemy 2.0 + SQLite
- **Frontend**: Jinja2 + HTMX (no SPA, no build step)
- **Auth**: Authlib + Keycloak OIDC
- **Background**: asyncio polling worker (NCP delivery sync)
- **Encryption**: Fernet (AES-128-CBC + HMAC-SHA256) for secrets

### Quick Start (Development)

```bash
git clone https://github.com/RAVNUS-INC/kotify.git
cd kotify
python3.12 -m venv .venv
.venv/bin/pip install -e .
SMS_DEV_MODE=true .venv/bin/uvicorn app.main:app --reload
```

Open http://localhost:8000/setup and follow the wizard.

### Production Deployment (Proxmox LXC)

1. Create a Debian 12 or 13 LXC container (1 vCPU, 1 GB RAM, 8 GB disk)
2. Run the bootstrap script:
   ```bash
   bash <(curl -fsSL https://raw.githubusercontent.com/RAVNUS-INC/kotify/main/deploy/ct-bootstrap.sh)
   ```
3. Configure NPM (Nginx Proxy Manager) — see [deploy/npm-config.md](deploy/npm-config.md)
4. Open `https://your-domain.example.com/setup` and complete the wizard
5. Backup `/var/lib/kotify/master.key` to a secure location

See [deploy/README.md](deploy/README.md) for detailed instructions.

### Configuration

All configuration is done via the web-based setup wizard:
- NCP SENS credentials (Access Key, Secret Key, Service ID)
- Keycloak OIDC (issuer, client ID/secret)
- First admin email (must match Keycloak login email)
- Public URL

After setup, additional configuration via the `/admin/settings` page.

### Upgrading from v0.0.x

If you previously deployed with `/var/lib/sms/` paths (pre-OSS release), migrate manually:

```bash
systemctl stop sms
mv /var/lib/sms /var/lib/kotify
mv /var/log/sms /var/log/kotify
mv /var/backups/sms /var/backups/kotify
mv /opt/sms /opt/kotify
# Update systemd service and re-run bootstrap or install kotify.service manually
```

### Documentation

- [Architecture & Specification](claudedocs/SPEC.md)
- [E2E Deployment Checklist](claudedocs/E2E-CHECKLIST.md)
- [NCP SENS Research Notes](claudedocs/ncp-research.md)
- [Deployment Guide](deploy/README.md)

### Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome.

### License

MIT — see [LICENSE](LICENSE).

---

## 한국어

### 주요 기능

- NCP SENS를 활용한 단체 SMS 발송 (캠페인당 최대 1,000명)
- Keycloak OIDC 인증 + 역할 기반 권한 (viewer / sender / admin)
- 실시간 발송 결과 폴링 및 이력 관리
- 한국 휴대폰 번호 자동 정규화 (다양한 형식 지원)
- 시크릿 암호화 저장 (Fernet) — `.env` 파일 불필요
- 웹 기반 첫 설정 마법사
- Proxmox LXC 부트스트랩 스크립트로 단일 파일 배포
- 모든 민감 작업 감사 로깅
- 1,000명 제한 (NCP API 제약 강제)

### 빠른 시작 (개발)

```bash
git clone https://github.com/RAVNUS-INC/kotify.git
cd kotify
python3.12 -m venv .venv
.venv/bin/pip install -e .
SMS_DEV_MODE=true .venv/bin/uvicorn app.main:app --reload
```

http://localhost:8000/setup 에 접속하여 마법사를 진행하세요.

### Proxmox 배포

[deploy/README.md](deploy/README.md) 참고. CT(Debian 12/13)에서 한 줄 부트스트랩.

### 라이선스

MIT — 자유롭게 사용/수정/배포 가능. 단, copyright 표기 보존 필수.

`Copyright (c) 2026 RAVNUS Inc.`
