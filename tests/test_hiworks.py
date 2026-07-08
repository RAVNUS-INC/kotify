"""하이웍스 CID 조회 서비스 테스트.

- 미설정(host 없음) → 빈 dict, 조회 시도 안 함.
- 조회 실패(pymysql 예외) → 빈 dict, 예외 전파 안 함(격리).
- 정상 조회 → 번호→표시명 매핑.
- format_display_name / _digits 규칙.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.security.settings_store import SettingsStore
from app.services import hiworks


def _configure(db, host="10.0.5.209"):
    store = SettingsStore(db)
    store.set("hiworks.mysql_host", host, is_secret=False, updated_by="t")
    store.set("hiworks.mysql_user", "ro", is_secret=False, updated_by="t")
    store.set("hiworks.mysql_password", "pw", is_secret=True, updated_by="t")
    db.commit()


# ── 순수 함수 ────────────────────────────────────────────────────────────────


def test_format_display_name():
    assert hiworks.format_display_name("홍길동", "부장", "레이븐어스") == "홍길동 부장 (레이븐어스)"
    assert hiworks.format_display_name("홍길동", None, None) == "홍길동"
    assert hiworks.format_display_name("홍길동", "", "") == "홍길동"
    assert hiworks.format_display_name("김철수", None, "회사") == "김철수 (회사)"


def test_digits():
    assert hiworks._digits("010-1234-5678") == "01012345678"
    assert hiworks._digits("02 577 1000") == "025771000"
    assert hiworks._digits(None) == ""


# ── lookup_names 격리 ────────────────────────────────────────────────────────


def test_lookup_empty_phones(db_session):
    assert hiworks.lookup_names(db_session, []) == {}


def test_lookup_unconfigured_returns_empty(db_session):
    """host 미설정이면 조회 시도 없이 빈 dict."""
    with patch("pymysql.connect") as m:
        result = hiworks.lookup_names(db_session, ["01012345678"])
    assert result == {}
    m.assert_not_called()  # 접속 시도조차 안 함


def test_lookup_connect_failure_is_isolated(db_session):
    """접속/조회 예외는 격리 — 빈 dict 반환, 예외 전파 안 함."""
    _configure(db_session)
    with patch("pymysql.connect", side_effect=OSError("connection refused")):
        result = hiworks.lookup_names(db_session, ["01012345678"])
    assert result == {}  # 예외 없이 빈 결과


def test_lookup_success_maps_names(db_session):
    """정상 조회 → 번호→표시명. 형식(하이픈) 입력도 숫자로 매칭."""
    _configure(db_session)

    fake_rows = [
        {"phone": "01012345678", "name": "홍길동", "grade": "부장", "company": "레이븐어스"},
    ]
    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = fake_rows
    fake_cur.__enter__ = MagicMock(return_value=fake_cur)
    fake_cur.__exit__ = MagicMock(return_value=False)
    fake_conn = MagicMock()
    fake_conn.cursor.return_value = fake_cur

    with patch("pymysql.connect", return_value=fake_conn):
        # 입력은 하이픈 있어도 숫자로 정규화되어 매칭
        result = hiworks.lookup_names(db_session, ["010-1234-5678"])

    assert "01012345678" in result
    assert result["01012345678"]["display"] == "홍길동 부장 (레이븐어스)"
    assert result["01012345678"]["name"] == "홍길동"


def test_test_connection_unconfigured(db_session):
    ok, msg = hiworks.test_connection(db_session)
    assert ok is False
    assert "설정" in msg
