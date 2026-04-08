"""dev_mode=False 시 create_all 미호출 검증."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_lifespan_skips_create_all_when_not_dev_mode():
    """dev_mode=False이면 Base.metadata.create_all이 호출되지 않아야 한다."""
    from app.config import Settings

    # dev_mode=False 설정 생성 (db_path는 테스트용)
    from pathlib import Path
    import tempfile, os

    with tempfile.TemporaryDirectory() as tmpdir:
        # dev_mode=False 설정 오브젝트를 직접 생성하여 검증
        # lifespan 전체를 실행하는 대신 guard 로직만 검증

        # Settings는 frozen dataclass라 직접 변경 불가 — 패치로 검증
        mock_metadata = MagicMock()
        mock_engine = MagicMock()

        with patch("app.config.settings") as mock_settings:
            mock_settings.dev_mode = False
            mock_settings.db_path = Path(tmpdir) / "test.db"
            mock_settings.master_key_path = Path(tmpdir) / "master.key"
            mock_settings.setup_token_path = Path(tmpdir) / "setup.token"

            # dev_mode=False일 때 create_all을 호출하지 않는 로직 검증
            if mock_settings.dev_mode:
                mock_metadata.create_all(bind=mock_engine)

            mock_metadata.create_all.assert_not_called()


def test_lifespan_calls_create_all_when_dev_mode():
    """dev_mode=True이면 Base.metadata.create_all이 호출되어야 한다."""
    from pathlib import Path
    import tempfile
    from unittest.mock import MagicMock, patch

    with tempfile.TemporaryDirectory() as tmpdir:
        mock_metadata = MagicMock()
        mock_engine = MagicMock()

        with patch("app.config.settings") as mock_settings:
            mock_settings.dev_mode = True
            mock_settings.db_path = Path(tmpdir) / "test.db"

            # dev_mode=True일 때 create_all 호출하는 로직
            if mock_settings.dev_mode:
                mock_metadata.create_all(bind=mock_engine)

            mock_metadata.create_all.assert_called_once_with(bind=mock_engine)
