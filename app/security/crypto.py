"""마스터 키 관리 + Fernet 암호화/복호화.

마스터 키는 `/var/lib/sms/master.key` (운영) 또는 `./var/master.key` (개발)에
600 권한으로 보관된다. 파일이 없으면 최초 기동 시 자동 생성한다.

절대 금지:
- 키 값을 로그에 출력
- 키 값을 HTTP 응답에 포함
"""
from __future__ import annotations

import stat
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet

from app.config import settings


def load_or_create_master_key(path: Path | None = None) -> bytes:
    """마스터 키를 파일에서 읽거나, 없으면 생성 후 저장한다.

    Args:
        path: 키 파일 경로. None 이면 ``settings.master_key_path`` 사용.

    Returns:
        Fernet 키 바이트 (URL-safe base64, 44 bytes).

    Raises:
        OSError: 파일 읽기/쓰기 실패 시.
    """
    key_path = path or settings.master_key_path

    if key_path.exists():
        return key_path.read_bytes().strip()

    # 키 파일이 없으면 새로 생성
    key = Fernet.generate_key()

    # 부모 디렉토리 생성 (없는 경우)
    key_path.parent.mkdir(parents=True, exist_ok=True)

    # 600 권한으로 저장 (소유자 읽기/쓰기만)
    key_path.write_bytes(key)
    key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)

    return key


@lru_cache(maxsize=1)
def get_fernet(key_path_str: str | None = None) -> Fernet:
    """캐시된 Fernet 인스턴스를 반환한다.

    Args:
        key_path_str: 키 파일 경로 문자열. None 이면 settings 기본값 사용.
            lru_cache가 해시 가능한 인자만 허용하므로 Path 대신 str 사용.

    Returns:
        초기화된 Fernet 인스턴스.
    """
    path = Path(key_path_str) if key_path_str else None
    key = load_or_create_master_key(path)
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    """평문 문자열을 Fernet 암호화하여 토큰 문자열로 반환한다.

    Args:
        plaintext: 암호화할 평문.

    Returns:
        URL-safe base64 인코딩된 Fernet 토큰 문자열.
    """
    fernet = get_fernet()
    token: bytes = fernet.encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt(ciphertext: str) -> str:
    """Fernet 토큰 문자열을 복호화하여 평문 문자열로 반환한다.

    Args:
        ciphertext: Fernet 토큰 문자열.

    Returns:
        복호화된 평문.

    Raises:
        cryptography.fernet.InvalidToken: 토큰이 유효하지 않거나 변조된 경우.
    """
    fernet = get_fernet()
    plaintext: bytes = fernet.decrypt(ciphertext.encode("utf-8"))
    return plaintext.decode("utf-8")


def mask(value: str) -> str:
    """시크릿 값을 마스킹한다. 마지막 4자리만 노출한다.

    Args:
        value: 원본 시크릿 값.

    Returns:
        예: ``'****1234'``. 4자 미만이면 전체 마스킹.
    """
    if len(value) <= 4:
        return "*" * len(value)
    return "*" * (len(value) - 4) + value[-4:]
