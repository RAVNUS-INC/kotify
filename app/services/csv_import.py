"""CSV 가져오기/내보내기 서비스."""
from __future__ import annotations

import csv
import io
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contact
from app.services.contacts import create_contact, update_contact
from app.util.phone import normalize_phone

# CSV 필수 헤더
_REQUIRED_HEADERS = {"name"}
# 지원 헤더 (순서 무관)
_SUPPORTED_HEADERS = {"name", "phone", "email", "department", "notes"}


def parse_csv(content: str) -> tuple[list[dict], list[dict]]:
    """CSV 문자열을 파싱하여 (valid_rows, invalid_rows) 반환.

    헤더: name, phone, email, department, notes
    필수: name + (phone 또는 email 중 하나 이상)

    Args:
        content: CSV 문자열.

    Returns:
        (valid_rows, invalid_rows) 튜플.
        invalid_rows 형태: {row_number, raw_data, error}
    """
    valid: list[dict] = []
    invalid: list[dict] = []

    reader = csv.DictReader(io.StringIO(content.strip()))

    # 헤더 확인
    if reader.fieldnames is None:
        return [], [{"row_number": 0, "raw_data": {}, "error": "헤더가 없습니다."}]

    headers = {h.strip().lower() for h in reader.fieldnames if h}
    missing = _REQUIRED_HEADERS - headers
    if missing:
        return [], [
            {
                "row_number": 0,
                "raw_data": {},
                "error": f"필수 헤더 누락: {', '.join(sorted(missing))}",
            }
        ]

    for row_num, row in enumerate(reader, start=2):  # 헤더가 1번
        # 키 정규화
        normalized: dict[str, Any] = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}

        name = normalized.get("name", "")
        raw_phone = normalized.get("phone", "")
        email = normalized.get("email", "")
        department = normalized.get("department", "") or None
        notes = normalized.get("notes", "") or None

        # name 필수
        if not name:
            invalid.append({
                "row_number": row_num,
                "raw_data": dict(row),
                "error": "name이 비어 있습니다.",
            })
            continue

        # phone 또는 email 중 하나 필수
        if not raw_phone and not email:
            invalid.append({
                "row_number": row_num,
                "raw_data": dict(row),
                "error": "phone 또는 email 중 하나 이상 필요합니다.",
            })
            continue

        # phone 정규화
        phone: str | None = None
        if raw_phone:
            phone = normalize_phone(raw_phone)
            if phone is None:
                invalid.append({
                    "row_number": row_num,
                    "raw_data": dict(row),
                    "error": f"올바르지 않은 전화번호 형식: {raw_phone!r}",
                })
                continue

        valid.append({
            "name": name,
            "phone": phone,
            "email": email or None,
            "department": department,
            "notes": notes,
        })

    return valid, invalid


def import_contacts(
    db: Session,
    valid_rows: list[dict],
    created_by: str,
    mode: str = "skip",
) -> dict:
    """유효 행을 DB에 저장.

    Args:
        db: SQLAlchemy 세션.
        valid_rows: parse_csv()가 반환한 valid_rows.
        created_by: users.sub.
        mode: 'skip' | 'update' | 'create'
            - skip: phone 기준 중복이면 건너뜀
            - update: phone 기준 중복이면 덮어씀
            - create: 항상 새 레코드 생성

    Returns:
        {created: N, updated: N, skipped: N, errors: [...]}
    """
    result: dict[str, Any] = {"created": 0, "updated": 0, "skipped": 0, "errors": []}

    # N+1 제거: 기존 연락처를 phone 기준으로 일괄 조회 후 dict 캐싱한다.
    # parse_csv 가 normalize_phone 으로 정규화했으므로 키가 일치한다. 대량 CSV 의
    # SQLite IN 절 변수 한도(구버전 999)를 피하려 청크로 나눠 조회한다.
    existing_map: dict[str, Contact] = {}
    if mode != "create":
        phones = [r["phone"] for r in valid_rows if r.get("phone")]
        _CHUNK = 500
        for i in range(0, len(phones), _CHUNK):
            batch = phones[i : i + _CHUNK]
            rows = db.execute(
                select(Contact).where(Contact.phone.in_(batch))
            ).scalars().all()
            for c in rows:
                if c.phone:
                    existing_map[c.phone] = c

    for row in valid_rows:
        try:
            phone = row.get("phone")
            existing = existing_map.get(phone) if (mode != "create" and phone) else None

            if existing is not None:
                if mode == "skip":
                    result["skipped"] += 1
                    continue
                if mode == "update":
                    update_contact(
                        db,
                        existing.id,
                        name=row["name"],
                        email=row.get("email"),
                        department=row.get("department"),
                        notes=row.get("notes"),
                    )
                    result["updated"] += 1
                    continue

            # 새로 생성
            created = create_contact(
                db,
                name=row["name"],
                created_by=created_by,
                phone=phone,
                email=row.get("email"),
                department=row.get("department"),
                notes=row.get("notes"),
            )
            result["created"] += 1
            # CSV 내 동일 phone 후속 행이 방금 만든 레코드를 보도록 캐시 갱신
            # (원래 행별 SELECT 동작 보존 — 같은 파일 내 중복 시 1건만 생성).
            if phone and mode != "create":
                existing_map[phone] = created

        except Exception as exc:
            result["errors"].append(str(exc))

    return result


def export_contacts(
    db: Session,
    contact_ids: list[int] | None = None,
) -> str:
    """연락처를 CSV 문자열로 내보내기.

    Args:
        db: SQLAlchemy 세션.
        contact_ids: 특정 ID 목록 (None이면 전체).

    Returns:
        CSV 문자열.
    """
    q = select(Contact).order_by(Contact.name)
    if contact_ids is not None:
        q = q.where(Contact.id.in_(contact_ids))

    contacts = list(db.execute(q).scalars().all())

    # CWE-1236 CSV formula injection 방어. notes/name 같은 사용자 입력 필드에
    # `=CMD(...)` 같은 payload 가 들어오면 Excel 에서 원격 명령을 트리거할 수 있다.
    from app.util.csv_safe import safe_csv_cell

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["name", "phone", "email", "department", "notes"],
        extrasaction="ignore",
    )
    writer.writeheader()
    for c in contacts:
        writer.writerow({
            "name": safe_csv_cell(c.name or ""),
            "phone": safe_csv_cell(c.phone or ""),
            "email": safe_csv_cell(c.email or ""),
            "department": safe_csv_cell(c.department or ""),
            "notes": safe_csv_cell(c.notes or ""),
        })

    return output.getvalue()
