# Contributing to kotify

Thanks for your interest in contributing!

kotify has two runtimes — **FastAPI backend** (Python) and **Next.js frontend** (TypeScript).
Set up both when working on full-stack changes.

---

## Setup

### Backend (FastAPI)

```bash
git clone https://github.com/RAVNUS-INC/kotify.git
cd kotify
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

### Frontend (Next.js)

```bash
cd web
pnpm install
pnpm typecheck
pnpm lint
pnpm build
```

### Running both in dev

Two terminals:

```bash
# Terminal 1 — FastAPI
SMS_DEV_MODE=true .venv/bin/uvicorn app.main:app --reload --port 8000

# Terminal 2 — Next.js
cd web && pnpm dev
```

Open <http://localhost:3000>. Frontend proxies `/api/*` to the backend via `next.config.mjs`.

---

## Code Style

### Python

- Python 3.12+ syntax (`X | Y`, `type` statements, etc.)
- Type hints required on all public functions
- `ruff check` + `ruff format` before committing
- Korean and English comments both welcome

### TypeScript / React

- TypeScript strict mode; no `any` in new code
- Server Components by default, `'use client'` only on stateful leaves
- `eslint-config-next` + `jsx-a11y/strict` — run `pnpm lint` before commit
- Prefer URL state (`searchParams`) over client state for filters
- Tailwind utility classes with CSS-variable pass-through (`bg-brand` → `var(--brand)`)

### Commits

- Conventional-style but Korean OK (`feat:`, `fix:`, `chore:`, `refactor:`)
- Reference Phase number if applicable (e.g., `Phase 10c`)
- **No AI/Claude attribution in commit messages, PRs, or any git artefact**

---

## Testing

### Backend

- All new features must include tests (`pytest tests/`)
- Use `respx` for HTTP mocking (msghub client)
- Run `pytest` before submitting PR; coverage should not regress

### Frontend

- `pnpm typecheck` must pass (TS compile)
- `pnpm lint` must pass (ESLint + jsx-a11y/strict)
- `pnpm build` must succeed (Next.js production build catches a wider class of errors)
- Motion timing changes → update `claudedocs/motion-timing.md`

---

## Pull Request Process

1. Fork the repo
2. Create a feature branch (`feat/…`, `fix/…`)
3. Make your changes with tests
4. Run the full verification matrix:
   - Backend: `pytest`
   - Frontend: `pnpm typecheck && pnpm lint && pnpm build`
5. Ensure every check passes
6. Open a PR with clear description and any motion/bundle/a11y impact noted

---

## Reporting Issues

Use GitHub Issues. Include:
- Steps to reproduce
- Expected vs actual behavior
- Environment (OS, Python version, Node version, browser)
- Relevant logs (sanitized — no secrets)

---

## Security

For security vulnerabilities, please follow [`SECURITY.md`](SECURITY.md) instead of opening a public issue.
