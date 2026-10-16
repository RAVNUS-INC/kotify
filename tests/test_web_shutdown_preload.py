"""deploy/kotify-web-shutdown.cjs 테스트 — kotify-web 종료 유예 preload.

운영 Next(14.2 standalone)의 SIGTERM 처리 `server.close(() => process.exit(0))` 를 그대로
흉내 낸 작은 node 서버에 preload 를 붙여, 끝나지 않는 SSE 연결이 열려 있어도 유예 뒤
정상 종료(0)하는지, 열린 연결이 없으면 유예를 기다리지 않는지, 다른 SIGTERM 처리기가
없는 자식 node 는 원래대로 바로 죽는지 확인한다.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
PRELOAD = DEPLOY / "kotify-web-shutdown.cjs"
INSTALLED_PRELOAD = "/usr/local/lib/kotify/kotify-web-shutdown.cjs"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node 가 필요한 preload 테스트")

# Next 14.2.35 start-server.js 의 종료 처리와 같은 형태. /sse 는 응답을 끝내지 않는다.
NEXT_LIKE_SERVER = """
const http = require('http');
const server = http.createServer((req, res) => {
  if (req.url === '/sse') {
    res.writeHead(200, {'content-type': 'text/event-stream'});
    res.write('event: ping\\ndata: .\\n\\n');
    return;
  }
  res.end('ok');
});
server.listen(0, '127.0.0.1', () => console.log('port=' + server.address().port));
process.on('SIGTERM', () => server.close(() => process.exit(0)));
"""

# SIGTERM 처리기가 없는 자식 node(NODE_OPTIONS 로 preload 만 상속).
PLAIN_CHILD = "console.log('port=0'); setInterval(() => {}, 1000);"


@pytest.fixture
def run_node(tmp_path: Path) -> Iterator:
    procs: list[subprocess.Popen[str]] = []

    def start(source: str, grace_ms: int) -> tuple[subprocess.Popen[str], int]:
        script = tmp_path / f"server{len(procs)}.js"
        script.write_text(source)
        proc = subprocess.Popen(
            ["node", f"--require={PRELOAD}", str(script)],
            stdout=subprocess.PIPE,
            text=True,
            env={**os.environ, "KOTIFY_WEB_SHUTDOWN_GRACE_MS": str(grace_ms)},
        )
        procs.append(proc)
        assert proc.stdout is not None
        match = re.match(r"port=(\d+)", proc.stdout.readline())
        assert match, "node 서버가 기동하지 않음"
        return proc, int(match.group(1))

    yield start
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
        proc.wait()


def _open_sse(port: int) -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    sock.sendall(b"GET /sse HTTP/1.1\r\nHost: localhost\r\n\r\n")
    assert b"200" in sock.recv(1024)
    return sock


def test_open_sse_is_cut_after_grace_and_exits_zero(run_node) -> None:
    proc, port = run_node(NEXT_LIKE_SERVER, grace_ms=400)
    sse = _open_sse(port)
    started = time.monotonic()
    proc.send_signal(signal.SIGTERM)

    assert proc.wait(timeout=5) == 0
    elapsed = time.monotonic() - started
    assert 0.3 <= elapsed < 3, elapsed
    # 남아 있던 SSE 연결은 끊겼다(EOF 또는 RST).
    try:
        rest = sse.recv(1024)
        while rest:
            rest = sse.recv(1024)
    except ConnectionResetError:
        pass
    sse.close()


def test_new_connections_are_refused_during_grace(run_node) -> None:
    proc, port = run_node(NEXT_LIKE_SERVER, grace_ms=2000)
    sse = _open_sse(port)
    proc.send_signal(signal.SIGTERM)
    time.sleep(0.3)

    assert proc.poll() is None  # 아직 유예 중
    with pytest.raises(ConnectionRefusedError):
        socket.create_connection(("127.0.0.1", port), timeout=1)
    assert proc.wait(timeout=5) == 0
    sse.close()


def test_without_open_connections_exits_without_waiting_for_grace(run_node) -> None:
    proc, _port = run_node(NEXT_LIKE_SERVER, grace_ms=10_000)
    started = time.monotonic()
    proc.send_signal(signal.SIGTERM)

    assert proc.wait(timeout=5) == 0
    assert time.monotonic() - started < 2


def test_child_without_sigterm_handler_keeps_default_termination(run_node) -> None:
    proc, _port = run_node(PLAIN_CHILD, grace_ms=10_000)
    started = time.monotonic()
    proc.send_signal(signal.SIGTERM)

    assert proc.wait(timeout=5) == -signal.SIGTERM
    assert time.monotonic() - started < 2


def test_unit_and_bootstrap_use_out_of_repo_copy() -> None:
    unit = (DEPLOY / "kotify-web.service").read_text()
    bootstrap = (DEPLOY / "ct-bootstrap.sh").read_text()

    assert f"Environment=NODE_OPTIONS=--require={INSTALLED_PRELOAD}" in unit
    assert INSTALLED_PRELOAD in bootstrap
    # 안전망 TimeoutStopSec 는 기본 유예(5초)보다 길어야 preload 가 먼저 정상 종료한다.
    timeout = re.search(r"^TimeoutStopSec=(\d+)$", unit, re.MULTILINE)
    default_grace = re.search(r"DEFAULT_GRACE_MS = (\d+);", PRELOAD.read_text())
    assert timeout and default_grace
    assert int(timeout.group(1)) * 1000 > int(default_grace.group(1))
