"""SettingsStore — get/set/암호화 검증."""
from __future__ import annotations

from app.security.settings_store import SettingsStore


class TestSettingsStore:
    def test_set_and_get_plain(self, db_session):
        """평문 값 저장/조회."""
        store = SettingsStore(db_session)
        store.set("keycloak.issuer", "https://keycloak.example.com/realms/sms-sys",
                  is_secret=False, updated_by=None)
        db_session.commit()

        val = store.get("keycloak.issuer")
        assert val == "https://keycloak.example.com/realms/sms-sys"

    def test_set_and_get_secret(self, db_session):
        """시크릿 값 저장/조회 — 자동 암복호화."""
        store = SettingsStore(db_session)
        store.set("ncp.access_key", "my-super-secret-key",
                  is_secret=True, updated_by=None)
        db_session.commit()

        val = store.get("ncp.access_key")
        assert val == "my-super-secret-key"

    def test_get_missing_returns_default(self, db_session):
        """없는 키는 default 반환."""
        store = SettingsStore(db_session)
        val = store.get("nonexistent.key", default="fallback")
        assert val == "fallback"

    def test_get_missing_returns_none(self, db_session):
        """default 없이 없는 키는 None 반환."""
        store = SettingsStore(db_session)
        val = store.get("nonexistent.key")
        assert val is None

    def test_upsert_updates_existing(self, db_session):
        """같은 키 다시 set하면 업데이트됨."""
        store = SettingsStore(db_session)
        store.set("app.public_url", "https://old.example.com",
                  is_secret=False, updated_by=None)
        db_session.commit()

        store.set("app.public_url", "https://new.example.com",
                  is_secret=False, updated_by=None)
        db_session.commit()

        val = store.get("app.public_url")
        assert val == "https://new.example.com"

    def test_bootstrap_not_completed_initially(self, db_session):
        """부트스트랩 미완료 상태."""
        store = SettingsStore(db_session)
        assert store.is_bootstrap_completed() is False

    def test_mark_bootstrap_completed(self, db_session):
        """부트스트랩 완료 마킹."""
        # updated_by FK 제약 때문에 NULL(None) 사용
        store = SettingsStore(db_session)
        store.mark_bootstrap_completed(updated_by=None)

        assert store.is_bootstrap_completed() is True

    def test_mask(self):
        """마스킹 헬퍼 — 마지막 4자리 노출, 4자 이하는 전체 마스킹."""
        assert SettingsStore.mask("abcdefgh1234") == "********1234"
        assert SettingsStore.mask("ab") == "**"
        # 4자 이하 → 전체 마스킹 (crypto.mask 명세)
        assert SettingsStore.mask("abcd") == "****"

    def test_get_all_public(self, db_session):
        """is_secret=False인 설정만 반환."""
        store = SettingsStore(db_session)
        store.set("keycloak.issuer", "https://example.com", is_secret=False, updated_by=None)
        store.set("ncp.access_key", "secret", is_secret=True, updated_by=None)
        db_session.commit()

        public = store.get_all_public()
        assert "keycloak.issuer" in public
        assert "ncp.access_key" not in public

    def test_secret_value_is_encrypted_in_db(self, db_session):
        """DB에 저장된 시크릿 값은 암호화되어 있어야 함."""
        from sqlalchemy import select

        from app.models import Setting

        store = SettingsStore(db_session)
        store.set("ncp.secret_key", "plaintext-secret",
                  is_secret=True, updated_by=None)
        db_session.commit()

        row = db_session.execute(
            select(Setting).where(Setting.key == "ncp.secret_key")
        ).scalar_one()

        # DB에 저장된 값은 평문이 아니어야 함
        assert row.value != "plaintext-secret"
        # 하지만 get()하면 평문으로 반환
        assert store.get("ncp.secret_key") == "plaintext-secret"
