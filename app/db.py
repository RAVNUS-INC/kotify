"""SQLAlchemy 2.0 엔진·세션·Base 설정.

WAL 모드를 활성화하여 읽기/쓰기 동시성을 확보한다.
"""
from __future__ import annotations

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """모든 ORM 모델의 기반 클래스."""


def _apply_wal(dbapi_conn: object, connection_record: object) -> None:  # noqa: ARG001
    """새 SQLite 연결마다 WAL 모드 + 외래 키 활성화."""
    cursor = dbapi_conn.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_db_engine(db_url: str | None = None) -> Engine:
    """엔진을 생성하고 WAL 이벤트 리스너를 붙인다.

    SQLite 파일의 부모 디렉토리가 없으면 자동 생성한다 (dev mode 첫 실행 시
    ``./var/`` 가 없으면 OperationalError가 발생하는 문제 방지).

    ``hide_parameters=True`` — SQLAlchemy 예외 문구와 SQL 로그에 바인딩 값을 넣지 않는다.
    값에는 고객 번호·회신 본문·웹훅 원문이 있고, ``log.exception`` 이 예외 문구를 그대로
    남긴다(운영 stderr.log). SQL 문과 DB 오류 메시지는 그대로 남는다.

    Args:
        db_url: 명시하지 않으면 ``settings.db_url`` 사용.
    """
    url = db_url or settings.db_url
    # SQLite 파일 경로의 부모 디렉토리 보장
    if url.startswith("sqlite:///"):
        from pathlib import Path
        db_file = Path(url.removeprefix("sqlite:///"))
        db_file.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        url, connect_args={"check_same_thread": False}, hide_parameters=True
    )
    event.listen(engine, "connect", _apply_wal)
    return engine


engine: Engine = create_db_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db():
    """FastAPI 의존성 — 요청당 세션 하나를 생성하고 종료 시 닫는다."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
