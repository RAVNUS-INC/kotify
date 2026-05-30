"""CSV formula injection (CWE-1236) 방어 회귀 테스트.

Excel/Numbers 는 `=` `+` `-` `@` `\\t` `\\r` `\\n` `;` 로 시작하는 셀을 공식으로
해석해 외부 링크·명령 실행 위험이 있다. safe_csv_cell 이 이를 single-quote 로
무력화하며, 모든 CSV export 경로(audit_api/campaigns/reports/contacts)가 동일
헬퍼를 공유한다.

검증 범위: 헬퍼(safe_csv_cell) + 대표 export 경로(export_contacts, import→DB→
export 라운드트립). 나머지 3개 라우터(audit_api/campaigns/reports)는 모든 사용자
입력 컬럼이 동일 헬퍼로 감싸졌음을 코드 인스펙션으로 확인했고(숫자 컬럼 str(cost)
등은 서버 계산값이라 공식 트리거 불가), 본 헬퍼 테스트가 그 동작을 고정한다.
"""
from __future__ import annotations

import csv
import io

from app.models import Contact
from app.services.csv_import import export_contacts
from app.util.csv_safe import safe_csv_cell


def test_safe_csv_cell_prefixes_formula_triggers():
    """공식 트리거 문자로 시작하는 값은 single-quote 로 무력화된다."""
    for ch in ("=", "+", "-", "@", "\t", "\r", "\n", ";"):
        assert safe_csv_cell(f"{ch}cmd") == f"'{ch}cmd"


def test_safe_csv_cell_passes_safe_values():
    """일반 값·빈 문자열·중간 특수문자는 변경하지 않는다."""
    assert safe_csv_cell("홍길동") == "홍길동"
    assert safe_csv_cell("01012345678") == "01012345678"
    assert safe_csv_cell("a=b+c") == "a=b+c"   # 선두가 아니면 위험 아님
    assert safe_csv_cell("x@example.com") == "x@example.com"
    assert safe_csv_cell("") == ""


def test_export_contacts_sanitizes_injection(db_session, sample_user):
    """악성 payload 가 든 연락처를 export 하면 공식이 무력화돼 출력된다."""
    db_session.add(Contact(
        name='=HYPERLINK("http://evil","click")',
        phone="01099998888",
        email="x@example.com",
        department="@SUM(A1:A9)",
        notes="+1+2",
        created_by=sample_user.sub,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
    ))
    db_session.commit()

    csv_text = export_contacts(db_session)
    rows = list(csv.DictReader(io.StringIO(csv_text)))

    assert len(rows) == 1
    row = rows[0]
    # 위험 필드는 single-quote 로 시작 (공식 비활성화) — CSV 라운드트립 후에도 유지
    assert row["name"].startswith("'=")
    assert row["department"].startswith("'@")
    assert row["notes"].startswith("'+")
    # 안전 필드(공식 트리거 아님)는 원본 그대로
    assert row["phone"] == "01099998888"
    assert row["email"] == "x@example.com"
