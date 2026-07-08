"""하이웍스 CID 주소록 조회 — 외부 MySQL(cid_lookup)에서 번호→이름 매핑.

별도 시스템(hiworks-cid)이 하이웍스 공유 주소록을 MySQL `cid_lookup` 테이블로
주기 동기화한다. kotify 는 그 테이블을 **읽기 전용**으로 조회해 채팅·발송 화면에서
고객 번호 대신 이름(직급·회사)을 표시한다.

설계 원칙:
- **완전 격리**: 조회 실패(접속 불가/타임아웃/모듈 없음/스키마 불일치)는 절대
  예외를 밖으로 던지지 않는다. 실패 시 빈 dict → 화면은 번호만 표시(기존 동작).
  하이웍스 시스템이 죽어도 kotify 채팅/발송은 정상 동작해야 한다.
- **배치 조회**: 번호 여러 개를 `WHERE phone IN (...)` 한 번으로. N+1 회피.
- **미설정 = 무동작**: MySQL host 설정이 없으면 조회 자체를 건너뛴다(기능 off).

설정 키 (SettingsStore, 접속정보는 시크릿 암호화):
- ``hiworks.mysql_host``     : MySQL 호스트 (예: 10.0.5.209). 비어 있으면 기능 off.
- ``hiworks.mysql_port``     : 포트 (기본 3306)
- ``hiworks.mysql_db``       : DB 이름 (기본 asterisk)
- ``hiworks.mysql_user``     : 조회 계정 (읽기 전용 권장)
- ``hiworks.mysql_password`` : 비밀번호 (시크릿)
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.security.settings_store import SettingsStore

log = logging.getLogger(__name__)

# MySQL 접속/조회 타임아웃 (초) — 화면 렌더를 오래 잡지 않도록 짧게.
_CONNECT_TIMEOUT = 3
_READ_TIMEOUT = 3

# 한 번에 조회할 최대 번호 수 (IN 절 크기 방어). 채팅 목록·발송 수신자 규모 고려.
_MAX_BATCH = 1000


def _digits(value: str | None) -> str:
    """숫자만 추출. cid_lookup.phone 도 숫자만 저장이라 매칭 키로 사용."""
    return "".join(c for c in (value or "") if c.isdigit())


def _load_config(db: Session) -> dict | None:
    """설정에서 MySQL 접속정보를 읽는다. host 미설정이면 None(기능 off)."""
    store = SettingsStore(db)
    host = (store.get("hiworks.mysql_host", "") or "").strip()
    if not host:
        return None
    return {
        "host": host,
        "port": int(store.get("hiworks.mysql_port", "3306") or "3306"),
        "db": (store.get("hiworks.mysql_db", "asterisk") or "asterisk").strip(),
        "user": (store.get("hiworks.mysql_user", "") or "").strip(),
        "password": store.get("hiworks.mysql_password", "") or "",
    }


def format_display_name(name: str, grade: str | None, company: str | None) -> str:
    """CID 표시 문자열: '이름 직급 (회사)'. 빈 값은 생략. (hiworks-cid 규칙과 동일)"""
    s = (name or "").strip()
    if grade and grade.strip():
        s += f" {grade.strip()}"
    if company and company.strip():
        s += f" ({company.strip()})"
    return s


def lookup_names(db: Session, phones: list[str]) -> dict[str, dict]:
    """번호 리스트 → {정규화번호: {name, grade, company, display}} 배치 조회.

    실패 시(미설정·접속불가·예외 등) 빈 dict 반환. 절대 예외를 던지지 않는다.

    Args:
        db: 활성 DB 세션(설정 읽기용). 조회 자체는 외부 MySQL 로 별도 연결.
        phones: 조회할 번호들(형식 무관 — 내부에서 숫자만 추출).

    Returns:
        {phone_digits: {"name","grade","company","display"}}. 매칭 없는 번호는 키 없음.
    """
    if not phones:
        return {}

    # 숫자만 + 중복 제거 + 빈 값 제외. 매칭 실패해도 안전하므로 관대하게.
    keys = list({d for p in phones if (d := _digits(p))})[:_MAX_BATCH]
    if not keys:
        return {}

    config = _load_config(db)
    if config is None:
        return {}  # 미설정 — 기능 off

    conn = None
    try:
        import pymysql

        conn = pymysql.connect(
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            database=config["db"],
            charset="utf8mb4",
            connect_timeout=_CONNECT_TIMEOUT,
            read_timeout=_READ_TIMEOUT,
            cursorclass=pymysql.cursors.DictCursor,
        )
        placeholders = ",".join(["%s"] * len(keys))
        sql = (
            "SELECT phone, name, grade, company FROM cid_lookup "
            f"WHERE phone IN ({placeholders})"
        )
        with conn.cursor() as cur:
            cur.execute(sql, keys)
            rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001 — 조회 실패는 전면 격리(번호 표시로 fallback)
        log.warning("하이웍스 CID 조회 실패(무시하고 번호 표시): %s", exc)
        return {}
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    result: dict[str, dict] = {}
    for r in rows:
        phone = _digits(r.get("phone"))
        if not phone:
            continue
        name = r.get("name") or ""
        grade = r.get("grade")
        company = r.get("company")
        result[phone] = {
            "name": name,
            "grade": grade,
            "company": company,
            "display": format_display_name(name, grade, company),
        }
    return result


def test_connection(db: Session) -> tuple[bool, str]:
    """설정 화면 '연결 테스트'용 — 접속 + cid_lookup 건수 확인.

    Returns:
        (성공여부, 메시지).
    """
    config = _load_config(db)
    if config is None:
        return False, "MySQL 호스트가 설정되지 않았습니다"
    conn = None
    try:
        import pymysql

        conn = pymysql.connect(
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            database=config["db"],
            charset="utf8mb4",
            connect_timeout=_CONNECT_TIMEOUT,
            read_timeout=_READ_TIMEOUT,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM cid_lookup")
            (count,) = cur.fetchone()
        return True, f"연결 성공 · 주소록 {count:,}건"
    except Exception as exc:  # noqa: BLE001
        return False, f"연결 실패: {exc}"
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
