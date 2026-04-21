# kotify

> Korean broadcast notification system powered by U+ msghub (RCS-first with SMS/LMS/MMS auto-fallback).

[![Tests](https://github.com/RAVNUS-INC/kotify/actions/workflows/test.yml/badge.svg)](https://github.com/RAVNUS-INC/kotify/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Node 20+](https://img.shields.io/badge/node-20+-green.svg)](https://nodejs.org/)

A self-hostable web application for sending mass RCS/SMS announcements via U+ msghub,
built specifically for Korean phone numbers and Korean operators.

**Languages**: [English](#english) | [한국어](#한국어)

---

## English

### Features

- **RCS-first messaging** via U+ msghub with SMS/LMS/MMS auto-fallback (`fbInfoLst`), up to 1,000 recipients per campaign
  - RCS 양방향 (8원) → SMS (9원) for short text
  - RCS LMS (27원) → LMS (27원) for long text
  - RCS image template (40원) → MMS (85원) for images — 53% cost saving
- **Webhook-based delivery reports** — no polling required, real-time updates
- **Keycloak OIDC** authentication with role-based access (viewer / sender / admin)
- Korean phone number normalization (010-1234-5678, +82-10-1234-5678, etc.)
- Encrypted secrets storage (Fernet) — no `.env` file required
- Web-based setup wizard for first-time configuration
- Proxmox LXC single-container deployment (FastAPI + Next.js coresident)
- Audit logging for all sensitive actions
- One-click system update from admin settings

### Architecture

- **Backend**: FastAPI + SQLAlchemy 2.0 + SQLite (WAL), Python 3.12+
- **Frontend**: Next.js 14 (App Router, RSC-first) + TypeScript + Tailwind, Node 20+
  - `/api/*` is rewritten to FastAPI via `next.config.mjs`; frontend never talks to backend URLs directly
  - Radix UI primitives (Dialog, Drawer, Command Palette)
  - Motion primitives with a 1.2s budget (Counter / Sparkline / AnimatedBars / Progress / Rise)
- **Auth**: Authlib + Keycloak OIDC (2-tier guard: middleware + layout session check)
- **Messaging**: U+ msghub API (RCS + SMS/LMS/MMS fallback) with JWT auth & SHA512 hashing
- **Encryption**: Fernet (AES-128-CBC + HMAC-SHA256) for secrets

### Quick Start (Development)

Backend (FastAPI):

```bash
git clone https://github.com/RAVNUS-INC/kotify.git
cd kotify
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
SMS_DEV_MODE=true .venv/bin/uvicorn app.main:app --reload --port 8000
```

Frontend (Next.js) in a second terminal:

```bash
cd web
pnpm install
pnpm dev     # http://localhost:3000
```

Open <http://localhost:3000> and follow the Setup Wizard (dev mode uses `./var/` for data).

### Production Deployment (Proxmox LXC)

1. Create a Debian 12 or 13 LXC container (1 vCPU, 1 GB RAM, 8 GB disk)
2. Run the bootstrap script:
   ```bash
   bash <(curl -fsSL https://raw.githubusercontent.com/RAVNUS-INC/kotify/main/deploy/ct-bootstrap.sh)
   ```
   — installs Python 3.12/3.13, Node 20, pnpm, builds Next.js, installs `kotify.service` (FastAPI) and `kotify-web.service` (Next.js).
3. Configure NPM (Nginx Proxy Manager) — see [`deploy/npm-config.md`](deploy/npm-config.md)
4. Open `https://your-domain.example.com` and complete the Setup Wizard
5. Backup `/var/lib/kotify/master.key` to a secure location (1Password etc.)

See [`deploy/README.md`](deploy/README.md) for detailed instructions.

### Configuration

All configuration is done via the web-based Setup Wizard:
- **msghub API credentials** (API Key / API Password / JWT 자동 관리)
- **RCS settings** (Brand ID, Chatbot ID — 사전 등록된 상태 가정)
- **Keycloak OIDC** (issuer, client ID/secret)
- **First admin email** (must match Keycloak login email)
- **Public URL** (`https://sms.example.com`)

After setup, additional configuration via the `/settings` page.

### Documentation

- [Architecture & Specification](claudedocs/SPEC.md)
- [E2E Deployment Checklist](claudedocs/E2E-CHECKLIST.md)
- [msghub API Guide](claudedocs/msghub-api-guide.md)
- [msghub Error Codes](claudedocs/msghub-error-codes.md)
- [Motion Timing Matrix](claudedocs/motion-timing.md) (Phase 10c)
- [Web Bundle Snapshot](claudedocs/web-bundle-snapshot.md) (Phase 10b)
- [Deployment Guide](deploy/README.md)

### Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Issues and PRs welcome.

### License

MIT — see [LICENSE](LICENSE).

---

## 한국어

### 주요 기능

- **RCS 우선 발송**: U+ msghub를 통한 RCS/SMS/LMS/MMS 자동 fallback (캠페인당 최대 1,000명)
  - RCS 양방향(8원) → SMS(9원) 폴백 (단문)
  - RCS LMS(27원) → LMS(27원) (장문)
  - RCS 이미지 템플릿(40원) → MMS(85원) (이미지, **53% 절감**)
- **웹훅 기반 실시간 결과 수신** — 폴링 불필요
- Keycloak OIDC 인증 + 역할 기반 권한 (viewer / sender / admin)
- 한국 휴대폰 번호 자동 정규화 (다양한 형식 지원)
- 시크릿 암호화 저장 (Fernet) — `.env` 파일 불필요
- 웹 기반 첫 설정 마법사
- Proxmox LXC 단일 컨테이너 배포 (FastAPI + Next.js 공존)
- 모든 민감 작업 감사 로깅

### 빠른 시작 (개발)

백엔드 (FastAPI):

```bash
git clone https://github.com/RAVNUS-INC/kotify.git
cd kotify
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
SMS_DEV_MODE=true .venv/bin/uvicorn app.main:app --reload --port 8000
```

프론트엔드 (Next.js, 별도 터미널):

```bash
cd web
pnpm install
pnpm dev     # http://localhost:3000
```

<http://localhost:3000> 접속 후 Setup Wizard 진행.

### Proxmox 배포

[`deploy/README.md`](deploy/README.md) 참고. CT(Debian 12/13)에서 한 줄 부트스트랩으로 Python + Node + Next.js 빌드 + 두 systemd 서비스까지 자동 구성.

### 라이선스

MIT — 자유롭게 사용/수정/배포 가능. 단, copyright 표기 보존 필수.

`Copyright (c) 2026 RAVNUS Inc.`
