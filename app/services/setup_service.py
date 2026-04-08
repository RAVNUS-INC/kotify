"""Setup wizard 서비스.

토큰 생성/검증과 초기 설정 저장을 담당한다.
"""
from __future__ import annotations

import hmac
import secrets
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.models import User
from app.security.settings_store import SettingsStore
from app.services import audit


def generate_setup_token(path: Path) -> str:
    """16 바이트 hex 토큰을 생성하고 600 권한 파일로 저장한다.

    이미 파일이 있으면 그대로 읽어 반환한다.

    Args:
        path: 토큰 파일 경로.

    Returns:
        hex 토큰 문자열 (32자).
    """
    if path.exists():
        return path.read_text().strip()

    token = secrets.token_hex(16)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token)
    path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
    return token


def verify_setup_token(path: Path, provided: str) -> bool:
    """상수시간 비교로 토큰을 검증한다.

    Args:
        path: 토큰 파일 경로.
        provided: 사용자가 제출한 토큰.

    Returns:
        일치하면 True.
    """
    if not path.exists():
        return False
    stored = path.read_text().strip()
    return hmac.compare_digest(stored, provided.strip())


def delete_setup_token(path: Path) -> None:
    """토큰 파일을 삭제한다.

    Args:
        path: 토큰 파일 경로.
    """
    if path.exists():
        path.unlink()


def complete_setup(
    db: Session,
    settings_payload: dict[str, Any],
    first_admin_sub: str,
    token_path: Path,
) -> None:
    """설정을 일괄 저장하고 부트스트랩을 완료 처리한다.

    1. settings 일괄 저장
    2. bootstrap.completed=true
    3. 첫 admin user upsert with role=admin
    4. setup token 삭제
    5. 감사 로그 기록

    Args:
        db: SQLAlchemy 세션.
        settings_payload: {key: (value, is_secret)} 딕셔너리.
        first_admin_sub: 첫 admin 사용자의 Keycloak sub.
        token_path: setup token 파일 경로.
    """
    store = SettingsStore(db)

    # session.secret 자동 생성 (없으면)
    if "session.secret" not in settings_payload:
        import secrets as _secrets
        session_secret = _secrets.token_hex(32)
        settings_payload["session.secret"] = (session_secret, True)

    for key, val in settings_payload.items():
        if isinstance(val, tuple):
            value, is_secret = val
        else:
            value, is_secret = val, False
        store.set(key, value, is_secret=is_secret, updated_by=first_admin_sub)

    store.mark_bootstrap_completed(first_admin_sub)

    # 첫 admin user upsert
    now = datetime.now(UTC).isoformat()
    import json
    user = db.get(User, first_admin_sub)
    if user is None:
        user = User(
            sub=first_admin_sub,
            email=settings_payload.get("first_admin_email", ("", False))[0] if isinstance(settings_payload.get("first_admin_email"), tuple) else "",
            name="Admin",
            roles=json.dumps(["admin"]),
            created_at=now,
            last_login_at=now,
        )
        db.add(user)
    else:
        existing_roles = json.loads(user.roles)
        if "admin" not in existing_roles:
            existing_roles.append("admin")
        user.roles = json.dumps(existing_roles)

    db.flush()

    # 감사 로그
    audit.log(
        db,
        actor_sub=first_admin_sub,
        action=audit.SETUP_COMPLETED,
        detail={"keys_saved": list(settings_payload.keys())},
    )
    db.commit()

    # 토큰 삭제
    delete_setup_token(token_path)
