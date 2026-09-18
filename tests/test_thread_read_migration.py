"""0019는 관측 가능한 서버 수신 prefix만 읽음으로 이전하며 caller별 기존 행을 보존한다."""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine

from alembic import command

_ROOT = Path(__file__).resolve().parents[1]


def _config():
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "alembic"))
    return cfg


def _run(conn, direction):
    module = ScriptDirectory.from_config(_config()).get_revision("0019").module
    with Operations.context(MigrationContext.configure(conn)):
        getattr(module, direction)()


def test_migration_0019_is_single_head_after_0018():
    scripts = ScriptDirectory.from_config(_config())
    assert scripts.get_heads() == ["0019"]
    assert scripts.get_revision("0019").down_revision == "0018"


def test_backfill_uses_server_arrival_and_conservative_prefix_preserving_callers():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE thread_reads (id INTEGER PRIMARY KEY, caller TEXT NOT NULL, "
                             "phone TEXT NOT NULL, read_at TEXT NOT NULL, "
                             "CONSTRAINT uq_thread_reads_caller_phone UNIQUE(caller,phone))")
        conn.exec_driver_sql("CREATE TABLE mo_messages (id INTEGER PRIMARY KEY, mo_number TEXT, "
                             "mo_recv_dt TEXT, received_at TEXT)")
        conn.exec_driver_sql("INSERT INTO thread_reads VALUES (?, ?, ?, ?)", [
            (1, "caller-a", "phone-a", "2026-06-01T02:00:00+00:00"),
            (2, "caller-b", "phone-a", "2026-06-01T00:30:00+00:00"),
            (3, "caller-a", "phone-b", "2026-06-01T02:00:00+00:00"),
            (4, "caller-a", "phone-c", "2026-06-01T02:00:00+00:00"),
            (5, "caller-a", "phone-d", "N/A"),
            (6, "caller-a", "phone-empty", "2026-06-01T02:00:00+00:00"),
        ])
        conn.exec_driver_sql("INSERT INTO mo_messages VALUES (?, ?, ?, ?)", [
            (1, "phone-a", "20260601090000", "2026-06-01T00:00:00Z"),
            (2, "phone-b", "20260601090000", "2026-06-01T00:00:00+00:00"),
            (3, "phone-a", "20260601100000", "2026-06-01T01:00:00+00:00"),
            # 발신 원본은 어제지만 읽은 뒤 수신된 행은 읽음으로 이전하지 않는다.
            (4, "phone-a", "20260501090000", "2026-06-01T03:00:00+00:00"),
            # DB ID와 수신 시각이 역순이어도 id=5를 건너뛰어 id=6까지 읽지 않는다.
            (5, "phone-b", "20260601120000", "2026-06-01T03:00:00+00:00"),
            (6, "phone-b", "20260601100000", "2026-06-01T01:00:00+00:00"),
            (7, "phone-c", "20260601090000", "N/A"),
            (8, "phone-c", "20260601100000", "2026-06-01T01:00:00+00:00"),
            (9, "phone-d", "20260601090000", "2026-06-01T00:00:00+00:00"),
        ])
        original = list(conn.exec_driver_sql("SELECT * FROM thread_reads ORDER BY id"))
        _run(conn, "upgrade")
        assert list(conn.exec_driver_sql("SELECT last_read_mo_id FROM thread_reads ORDER BY id").scalars()) == [3, 1, 2, 0, 0, 0]
        assert list(conn.exec_driver_sql("SELECT id, caller, phone, read_at FROM thread_reads ORDER BY id")) == original
        assert "idx_thread_reads_phone" in [row[1] for row in conn.exec_driver_sql("PRAGMA index_list(thread_reads)")]
        _run(conn, "downgrade")
        assert list(conn.exec_driver_sql("SELECT * FROM thread_reads ORDER BY id")) == original
        assert "last_read_mo_id" not in [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(thread_reads)")]
        _run(conn, "upgrade")
        assert list(conn.exec_driver_sql("SELECT last_read_mo_id FROM thread_reads ORDER BY id").scalars()) == [3, 1, 2, 0, 0, 0]
    engine.dispose()


def test_full_migration_chain_upgrades_and_downgrades_on_temporary_database(tmp_path, monkeypatch):
    from app.config import settings

    db_path = tmp_path / "migration.db"
    monkeypatch.setattr(settings, "db_path", db_path)
    cfg = _config()
    command.upgrade(cfg, "head")
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0019"
        assert "last_read_mo_id" in [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(thread_reads)")]
    command.downgrade(cfg, "0018")
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == "0018"
        assert "last_read_mo_id" not in [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(thread_reads)")]
    command.upgrade(cfg, "head")
    engine.dispose()
