"""PBX 받은 팩스 PDF 를 읽기 전용 SFTP 로 가져온다.

PBX 에는 받은 팩스 PDF 를 내려받는 API·웹 경로가 없어(2026-10-16 확인) kotify 전용
읽기 전용 SFTP 계정으로 파일 하나씩 가져온다. 시스템 OpenSSH ``sftp`` 를 쓴다(새 Python
의존성 없음).

- 키: ``/var/lib/kotify/pbx_sftp_ed25519`` (600, kotify 소유). 서비스는 ``ProtectHome=true``
  라 ``~/.ssh`` 를 쓸 수 없어 키와 ``known_hosts`` 를 데이터 디렉터리에 둔다.
- 호스트 키는 ``/var/lib/kotify/pbx_known_hosts`` 에 고정하고 ``StrictHostKeyChecking=yes``.
- 파일 이름은 ``fax-in-<숫자>.<숫자>.pdf`` 만 허용하고, 목록 조회 없이 그 파일만 ``get``.
- 로그에는 sftp 의 출력(경로가 들어 있을 수 있음)을 남기지 않고 종료 코드만 남긴다.

설정 키 (SettingsStore, 모두 plain):
- ``pbx.sftp_user`` : 계정 이름. 비어 있으면 가져오기 기능 off
- ``pbx.sftp_host`` : 기본은 ``pbx.api_base_url`` 의 호스트
- ``pbx.sftp_port`` : 기본 55530
- ``pbx.sftp_dir``  : PBX 쪽 받은 팩스 폴더(chroot 면 chroot 기준), 기본 ``/var/lib/vitalpbx/fax/recvd``
"""
from __future__ import annotations

import asyncio
import logging
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app.config import settings
from app.pbx.client import DEFAULT_API_BASE_URL
from app.security.settings_store import SettingsStore

log = logging.getLogger(__name__)

INBOX_FILE = re.compile(r"^fax-in-\d+\.\d+\.pdf$")
_SAFE_DIR = re.compile(r"^/[A-Za-z0-9_./-]*$")
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_.-]+$")
DEFAULT_PORT = "55530"
DEFAULT_DIR = "/var/lib/vitalpbx/fax/recvd"
TIMEOUT_SECONDS = 30
MAX_BYTES = 20 * 1024 * 1024


class SftpError(Exception):
    """가져오기 실패. ``code``: not_configured | bad_name | timeout | failed | too_large | not_pdf."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class SftpConfig:
    user: str
    host: str
    port: str
    directory: str
    key_path: Path
    known_hosts: Path


def data_dir() -> Path:
    return settings.db_path.parent


def load_sftp_config(db: Session) -> SftpConfig | None:
    """설정에서 SFTP 접속 정보를 읽는다. 계정이 없거나 값이 안전하지 않으면 None."""
    store = SettingsStore(db)
    user = (store.get("pbx.sftp_user", "") or "").strip()
    if not user:
        return None
    base = (store.get("pbx.api_base_url", "") or "").strip() or DEFAULT_API_BASE_URL
    host = (store.get("pbx.sftp_host", "") or "").strip() or (urlsplit(base).hostname or "")
    port = (store.get("pbx.sftp_port", "") or "").strip() or DEFAULT_PORT
    directory = (store.get("pbx.sftp_dir", "") or "").strip().rstrip("/") or DEFAULT_DIR
    if not (
        _SAFE_TOKEN.fullmatch(user)
        and _SAFE_TOKEN.fullmatch(host)
        and port.isdigit()
        and _SAFE_DIR.fullmatch(directory)
        and ".." not in directory
    ):
        log.warning("PBX SFTP 설정 값이 올바르지 않아 가져오기를 건너뜀")
        return None
    return SftpConfig(
        user=user,
        host=host,
        port=port,
        directory=directory,
        key_path=data_dir() / "pbx_sftp_ed25519",
        known_hosts=data_dir() / "pbx_known_hosts",
    )


def _command(config: SftpConfig) -> list[str]:
    return [
        "sftp",
        "-q",
        "-F", "/dev/null",
        "-i", str(config.key_path),
        "-o", "BatchMode=yes",
        "-o", "IdentitiesOnly=yes",
        "-o", "StrictHostKeyChecking=yes",
        "-o", f"UserKnownHostsFile={config.known_hosts}",
        "-o", "ConnectTimeout=10",
        "-P", config.port,
        "-b", "-",
        f"{config.user}@{config.host}",
    ]


async def fetch_inbox_pdf(config: SftpConfig, file_name: str) -> bytes:
    """받은 팩스 PDF 하나를 가져온다. 이름·크기·PDF 시그니처를 검사한다."""
    if not INBOX_FILE.fullmatch(file_name):
        raise SftpError("bad_name")
    with tempfile.TemporaryDirectory(prefix="kotify-fax-") as tmp:
        target = Path(tmp) / file_name
        batch = f"get {config.directory}/{file_name} {target}\n".encode()
        proc = await asyncio.create_subprocess_exec(
            *_command(config),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(proc.communicate(batch), timeout=TIMEOUT_SECONDS)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            log.warning("PBX SFTP 가져오기 시간 초과")
            raise SftpError("timeout") from None
        if proc.returncode != 0 or not target.is_file():
            log.warning("PBX SFTP 가져오기 실패: 종료 코드 %s", proc.returncode)
            raise SftpError("failed")
        if target.stat().st_size > MAX_BYTES:
            raise SftpError("too_large")
        data = target.read_bytes()
    if not data.lstrip()[:5] == b"%PDF-":
        raise SftpError("not_pdf")
    return data
