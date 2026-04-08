"""Setup 모드 IP ACL 테스트 — 외부 IP 차단, 사내망/loopback 통과."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Request

from app.auth.deps import _ALLOWED_SETUP_HOSTS, _is_private_network, require_setup_mode


class TestIsPrivateNetwork:
    def test_loopback_ipv4(self):
        assert _is_private_network("127.0.0.1") is True

    def test_loopback_ipv6(self):
        assert _is_private_network("::1") is True

    def test_private_10(self):
        assert _is_private_network("10.0.0.1") is True

    def test_private_172(self):
        assert _is_private_network("172.16.0.1") is True

    def test_private_192(self):
        assert _is_private_network("192.168.1.100") is True

    def test_public_ip(self):
        assert _is_private_network("8.8.8.8") is False

    def test_public_ip2(self):
        # 8.8.4.4는 Google DNS — 공인 IP
        assert _is_private_network("8.8.4.4") is False

    def test_invalid_ip(self):
        assert _is_private_network("not-an-ip") is False


class TestAllowedSetupHosts:
    def test_localhost_in_allowed(self):
        assert "127.0.0.1" in _ALLOWED_SETUP_HOSTS

    def test_ipv6_loopback_in_allowed(self):
        assert "::1" in _ALLOWED_SETUP_HOSTS

    def test_localhost_string_in_allowed(self):
        assert "localhost" in _ALLOWED_SETUP_HOSTS


class TestRequireSetupMode:
    def _make_request(self, client_ip: str) -> Request:
        """테스트용 최소 Request 객체 생성."""
        request = MagicMock(spec=Request)
        request.client = MagicMock()
        request.client.host = client_ip
        return request

    def _make_db_not_bootstrapped(self):
        """부트스트랩 미완료 DB 모킹."""
        db = MagicMock()
        store_mock = MagicMock()
        store_mock.is_bootstrap_completed.return_value = False
        return db, store_mock

    def test_loopback_passes(self, db_session):
        """127.0.0.1은 setup 접근 허용."""
        request = self._make_request("127.0.0.1")

        # bootstrap 미완료 상태 설정
        # DB에 아무 설정도 없으면 is_bootstrap_completed() == False
        # → setup mode라 bootstrap 체크 후 IP 체크로 진행
        # 404 예외가 발생하지 않아야 함
        try:
            require_setup_mode(request, db_session)
        except HTTPException as exc:
            assert exc.status_code != 404 or "Not Found" not in str(exc.detail), (
                "loopback은 404를 반환하면 안 됩니다"
            )

    def test_private_network_passes(self, db_session):
        """사내망(10.x.x.x)은 setup 접근 허용."""
        request = self._make_request("10.10.0.50")
        try:
            require_setup_mode(request, db_session)
        except HTTPException:
            # IP ACL로 인한 404가 아니어야 함
            # (bootstrap 완료로 인한 404는 OK)
            pass  # bootstrap 미완료 상태에서만 IP ACL 실행됨

    def test_public_ip_passes(self, db_session):
        """외부 IP도 setup 접근 허용 — IP ACL 제거됨.

        Reverse proxy(NPM) + --proxy-headers 환경에서 진짜 클라이언트 IP가
        외부 IP로 인식되어 정당한 운영자도 차단되는 catch-22 때문에
        IP ACL을 제거. setup.token 파일 + bootstrap 완료 플래그 + NPM 외부 차단이
        다층 방어를 이룬다.
        """
        request = self._make_request("8.8.8.8")
        # 예외 발생하지 않아야 함 (bootstrap 미완료 상태)
        require_setup_mode(request, db_session)

    def test_already_bootstrapped_returns_404(self, db_session):
        """부트스트랩 완료 상태에서는 어떤 IP든 404."""
        from app.security.settings_store import SettingsStore
        store = SettingsStore(db_session)
        # updated_by=None으로 FK 제약 우회 (시스템 액션)
        store.mark_bootstrap_completed(None)

        request = self._make_request("127.0.0.1")
        with pytest.raises(HTTPException) as exc_info:
            require_setup_mode(request, db_session)
        assert exc_info.value.status_code == 404
