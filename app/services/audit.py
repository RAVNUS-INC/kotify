"""감사 로그 서비스.

모든 중요 액션을 audit_logs 테이블에 기록한다.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog

# ── 액션 상수 ────────────────────────────────────────────────────────────────
LOGIN = "LOGIN"
LOGOUT = "LOGOUT"
SEND = "SEND"
CALLER_CREATE = "CALLER_CREATE"
CALLER_UPDATE = "CALLER_UPDATE"
CALLER_DELETE = "CALLER_DELETE"
CALLER_DEFAULT = "CALLER_DEFAULT"
SETTINGS_UPDATE = "SETTINGS_UPDATE"
SETUP_COMPLETED = "SETUP_COMPLETED"
BOOTSTRAP_INIT = "BOOTSTRAP_INIT"


def log(
    db: Session,
    actor_sub: str | None,
    action: str,
    target: str | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
) -> None:
    """감사 로그를 기록한다.

    주의: 이 함수는 db.flush()만 수행한다.
    호출자가 반드시 db.commit()을 호출해야 감사 로그가 저장됨.

    Args:
        db: SQLAlchemy 세션.
        actor_sub: 행위자 users.sub. 시스템 액션이면 None.
        action: 액션 상수 (LOGIN, SEND 등).
        target: 대상 리소스 식별자 (예: "campaign:42").
        detail: 추가 정보 딕셔너리 (JSON 직렬화됨).
        ip: 요청 IP 주소.
    """
    detail_json: str | None = None
    if detail is not None:
        detail_json = json.dumps(detail, ensure_ascii=False)

    entry = AuditLog(
        actor_sub=actor_sub,
        action=action,
        target=target,
        detail=detail_json,
        ip=ip,
        created_at=datetime.now(UTC).isoformat(),
    )
    db.add(entry)
    db.flush()
