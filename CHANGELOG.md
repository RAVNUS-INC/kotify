# Changelog

All notable changes to kotify will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial public release as kotify (formerly internal sms-sys)
- NCP SENS SMS API integration with HMAC-SHA256 authentication
- Mass SMS dispatch with automatic 100-recipient chunking (NCP limit)
- 1,000 recipient limit per campaign (NCP API constraint)
- Korean phone number normalization (multi-format input)
- Keycloak OIDC authentication with role-based access (viewer / sender / admin)
- Background polling worker for delivery status sync
- Web-based setup wizard for first-time configuration
- Encrypted secrets storage (Fernet, no `.env` required)
- Audit logging for all sensitive actions
- Proxmox LXC bootstrap script (Debian 12/13 + Python 3.12/3.13)
- CSRF protection on all state-mutating routes
- Setup mode with IP ACL + token verification
- systemd unit with security hardening
- SQLite WAL mode for concurrent reads
- 167 unit + integration tests

### Architecture
- FastAPI + SQLAlchemy 2.0 + SQLite
- Jinja2 + HTMX (no SPA, no build step)
- Authlib + Keycloak OIDC
- asyncio polling worker
- Fernet (AES-128-CBC + HMAC-SHA256) for secrets

### Documentation
- English + Korean README
- Architecture & specification document
- E2E deployment checklist
- Contributing guide
- Security policy
- MIT License (Copyright 2026 RAVNUS Inc.)
