# Changelog

All notable changes to kotify will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **U+ msghub 연동**: RCS 양방향 CHAT 우선 발송 + SMS/LMS/MMS 자동 fallback
- **웹훅 기반 리포트 수신**: 폴링 제거, 실시간 발송 결과 반영
- **RCS 양방향 대화방 UI**: MO(수신) 웹훅 처리 및 대화 이력 관리
- **DashForge `classic-plus` 테마**: 전 페이지 UI 전면 교체
- **관리자 원클릭 시스템 업데이트**: 실시간 진행 표시 + 자동 완료 감지
- **예약 발송**: msghub 예약 API 연동 + UI에서 취소 지원
- **MMS 이미지 전처리**: Pillow 기반 포맷/해상도/품질 자동 조정 (RCS/MMS 공용)
- **RCS 양방향 24h 세션 과금 상한 반영**
- Keycloak OIDC 인증 + 역할 기반 권한 (viewer / sender / admin)
- 한국 휴대폰 번호 자동 정규화
- 시크릿 암호화 저장 (Fernet) — `.env` 불필요
- 웹 기반 첫 설정 마법사
- Proxmox LXC 부트스트랩 스크립트
- CSRF 보호, 감사 로깅, systemd 보안 하드닝
- SQLite WAL 모드
- 194 단위/통합 테스트

### Changed
- **NCP SENS → U+ msghub 전면 교체** (NCP 코드 전량 삭제)
- 발송 청크 크기: 100 → 10 (msghub 제약)
- 메시지 식별자: `message_id` → `cli_key` + `msg_key`
- DB 모델: `NcpRequest` → `MsghubRequest`
- 폴링 워커 제거 → 웹훅 기반 리포트로 전환

### Architecture
- FastAPI + SQLAlchemy 2.0 + SQLite (WAL)
- Jinja2 + HTMX + DashForge `classic-plus` (no SPA, no build step)
- Authlib + Keycloak OIDC
- U+ msghub (JWT 인증 + SHA512 이중 해싱)
- Fernet (AES-128-CBC + HMAC-SHA256) for secrets

### Documentation
- English + Korean README
- msghub API 가이드 및 에러 코드 레퍼런스
- 배포 가이드 (`deploy/README.md`)
- Contributing 가이드
- Security policy
- MIT License (Copyright 2026 RAVNUS Inc.)
