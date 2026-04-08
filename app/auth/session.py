"""세션 미들웨어 설정 — itsdangerous 기반 Starlette SessionMiddleware.

session secret은 DB settings에서 읽는다.
부트스트랩 전엔 임시 키를 사용한다 (재시작 시 세션 무효화).
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.orm import Session

# 임시 키 (메모리 기반, 재시작 시 무효화)
_FALLBACK_SECRET = os.urandom(32).hex()


def get_fallback_secret() -> str:
    """임시 폴백 시크릿을 반환한다 (외부에서 _FALLBACK_SECRET 직접 접근 대신 사용)."""
    return _FALLBACK_SECRET


def get_session_secret(db: "Session") -> str:
    """DB에서 session.secret을 읽어 반환한다.

    설정이 없으면 메모리 기반 임시 키를 반환한다.

    Args:
        db: SQLAlchemy 세션.

    Returns:
        세션 서명에 사용할 비밀 키 문자열.
    """
    from app.security.settings_store import SettingsStore

    store = SettingsStore(db)
    secret = store.get("session.secret")
    return secret if secret else _FALLBACK_SECRET


def add_session_middleware(app: "FastAPI", secret_key: str) -> None:
    """FastAPI 앱에 SessionMiddleware를 추가한다.

    Args:
        app: FastAPI 인스턴스.
        secret_key: 세션 서명 키.
    """
    from starlette.middleware.sessions import SessionMiddleware

    app.add_middleware(
        SessionMiddleware,
        secret_key=secret_key,
        session_cookie="sms_session",
        max_age=60 * 60 * 8,  # 8시간
        same_site="lax",
        https_only=not settings.dev_mode,  # 운영: HTTPS 전용, 개발: HTTP 허용
    )
