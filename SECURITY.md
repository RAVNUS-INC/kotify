# Security Policy

## Supported Versions

kotify is in early development. Only the latest `main` branch receives security updates.

| Version | Supported |
| ------- | --------- |
| `main`  | ✅        |
| < 0.1   | ❌        |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

If you discover a security vulnerability in kotify, please report it privately:

1. Open a [GitHub Security Advisory](https://github.com/RAVNUS-INC/kotify/security/advisories/new) (preferred)
2. Or email the maintainers directly

Please include:
- A description of the vulnerability
- Steps to reproduce
- Affected versions / commits
- Potential impact
- Suggested mitigation (if any)

We will acknowledge your report within **72 hours** and provide an estimated timeline for a fix.

## Disclosure Policy

After a fix is merged and released:
- A public security advisory will be published on GitHub
- Credit will be given to the reporter (unless anonymity is requested)
- A CVE may be requested for significant vulnerabilities

## Security Best Practices for Operators

When deploying kotify:

1. **Master key**: Back up `/var/lib/kotify/master.key` to a secure location separate from the database. Loss of this file means loss of all encrypted secrets (msghub credentials, Keycloak client secret).
2. **msghub credentials**: Rotate API Key/Password periodically. Restrict source IP ranges in the msghub portal where possible.
3. **Network isolation**: Run kotify in an internal network only. Use Nginx Proxy Manager (or similar) for TLS termination; only expose Next.js (port 3000) externally — FastAPI (8080) stays internal.
4. **Setup token**: Treat the contents of `/var/lib/kotify/setup.token` as a one-time secret. Never share it via chat/email/screenshots.
5. **Time sync**: msghub JWT requires accurate server time. Ensure NTP (`systemd-timesyncd`) is active.
6. **Backups**: Encrypt backups at rest. Never include `master.key` in automatic backup tarballs.
7. **Updates**: Subscribe to repository releases for security patches. One-click update path is available via `/settings` → System.
8. **CSV exports**: The CSV generator applies formula-injection defense (CWE-1236) via `safe_csv_cell`, but treat exported files as potentially sensitive — store in encrypted locations.

## Known Security Considerations

- kotify stores all secrets encrypted at rest using Fernet (AES-128-CBC + HMAC-SHA256)
- Session cookies use `HttpOnly`, `Secure` (in production), and `SameSite=Lax`
- All state-mutating Next.js server actions and FastAPI POST routes are protected by CSRF tokens (SameSite + explicit token where needed)
- msghub delivery reports arrive via signed webhooks — verify the signature header before trusting payload
- Setup wizard is restricted to local/private network IPs by default (NPM-level ACL recommended as a second layer)
- The frontend never talks to FastAPI URLs directly — all backend calls go through the Next.js `/api/*` rewrite, reducing CORS surface to zero
