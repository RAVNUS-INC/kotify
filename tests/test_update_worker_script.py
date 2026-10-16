"""deploy/kotify-update-worker.sh 실패 롤백 — DB 는 마이그레이션 뒤 실패에만, 서비스를 멈춘 뒤 복원(M1).

pip·sqlite3·runuser(alembic)·pnpm·systemd-run 은 호출만 기록하는 스텁이다. 실제 systemctl·DB 는 건드리지 않는다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_post_restart_script import _git, _isolate_from_parent_git  # noqa: F401 — autouse fixture

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "kotify-update-worker.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="bash·git 이 필요한 스크립트 테스트",
)

_STUB = """#!/usr/bin/env bash
name=$(basename "$0")
printf '%s' "${name}" >> "${STUB_CALLS}"; printf ' %q' "$@" >> "${STUB_CALLS}"; echo >> "${STUB_CALLS}"
if [[ " ${STUB_FAIL:-} " == *" ${name} "* ]]; then exit 7; fi
if [[ "${name}" == "sqlite3" ]]; then echo backup > "${KOTIFY_DB_BACKUP}"; fi
if [[ "${name}" == "pnpm" && "${1:-}" == "build" ]]; then
    mkdir -p .next/static && echo chunk > .next/static/c.js
fi
"""


def _setup(tmp_path: Path, fail: str) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    venv_bin = tmp_path / "venv" / "bin"
    bin_dir.mkdir()
    venv_bin.mkdir(parents=True)
    stub = tmp_path / "stub"
    stub.write_text(_STUB)
    stub.chmod(0o755)
    for name in ("sqlite3", "runuser", "pnpm", "systemd-run"):
        (bin_dir / name).symlink_to(stub)
    (venv_bin / "pip").symlink_to(stub)

    repo = tmp_path / "install"
    (repo / "web").mkdir(parents=True)
    (repo / "app.py").write_text("1\n")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "prev")
    (repo / "app.py").write_text("2\n")
    _git(repo, "commit", "-qam", "new")

    db = tmp_path / "sms.db"
    db.write_text("live")
    calls = tmp_path / "calls.log"
    env = {
        **os.environ,
        "KOTIFY_TEST_PATH": str(bin_dir),
        "STUB_CALLS": str(calls),
        "STUB_FAIL": fail,
        "KOTIFY_INSTALL_DIR": str(repo),
        "KOTIFY_VENV": str(tmp_path / "venv"),
        "KOTIFY_DB_PATH": str(db),
        "KOTIFY_DB_BACKUP": str(tmp_path / "pre-migrate.db"),
        "KOTIFY_SYSTEMD_RUN": str(bin_dir / "systemd-run"),
    }
    return env, calls, db


def _run(env) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60)


def test_failure_before_migration_does_not_touch_db(tmp_path: Path):
    env, calls, db = _setup(tmp_path, fail="pip")
    result = _run(env)

    assert result.returncode != 0
    assert db.read_text() == "live"
    assert "systemd-run" not in calls.read_text()  # 복원 예약 없음


def test_failure_after_migration_restores_db_after_stopping_api(tmp_path: Path):
    env, calls, db = _setup(tmp_path, fail="runuser")  # alembic upgrade 실패
    result = _run(env)

    assert result.returncode != 0
    assert db.read_text() == "live"  # worker 는 도는 DB 를 직접 덮지 않는다
    [restore] = [line for line in calls.read_text().splitlines() if line.startswith("systemd-run")]
    assert "--unit=kotify-db-restore-" in restore
    script = restore.split("/bin/bash -c ", 1)[1]
    assert script.index("systemctl\\ stop\\ kotify") < script.index("cp\\ -f")
    assert script.index("cp\\ -f") < script.index("systemctl\\ start\\ kotify")


def test_build_failure_after_migration_also_restores(tmp_path: Path):
    env, calls, _db = _setup(tmp_path, fail="pnpm")
    assert _run(env).returncode != 0
    assert "kotify-db-restore-" in calls.read_text()
