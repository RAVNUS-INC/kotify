"""Alembic 환경 설정.

app.config.settings에서 DB URL을 읽어 주입하므로 alembic.ini에
sqlalchemy.url을 하드코딩하지 않는다.
"""
from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# app 패키지에서 Base와 settings를 import
from app.config import settings
from app.db import Base

# alembic.ini 로거 설정 적용
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 마이그레이션 대상 메타데이터
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """'오프라인' 모드 — 실제 DB 연결 없이 SQL 생성."""
    url = settings.db_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite ALTER TABLE 지원
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """'온라인' 모드 — 실제 DB 연결로 마이그레이션 실행."""
    # alembic.ini의 sqlalchemy.url 대신 settings에서 주입
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = settings.db_url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite ALTER TABLE 지원
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
