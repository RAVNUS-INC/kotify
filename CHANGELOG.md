# Changelog

All notable changes to kotify will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **U+ msghub integration** (replaces NCP SENS completely)
  - JWT authentication with SHA512 double-hashing (`app/msghub/auth.py`)
  - TokenManager with asyncio.Lock stampede prevention + auto-renewal
  - Unified client for SMS / LMS / MMS / RCS bidirectional + `fbInfoLst` fallback
  - Error taxonomy, rate table, cost calculation (`app/msghub/codes.py`)
  - Webhook endpoint (`/webhook/msghub/report`, `/webhook/msghub/mo`) — no polling
- **Next.js 14 web frontend** (replaces Jinja2 + HTMX)
  - App Router with RSC-first architecture, `'use client'` only on stateful leaves
  - `typedRoutes: true` for typesafe navigation
  - Route groups `(app)` / `(auth)` with middleware + layout two-tier guard
  - URL state over client state (searchParams for filter/selected/q)
  - Radix Dialog-based Drawer + Command Palette (⌘K)
  - SSE chat stream with exponential backoff
  - Korean IME composition handling on Enter
- **Motion design system** with 1.2s budget
  - Primitives: Counter / Sparkline (useDrawOn) / AnimatedBars / Progress / Rise / Stagger / PulseDot
  - `useReducedMotion()` hook — all primitives jump to final state under `prefers-reduced-motion: reduce`
  - Timing matrix documented in `claudedocs/motion-timing.md`
- **Accessibility**
  - jsx-a11y/strict preset (Phase 10a)
  - tabular-nums on Counter values to prevent layout shift
  - ARIA: `role="img"` + `aria-label` on Sparkline, `role="status"` on toasts
- **Performance**
  - `@next/bundle-analyzer` gated by `ANALYZE=true` (Phase 10b)
  - Shared chunks ~87 kB, per-page first-load ~127 kB
- **CSV formula injection defense** (CWE-1236) — `app/util/csv_safe.py` with `safe_csv_cell`
- **Keycloak OIDC** with role-based access (viewer / sender / admin)
- **Web-based Setup Wizard** for first-time configuration (msghub credentials, RCS brand, Keycloak)
- **Encrypted secrets storage** (Fernet, no `.env`)
- **Audit logging** for all sensitive actions with `actor / action / target / detail` schema
- **Proxmox LXC bootstrap** (Debian 12/13 + Python 3.12/3.13 + Node 20 + pnpm)
- **systemd hardening** — `NoNewPrivileges`, `ProtectSystem=strict`, `ReadWritePaths` minimal

### Removed

- **NCP SENS SMS integration** (전량 삭제) — `app/ncp/*`, HMAC-SHA256 signature, 100-chunk splitting logic
- **Background polling worker** (`app/services/poller.py`) — replaced by msghub webhooks
- **Jinja2 + HTMX templates** — replaced by Next.js

### Architecture

- Backend: FastAPI + SQLAlchemy 2.0 + SQLite (WAL mode)
- Frontend: Next.js 14 (App Router) + TypeScript + Tailwind CSS
- Auth: Authlib + Keycloak OIDC
- Messaging: U+ msghub (webhook-based)
- Secrets: Fernet (AES-128-CBC + HMAC-SHA256)
- Deployment: Proxmox LXC (FastAPI 8080 + Next.js 3000, NPM fronts Next.js)

### Documentation

- English + Korean README
- Architecture & specification document (`SPEC.md`)
- E2E deployment checklist
- msghub API guide, error codes, template API, UX change log
- Motion timing matrix + web bundle snapshot (Phase 10b/10c)
- Contributing guide, Security policy
- MIT License (Copyright 2026 RAVNUS Inc.)
