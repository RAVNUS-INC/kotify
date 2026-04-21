"""CSRF 보호 — 세션 기반 토큰 검증.

POST 요청의 form 필드 csrf_token 또는 헤더 X-CSRF-Token을 확인한다.
HTMX 요청은 헤더로 토큰을 전달해야 한다.

환경변수 SMS_DISABLE_CSRF=1 로 CSRF 검증을 우회할 수 있다.
이 환경변수는 테스트 전용이며 운영 환경에서 절대 설정하면 안 된다.
"""
from __future__ import annotations

import os
import secrets

from fastapi import HTTPException, Request


def get_csrf_token(request: Request) -> str:
    """세션에서 CSRF 토큰을 반환한다. 없으면 새로 생성한다.

    Args:
        request: Starlette Request.

    Returns:
        CSRF 토큰 문자열.
    """
    try:
        token = request.session.get("csrf_token")
    except AssertionError:
        return ""
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


async def verify_csrf(request: Request) -> None:
    """POST 요청의 CSRF 토큰을 검증하는 FastAPI dependency.

    form 필드 csrf_token 또는 헤더 X-CSRF-Token을 확인한다.
    일치하지 않으면 403을 반환한다.

    SMS_DISABLE_CSRF=1 환경변수가 설정되면 검증을 우회한다 (테스트 전용).

    Args:
        request: Starlette Request.

    Raises:
        HTTPException: 403 — CSRF 토큰 불일치.
    """
    # 테스트 전용 우회 — 운영 환경에서는 효과 없도록 가드.
    # SMS_DEV_MODE=true 가 아닌 상태에서 SMS_DISABLE_CSRF 가 설정돼 있으면
    # 실수 또는 공격 시도로 간주하고 에러 로그 후 일반 경로로 진행한다.
    if os.getenv("SMS_DISABLE_CSRF") == "1":
        from app.config import settings as _settings
        if _settings.dev_mode:
            return
        import logging
        logging.getLogger(__name__).error(
            "SMS_DISABLE_CSRF=1 is set but dev_mode=false — ignoring (production safety)"
        )

    if request.method != "POST":
        return

    try:
        session_token = request.session.get("csrf_token")
    except AssertionError as exc:
        # SessionMiddleware 미설치 시 Starlette가 AssertionError를 발생시킴
        raise HTTPException(status_code=403, detail="CSRF 검증 실패: 세션 없음") from exc
    if not session_token:
        raise HTTPException(status_code=403, detail="CSRF 토큰이 없습니다.")

    # 헤더 우선 확인 (HTMX)
    submitted_token = request.headers.get("X-CSRF-Token")

    if not submitted_token:
        # form 데이터에서 확인
        try:
            form_data = await request.form()
            submitted_token = form_data.get("csrf_token", "")
        except Exception:
            submitted_token = ""

    if not submitted_token or not secrets.compare_digest(session_token, submitted_token):
        raise HTTPException(status_code=403, detail="CSRF 토큰이 유효하지 않습니다.")
