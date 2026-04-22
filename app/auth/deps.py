"""FastAPI 의존성 — 인증/권한 검사.

세션에서 사용자 정보를 읽어 DB upsert하고,
라우트에서 require_user / require_role / require_setup_complete 등으로 사용한다.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User

if TYPE_CHECKING:
    pass


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def parse_user_roles(user: User | None) -> list[str]:
    """user.roles JSON 문자열을 list로 파싱한다. 실패 시 빈 list 반환.

    Args:
        user: User ORM 객체 또는 None.

    Returns:
        역할 이름 list.
    """
    if not user or not user.roles:
        return []
    try:
        return json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        return []


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


# 역할 우선순위 — 높은 권한이 앞. 대표 role 산정, UI 표시 순서 등
# 공용 기준으로 쓴다. `require_role` 의 권한 체크 자체는 여전히 평면적
# intersection 이지만, "대표 역할"이 필요한 곳은 이 순서로 판정.
ROLE_PRIORITY: tuple[str, ...] = ("owner", "admin", "sender", "operator", "viewer")


def primary_role(roles_json: str | None, default: str = "viewer") -> str:
    """User.roles(JSON array) → 대표 role. 배열이 비었거나 매칭 없음은 default.

    파싱 실패(None, malformed JSON)도 default 로 graceful fallback.
    """
    if not roles_json:
        return default
    try:
        arr = json.loads(roles_json)
    except (json.JSONDecodeError, TypeError):
        return default
    if not isinstance(arr, list):
        return default
    role_set = set(arr)
    for r in ROLE_PRIORITY:
        if r in role_set:
            return r
    return default


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
    """부트스트랩이 이미 완료된 경우 404 반환 (setup 라우트 보호용).

    이전 버전은 IP ACL(사설망/loopback만 허용)도 적용했으나,
    NPM 같은 reverse proxy 뒤에서 --proxy-headers와 결합 시 진짜 클라이언트 IP가
    외부 IP로 인식되어 정당한 운영자도 차단되는 catch-22가 발생.

    setup.token(128-bit hex)이 단일 보안 메커니즘이며, 다음 조건들이 함께
    방어층을 이룬다:
    - bootstrap 완료 후 영구 비활성 (이 함수의 첫 체크)
    - setup.token 파일은 600 권한 (CT 콘솔/SSH 접근 필요)
    - 부트스트랩 완료 시 토큰 파일 자동 삭제
    - NPM 앞단에서 외부 인바운드 차단 가능 (운영자 책임)

    Args:
        request: Starlette Request.
        db: SQLAlchemy 세션.

    Raises:
        HTTPException: 404 — 이미 설정 완료됨.
    """
    from app.security.settings_store import SettingsStore

    store = SettingsStore(db)
    if store.is_bootstrap_completed():
        raise HTTPException(status_code=404, detail="Not Found")
