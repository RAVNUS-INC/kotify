"""DB settings 테이블 접근 래퍼.

시크릿 키는 자동으로 Fernet 암호화/복호화한다.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Setting
from app.security.crypto import decrypt, encrypt
from app.security.crypto import mask as _mask


class SettingsStore:
    """settings 테이블 CRUD + 시크릿 투명 암복호화.

    Args:
        db: SQLAlchemy 세션.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    # ── 읽기 ────────────────────────────────────────────────────────────────

    def get(self, key: str, default: str | None = None) -> str | None:
        """키에 해당하는 값을 반환한다. 시크릿이면 자동 복호화한다.

        Args:
            key: 설정 키 (예: ``"ncp.access_key"``).
            default: 키가 없을 때 반환할 기본값.

        Returns:
            평문 값 또는 default.
        """
        row = self._db.execute(
            select(Setting).where(Setting.key == key)
        ).scalar_one_or_none()

        if row is None:
            return default

        if row.is_secret:
            return decrypt(row.value)
        return row.value

    def get_all_public(self) -> dict[str, str]:
        """is_secret=False 인 설정만 모두 반환한다.

        Returns:
            ``{key: value}`` 딕셔너리.
        """
        rows = self._db.execute(
            select(Setting).where(Setting.is_secret == 0)
        ).scalars().all()
        return {row.key: row.value for row in rows}

    # ── 쓰기 ────────────────────────────────────────────────────────────────

    def set(
        self,
        key: str,
        value: str,
        *,
        is_secret: bool,
        updated_by: str | None,
    ) -> None:
        """키-값을 upsert한다. is_secret=True이면 Fernet 암호화 후 저장.

        Args:
            key: 설정 키.
            value: 저장할 평문 값.
            is_secret: True이면 암호화하여 저장.
            updated_by: 변경자 users.sub (감사 목적).
        """
        stored_value = encrypt(value) if is_secret else value
        now = datetime.now(UTC).isoformat()

        row = self._db.execute(
            select(Setting).where(Setting.key == key)
        ).scalar_one_or_none()

        if row is None:
            row = Setting(
                key=key,
                value=stored_value,
                is_secret=int(is_secret),
                updated_by=updated_by,
                updated_at=now,
            )
            self._db.add(row)
        else:
            row.value = stored_value
            row.is_secret = int(is_secret)
            row.updated_by = updated_by
            row.updated_at = now

        self._db.flush()

    # ── 부트스트랩 ──────────────────────────────────────────────────────────

    def is_bootstrap_completed(self) -> bool:
        """``bootstrap.completed`` 키가 ``"true"`` 이면 True.

        Returns:
            부트스트랩 완료 여부.
        """
        value = self.get("bootstrap.completed", default="false")
        return (value or "false").lower() == "true"

    def mark_bootstrap_completed(self, updated_by: str | None = None) -> None:
        """부트스트랩 완료를 DB에 기록하고 커밋한다.

        Args:
            updated_by: 완료 처리한 users.sub.
        """
        self.set(
            "bootstrap.completed",
            "true",
            is_secret=False,
            updated_by=updated_by,
        )
        self._db.commit()

    # ── 헬퍼 ────────────────────────────────────────────────────────────────

    @staticmethod
    def mask(value: str) -> str:
        """마지막 4자리만 노출하는 마스킹 헬퍼.

        Args:
            value: 원본 시크릿 값.

        Returns:
            예: ``'****1234'``
        """
        return _mask(value)
