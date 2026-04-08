"""FastAPI 의존성 — 인증/권한 검사.

세션에서 사용자 정보를 읽어 DB upsert하고,
라우트에서 require_user / require_role / require_setup_complete 등으로 사용한다.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from starlette.responses import RedirectResponse

from app.db import get_db
from app.models import User

if TYPE_CHECKING:
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    """세션에서 사용자 정보를 읽어 DB upsert 후 반환한다.

    세션에 사용자 정보가 없으면 None 반환.

    Args:
        request: Starlette Request.
        db: SQLAlchemy 세션.

    Returns:
        User 또는 None.
    """
    sub = request.session.get("user_sub")
    if not sub:
        return None

    email = request.session.get("user_email", "")
    name = request.session.get("user_name", "")
    # #29: user_roles는 list로 직접 저장됨 — 타입 안전 처리
    roles_raw = request.session.get("user_roles", [])
    if isinstance(roles_raw, list):
        roles = roles_raw
    else:
        try:
            roles = json.loads(roles_raw)
        except (json.JSONDecodeError, TypeError):
            roles = []

    roles_json = json.dumps(roles, ensure_ascii=False)
    now = _now_iso()

    # upsert
    user = db.get(User, sub)
    if user is None:
        user = User(
            sub=sub,
            email=email,
            name=name,
            roles=roles_json,
            created_at=now,
            last_login_at=now,
        )
        db.add(user)
    else:
        user.email = email
        user.name = name
        user.roles = roles_json
        user.last_login_at = now

    db.commit()
    return user


def require_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """로그인된 사용자가 없으면 /auth/login 으로 리다이렉트.

    Args:
        request: Starlette Request.
        db: SQLAlchemy 세션.

    Returns:
        현재 User.

    Raises:
        HTTPException: 303 — /auth/login 으로 리다이렉트.
    """
    user = get_current_user(request, db)
    if user is None:
        raise HTTPException(
            status_code=303,
            headers={"Location": "/auth/login"},
        )
    return user


def require_role(*roles: str) -> Callable:
    """지정된 역할 중 하나 이상을 가진 사용자만 허용하는 의존성 팩토리.

    Usage:
        @router.get("/compose", dependencies=[Depends(require_role("sender", "admin"))])

    Args:
        *roles: 허용할 역할 이름들 (하나라도 일치하면 통과).

    Returns:
        FastAPI 의존성 함수.
    """
    allowed = set(roles)

    def _check(
        request: Request,
        db: Session = Depends(get_db),
    ) -> User:
        user = require_user(request, db)
        try:
            user_roles = set(json.loads(user.roles))
        except (json.JSONDecodeError, TypeError):
            user_roles = set()

        if not user_roles.intersection(allowed):
            raise HTTPException(status_code=403, detail="권한이 없습니다.")
        return user

    return _check


def require_setup_complete(
    request: Request,
    db: Session = Depends(get_db),
) -> None:
    """부트스트랩이 완료되지 않은 경우 /setup 으로 리다이렉트.

    Args:
        request: Starlette Request.
        db: SQLAlchemy 세션.

    Raises:
        HTTPException: 303 — /setup 으로 리다이렉트.
    """
    from app.security.settings_store import SettingsStore

    store = SettingsStore(db)
    if not store.is_bootstrap_completed():
        raise HTTPException(
            status_code=303,
            headers={"Location": "/setup"},
        )


def _is_private_network(ip: str) -> bool:
    """IP 주소가 사설망 또는 루프백인지 확인한다."""
    import ipaddress
    try:
        addr = ipaddress.ip_address(ip)
        return addr.is_private or addr.is_loopback
    except ValueError:
        return False


_ALLOWED_SETUP_HOSTS = {"127.0.0.1", "::1", "localhost"}


def require_setup_mode(
    request: Request,
    db: Session = Depends(get_db),
) -> None:
    """부트스트랩이 이미 완료됐거나 외부 IP인 경우 404 반환 (setup 라우트 보호용).

    Args:
        request: Starlette Request.
        db: SQLAlchemy 세션.

    Raises:
        HTTPException: 404 — 이미 설정 완료됨 또는 외부 IP.
    """
    from app.security.settings_store import SettingsStore

    store = SettingsStore(db)
    if store.is_bootstrap_completed():
        raise HTTPException(status_code=404, detail="Not Found")

    client_ip = request.client.host if request.client else None
    if client_ip and client_ip not in _ALLOWED_SETUP_HOSTS and not _is_private_network(client_ip):
        raise HTTPException(status_code=404, detail="Not Found")
