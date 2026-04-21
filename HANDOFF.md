# Handoff: kotify 현재 상태

> 최종 업데이트: 2026-04-22
> 상태: **NCP → msghub 마이그레이션 완료, UI 전면 교체 완료**

---

## 현재 상태 한눈에 보기

- NCP SENS → U+ msghub 전환: **완료**
- RCS 우선 발송 + SMS/LMS/MMS fallback: **완료**
- 웹훅 기반 리포트 수신 (폴링 제거): **완료**
- RCS 양방향 CHAT UI + MO 웹훅: **완료**
- DashForge 테마 기반 UI 전면 교체: **완료**
- 테스트: **194 passing / 0 failing**

## 주요 마일스톤 (시간 역순)

| 시점 | 내용 |
|------|------|
| 2026-04 후반 | DashForge 테마(`classic-plus`)로 UI 전면 교체, 22개 페이지 재이식 |
| 2026-04 중반 | msghub xms/* endpoint + v11 delivery report 반영, RCS fallback 체인 강화 |
| 2026-04 초반 | RCS 양방향 CHAT UI + MO 웹훅 수신, 관리자 원클릭 시스템 업데이트 |
| 2026-03 후반 | NCP 코드 전량 삭제, msghub 발송 서비스 리라이트, UI 전면 교체 |
| 2026-03 중반 | msghub TokenManager(JWT), MsghubClient(SMS/LMS/MMS/RCS) 구현 |

## 아키텍처 스냅샷

- **Backend**: FastAPI + SQLAlchemy 2.0 + SQLite (WAL)
- **Frontend**: Jinja2 + HTMX (no SPA) + DashForge classic-plus 테마
- **Auth**: Authlib + Keycloak OIDC (viewer / sender / admin)
- **Messaging**: U+ msghub API — RCS 양방향 CHAT + SMS/LMS/MMS fallback
- **Delivery Report**: 웹훅 수신 (`routes/webhook.py` + `services/report.py`)
- **Encryption**: Fernet (AES-128-CBC + HMAC-SHA256)

## 디렉토리 안내

- `app/msghub/` — TokenManager, MsghubClient, schemas, codes
- `app/services/compose.py` — 발송 디스패치 (RCS 우선, fbInfoLst 자동 fallback)
- `app/services/report.py` — 웹훅 결과 처리
- `app/services/image.py` — RCS용 이미지 전처리
- `app/routes/webhook.py` — msghub 웹훅 수신 엔드포인트

## 알려진 후속 아이디어 (스코프 밖)

- 첨부 BLOB 보관 정책: 캠페인 COMPLETED 후 24h 뒤 삭제 (현재 미구현)
- RCS 비용/채널 대시보드 고도화

## 관련 문서

- [SPEC.md](claudedocs/SPEC.md) — 아키텍처/스펙
- [E2E-CHECKLIST.md](claudedocs/E2E-CHECKLIST.md) — 배포 체크리스트
- [msghub-api-guide.md](claudedocs/msghub-api-guide.md) — msghub 순수 API 레퍼런스
- [msghub-migration-spec.md](claudedocs/msghub-migration-spec.md) — 마이그레이션 원본 기획서 (히스토리용)
