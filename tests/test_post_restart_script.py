"""deploy/kotify-post-restart.sh 시나리오 테스트 — 재시작 후 기동 확인과 롤백.

운영 서버에서는 시험할 수 없는 롤백 경로를 가짜 환경으로 재현한다:
- 설치 디렉터리는 임시 git 저장소 (이전 커밋 → 새 커밋 체크아웃 상태)
- systemctl / pnpm / pip / flock 은 호출만 기록하는 스텁
- 헬스체크는 로컬 HTTP 서버가 "지정한 정상 커밋이 체크아웃돼 있을 때만" ok 를 낸다
"""
from __future__ import annotations

import http.server
import json
import os
import shutil
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "deploy" / "kotify-post-restart.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None,
    reason="bash·git 이 필요한 스크립트 테스트",
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture(autouse=True)
def _isolate_from_parent_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """부모 git 프로세스가 넘긴 저장소 지정 환경변수(GIT_DIR 등)를 지운다.

    링크드 워크트리에서 pre-push 훅이 돌면 git 이 GIT_DIR 을 실제 저장소의 절대
    경로로 넘긴다. 그대로 두면 임시 저장소용 git 명령(init·commit·reset --hard)이
    실제 저장소에 적용돼 브랜치가 옮겨지거나 core.bare 가 켜진다.
    """
    names = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"], check=True, capture_output=True, text=True
    ).stdout.split()
    for name in names:
        monkeypatch.delenv(name, raising=False)


_STUB = """#!/usr/bin/env bash
name=$(basename "$0")
echo "${name} $*" >> "${STUB_CALLS}"
if [[ "${name}" == "pnpm" && "${1:-}" == "build" ]]; then
    mkdir -p .next/static && echo chunk > .next/static/c.js
fi
"""


@dataclass
class Stubs:
    bin_dir: Path
    venv: Path


@pytest.fixture(scope="session")
def stubs(tmp_path_factory: pytest.TempPathFactory) -> Stubs:
    """systemctl·flock·pnpm·pip 스텁. 실행 파일 하나를 심볼릭 링크로 공유한다.

    macOS 는 새로 만든 실행 파일을 처음 실행할 때 보안 검사로 수백 ms 가 걸려,
    테스트마다 스텁을 새로 만들지 않고 세션에 한 번만 만든다.
    """
    root = tmp_path_factory.mktemp("stubs")
    stub = root / "stub"
    stub.write_text(_STUB)
    stub.chmod(0o755)
    bin_dir = root / "bin"
    venv_bin = root / "venv" / "bin"
    bin_dir.mkdir()
    venv_bin.mkdir(parents=True)
    for name in ("systemctl", "flock", "pnpm"):
        (bin_dir / name).symlink_to(stub)
    (venv_bin / "pip").symlink_to(stub)
    return Stubs(bin_dir=bin_dir, venv=root / "venv")


class _HealthServer:
    """체크아웃된 커밋이 healthy_short 와 같을 때만 정상 응답.

    fail_first 만큼의 API 요청은 기동 중인 것처럼 무조건 실패시킨다.
    """

    def __init__(self, repo: Path) -> None:
        self.healthy_short: str | None = None
        self.fail_first = 0
        self.api_requests = 0
        self.full_version = False  # 짧은 해시 대신 전체 해시를 version 으로 응답
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def do_GET(self) -> None:
                if self.path == "/healthz":
                    outer.api_requests += 1
                starting = outer.api_requests <= outer.fail_first
                current = _git(repo, "rev-parse", "--short", "HEAD")
                ok = not starting and current == outer.healthy_short
                version = _git(repo, "rev-parse", "HEAD") if outer.full_version else current
                body = json.dumps({"status": "ok" if ok else "error", "version": version})
                self.send_response(200 if ok else 503)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(body.encode())

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        ).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@dataclass
class Deploy:
    repo: Path
    prev: str
    new: str
    calls: Path
    log: Path
    db: Path
    health: _HealthServer
    env: dict[str, str]

    def short(self, sha: str) -> str:
        return _git(self.repo, "rev-parse", "--short", sha)

    def run(self, prev: str | None = None, new: str | None = None) -> int:
        result = subprocess.run(
            ["bash", str(SCRIPT), prev or self.prev, new or self.new],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.returncode

    def call_lines(self) -> list[str]:
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def log_text(self) -> str:
        return self.log.read_text() if self.log.exists() else ""


def _make_deploy(tmp_path: Path, stubs: Stubs, *, new_migration: bool) -> Deploy:
    repo = tmp_path / "install"
    (repo / "alembic" / "versions").mkdir(parents=True)
    (repo / "web").mkdir()
    (repo / "app.py").write_text("VERSION = 1\n")
    (repo / "alembic" / "versions" / "0001_init.py").write_text("# 0001\n")
    (repo / "web" / "package.json").write_text("{}\n")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "prev")
    prev = _git(repo, "rev-parse", "HEAD")

    (repo / "app.py").write_text("VERSION = 2\n")
    if new_migration:
        (repo / "alembic" / "versions" / "0002_next.py").write_text("# 0002\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "new")
    new = _git(repo, "rev-parse", "HEAD")

    calls = tmp_path / "calls.log"

    db_dir = tmp_path / "db"
    db_dir.mkdir()
    db = db_dir / "sms.db"
    db.write_text("new-data")
    (db_dir / "sms.db-wal").write_text("wal")
    (db_dir / "pre-migrate.db").write_text("old-data")

    health = _HealthServer(repo)
    env = {
        **os.environ,
        "PATH": f"{stubs.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "STUB_CALLS": str(calls),
        "KOTIFY_INSTALL_DIR": str(repo),
        "KOTIFY_VENV": str(stubs.venv),
        "KOTIFY_DB_PATH": str(db),
        "KOTIFY_DB_BACKUP": str(db_dir / "pre-migrate.db"),
        "KOTIFY_UPDATE_LOG": str(tmp_path / "update.log"),
        "KOTIFY_UPDATE_LOCK": str(tmp_path / "update.lock"),
        "KOTIFY_API_HEALTH_URL": f"{health.url}/healthz",
        "KOTIFY_WEB_HEALTH_URL": f"{health.url}/api/healthz",
        # 기본은 1회만 확인(대기 없음). 재시도 시나리오만 늘려서 쓴다.
        "KOTIFY_HEALTH_TIMEOUT_SEC": "0",
        "KOTIFY_HEALTH_INTERVAL_SEC": "0.1",
        "KOTIFY_SYSTEMCTL": str(stubs.bin_dir / "systemctl"),
        "KOTIFY_FLOCK": str(stubs.bin_dir / "flock"),
        "KOTIFY_WORKER_HOME": str(tmp_path / "home"),
    }
    return Deploy(repo, prev, new, calls, tmp_path / "update.log", db, health, env)


@pytest.fixture
def deploy(tmp_path: Path, stubs: Stubs) -> Iterator[Deploy]:
    d = _make_deploy(tmp_path, stubs, new_migration=False)
    yield d
    d.health.close()


@pytest.fixture
def migrating_deploy(tmp_path: Path, stubs: Stubs) -> Iterator[Deploy]:
    d = _make_deploy(tmp_path, stubs, new_migration=True)
    yield d
    d.health.close()


def test_healthy_deploy_keeps_new_commit(deploy: Deploy):
    deploy.health.healthy_short = deploy.short(deploy.new)

    assert deploy.run() == 0, deploy.log_text()
    assert _git(deploy.repo, "rev-parse", "HEAD") == deploy.new
    assert "systemctl restart kotify kotify-web" in deploy.call_lines()
    assert not any(c.startswith(("pnpm", "pip", "systemctl stop")) for c in deploy.call_lines())
    assert "정상 기동" in deploy.log_text()


def test_accepts_same_commit_reported_with_different_hash_length(deploy: Deploy):
    deploy.health.healthy_short = deploy.short(deploy.new)
    deploy.health.full_version = True  # 서비스 사용자 쪽 git 설정으로 해시 길이가 달라진 경우

    assert deploy.run() == 0, deploy.log_text()
    assert not any(c.startswith("systemctl stop") for c in deploy.call_lines())


def test_waits_for_slow_start_instead_of_rolling_back(deploy: Deploy):
    deploy.health.healthy_short = deploy.short(deploy.new)
    deploy.health.fail_first = 3  # 재시작 직후 몇 번은 아직 기동 중
    deploy.env["KOTIFY_HEALTH_TIMEOUT_SEC"] = "10"

    assert deploy.run() == 0, deploy.log_text()
    assert deploy.health.api_requests > 3
    assert _git(deploy.repo, "rev-parse", "HEAD") == deploy.new
    assert not any(c.startswith("systemctl stop") for c in deploy.call_lines())


def test_failed_start_rolls_back_code_and_rebuilds(deploy: Deploy):
    deploy.health.healthy_short = deploy.short(deploy.prev)  # 새 커밋만 기동 실패

    assert deploy.run() == 1, deploy.log_text()
    assert _git(deploy.repo, "rev-parse", "HEAD") == deploy.prev
    steps = [
        c for c in deploy.call_lines()
        if c.startswith(("systemctl restart", "systemctl stop", "pip", "pnpm"))
    ]
    assert steps[0] == "systemctl restart kotify kotify-web"
    assert steps[1] == "systemctl stop kotify kotify-web"
    assert steps[2].startswith("pip install -e")
    assert steps[3:5] == ["pnpm install --frozen-lockfile", "pnpm build"]
    assert steps[5] == "systemctl restart kotify kotify-web"
    assert (deploy.repo / "web" / ".next" / "standalone" / ".next" / "static" / "c.js").exists()
    # 마이그레이션 변경이 없는 배포는 DB 를 되돌리지 않는다 (그 사이 쓰인 데이터 보존).
    assert deploy.db.read_text() == "new-data"
    assert "롤백 완료" in deploy.log_text()


def test_rollback_restores_db_when_deploy_changed_migrations(migrating_deploy: Deploy):
    d = migrating_deploy
    d.health.healthy_short = d.short(d.prev)

    assert d.run() == 1, d.log_text()
    assert _git(d.repo, "rev-parse", "HEAD") == d.prev
    assert d.db.read_text() == "old-data"
    assert not Path(f"{d.db}-wal").exists()
    assert "pre-migrate 백업으로 복원" in d.log_text()


def test_failure_without_previous_commit_does_not_roll_back(deploy: Deploy):
    deploy.health.healthy_short = None

    assert deploy.run(prev=deploy.new, new=deploy.new) == 1
    assert _git(deploy.repo, "rev-parse", "HEAD") == deploy.new
    assert not any(c.startswith(("pnpm", "systemctl stop")) for c in deploy.call_lines())
    assert "되돌릴 이전 커밋이 없음" in deploy.log_text()


def test_rollback_that_still_fails_asks_for_manual_check(deploy: Deploy):
    deploy.health.healthy_short = None  # 이전 커밋도 기동 실패

    assert deploy.run() == 1
    assert _git(deploy.repo, "rev-parse", "HEAD") == deploy.prev
    assert "롤백 후에도 기동 확인 실패" in deploy.log_text()
