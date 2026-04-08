"""애플리케이션 설정 — pydantic-settings 기반.

환경 변수로 재정의 가능. `.env` 파일은 사용하지 않음.
개발 모드(`SMS_DEV_MODE=true`)에서는 모든 파일 경로를 ./var/* 로 변경.
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """런타임 설정.

    운영 환경에서는 기본값을 그대로 사용하고 systemd 서비스로 기동.
    개발 환경에서는 ``SMS_DEV_MODE=true`` 환경변수를 설정하여 로컬 경로 사용.
    """

    model_config = SettingsConfigDict(
        env_prefix="SMS_",
        case_sensitive=False,
    )

    # 개발 모드 (True 이면 아래 path 기본값이 ./var/* 로 변경됨)
    dev_mode: bool = False

    # 리슨 호스트/포트
    host: str = "127.0.0.1"
    port: int = 8080

    # DB 경로 (운영)
    db_path: Path = Path("/var/lib/sms/sms.db")

    # 마스터 키 경로 (운영)
    master_key_path: Path = Path("/var/lib/sms/master.key")

    # Setup 토큰 경로 (운영)
    setup_token_path: Path = Path("/var/lib/sms/setup.token")

    def model_post_init(self, __context: object) -> None:
        """개발 모드 시 경로를 ./var/* 로 교체."""
        if self.dev_mode:
            object.__setattr__(self, "db_path", Path("./var/sms.db"))
            object.__setattr__(self, "master_key_path", Path("./var/master.key"))
            object.__setattr__(self, "setup_token_path", Path("./var/setup.token"))

    @property
    def db_url(self) -> str:
        """SQLAlchemy 연결 문자열."""
        return f"sqlite:///{self.db_path}"


# 모듈 레벨 싱글턴 — 앱 전체에서 `from app.config import settings` 로 참조
settings = Settings()
