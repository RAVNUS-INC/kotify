"""정보성 페이지 라우트 — 도움말(/help), 내 프로필(/me)."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.auth.deps import require_setup_complete, require_user
from app.models import User
from app.web import templates

router = APIRouter()


@router.get("/help", response_class=HTMLResponse)
async def help_center(
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """kotify 사용 도움말."""
    try:
        user_roles = json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        user_roles = []
    return templates.TemplateResponse(
        request,
        "help.html",
        {"user": user, "user_roles": user_roles},
    )


@router.get("/me", response_class=HTMLResponse)
async def my_profile(
    request: Request,
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """현재 로그인한 사용자의 프로필/세션 정보."""
    try:
        user_roles = json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        user_roles = []
    return templates.TemplateResponse(
        request,
        "me.html",
        {"user": user, "user_roles": user_roles},
    )
