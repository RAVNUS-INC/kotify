"""공통 pytest fixture — in-memory SQLite, fake settings 등."""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

# 개발 모드 강제 (테스트 중 var/ 디렉토리 사용)
os.environ.setdefault("SMS_DEV_MODE", "true")

# CSRF 검증 우회 — 테스트 전용. 운영 환경에서 절대 설정 금지.
os.environ.setdefault("SMS_DISABLE_CSRF", "1")

from datetime import UTC

from app.db import Base
from app.models import Caller, User

# ── DB Fixture ───────────────────────────────────────────────────────────────


@pytest.fixture(scope="function")
def db_engine():
    """인메모리 SQLite 엔진 (함수 스코프 — 테스트마다 초기화)."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    def _apply_wal(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    event.listen(engine, "connect", _apply_wal)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def session_factory(db_engine):
    """SessionMaker (함수 스코프)."""
    return sessionmaker(bind=db_engine, autocommit=False, autoflush=False)


@pytest.fixture(scope="function")
def db_session(session_factory):
    """SQLAlchemy 세션 (함수 스코프)."""
    session: Session = session_factory()
    yield session
    session.close()


# ── 마스터 키 Fixture ─────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def setup_master_key(tmp_path, monkeypatch):
    """테스트 중 마스터 키를 tmp_path에 생성."""
    key_path = tmp_path / "master.key"
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    key_path.write_bytes(key)

    # lru_cache 초기화
    from app.security import crypto
    crypto.get_fernet.cache_clear()

    monkeypatch.setattr("app.config.settings.master_key_path", key_path)
    monkeypatch.setattr("app.security.crypto.settings", MagicMock(master_key_path=key_path))

    yield key_path

    crypto.get_fernet.cache_clear()


# ── 사용자/발신번호 Fixture ───────────────────────────────────────────────────


@pytest.fixture
def sample_user(db_session):
    """테스트용 사용자."""
    from datetime import datetime
    user = User(
        sub="test-sub-001",
        email="test@example.com",
        name="테스트 사용자",
        roles=json.dumps(["sender", "admin"]),
        created_at=datetime.now(UTC).isoformat(),
        last_login_at=datetime.now(UTC).isoformat(),
    )
    db_session.add(user)
    db_session.commit()
    return user


@pytest.fixture
def sample_caller(db_session):
    """테스트용 발신번호."""
    from datetime import datetime
    caller = Caller(
        number="0212345678",
        label="대표번호",
        active=1,
        is_default=1,
        created_at=datetime.now(UTC).isoformat(),
    )
    db_session.add(caller)
    db_session.commit()
    return caller
