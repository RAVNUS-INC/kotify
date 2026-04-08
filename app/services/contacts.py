"""연락처 서비스 — CRUD, 검색, 발송 기록 업데이트."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Contact


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def create_contact(
    db: Session,
    name: str,
    created_by: str,
    phone: str | None = None,
    email: str | None = None,
    department: str | None = None,
    notes: str | None = None,
) -> Contact:
    """연락처 생성."""
    now = _now_iso()
    contact = Contact(
        name=name,
        phone=phone,
        email=email,
        department=department,
        notes=notes,
        active=1,
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    db.add(contact)
    db.flush()
    return contact


def update_contact(db: Session, contact_id: int, **fields) -> Contact:
    """연락처 수정. 존재하지 않으면 ValueError."""
    contact = db.get(Contact, contact_id)
    if contact is None:
        raise ValueError(f"연락처 {contact_id}를 찾을 수 없습니다.")

    allowed = {"name", "phone", "email", "department", "notes", "active"}
    for key, value in fields.items():
        if key in allowed:
            setattr(contact, key, value)

    contact.updated_at = _now_iso()
    db.flush()
    return contact


def delete_contact(db: Session, contact_id: int) -> None:
    """연락처 삭제. 존재하지 않으면 ValueError."""
    contact = db.get(Contact, contact_id)
    if contact is None:
        raise ValueError(f"연락처 {contact_id}를 찾을 수 없습니다.")
    db.delete(contact)
    db.flush()


def get_contact(db: Session, contact_id: int) -> Contact | None:
    """연락처 단건 조회."""
    return db.get(Contact, contact_id)


def list_contacts(
    db: Session,
    search: str | None = None,
    department: str | None = None,
    active_only: bool = False,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[Contact], int]:
    """연락처 목록 (검색, 필터, 페이지네이션).

    Returns:
        (contacts, total_count) 튜플.
    """
    q = select(Contact)

    if search:
        pattern = f"%{search}%"
        q = q.where(
            or_(
                Contact.name.like(pattern),
                Contact.phone.like(pattern),
                Contact.email.like(pattern),
                Contact.department.like(pattern),
            )
        )

    if department:
        q = q.where(Contact.department == department)

    if active_only:
        q = q.where(Contact.active == 1)

    count_q = select(func.count()).select_from(q.subquery())
    total = db.execute(count_q).scalar_one()

    offset = (page - 1) * per_page
    contacts = list(
        db.execute(q.order_by(Contact.name).offset(offset).limit(per_page)).scalars().all()
    )
    return contacts, total


def mark_sent(db: Session, contact_id: int, channel: str) -> None:
    """단일 연락처의 last_sent_at + channel 업데이트."""
    contact = db.get(Contact, contact_id)
    if contact is None:
        return
    now = _now_iso()
    contact.last_sent_at = now
    contact.last_sent_channel = channel
    contact.updated_at = now
    db.flush()


def bulk_mark_sent(db: Session, contact_ids: list[int], channel: str) -> None:
    """여러 연락처의 last_sent_at + channel 일괄 업데이트."""
    if not contact_ids:
        return
    now = _now_iso()
    contacts = list(
        db.execute(select(Contact).where(Contact.id.in_(contact_ids))).scalars().all()
    )
    for c in contacts:
        c.last_sent_at = now
        c.last_sent_channel = channel
        c.updated_at = now
    db.flush()
