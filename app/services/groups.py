"""그룹 서비스 — 그룹 CRUD, 멤버 관리, 그룹 펼치기."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Contact, ContactGroup, ContactGroupMember


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def create_group(
    db: Session,
    name: str,
    created_by: str,
    description: str | None = None,
) -> ContactGroup:
    """그룹 생성."""
    now = _now_iso()
    group = ContactGroup(
        name=name,
        description=description,
        created_by=created_by,
        created_at=now,
        updated_at=now,
    )
    db.add(group)
    db.flush()
    return group


def update_group(db: Session, group_id: int, **fields) -> ContactGroup:
    """그룹 수정. 존재하지 않으면 ValueError."""
    group = db.get(ContactGroup, group_id)
    if group is None:
        raise ValueError(f"그룹 {group_id}를 찾을 수 없습니다.")

    allowed = {"name", "description"}
    for key, value in fields.items():
        if key in allowed:
            setattr(group, key, value)

    group.updated_at = _now_iso()
    db.flush()
    return group


def delete_group(db: Session, group_id: int) -> None:
    """그룹 삭제 (멤버십 CASCADE). 존재하지 않으면 ValueError."""
    group = db.get(ContactGroup, group_id)
    if group is None:
        raise ValueError(f"그룹 {group_id}를 찾을 수 없습니다.")
    # 멤버십 먼저 삭제 (SQLite foreign key CASCADE가 비활성 환경 대비)
    db.execute(
        ContactGroupMember.__table__.delete().where(
            ContactGroupMember.group_id == group_id
        )
    )
    db.delete(group)
    db.flush()


def get_group(db: Session, group_id: int) -> ContactGroup | None:
    """그룹 단건 조회."""
    return db.get(ContactGroup, group_id)


def list_groups(
    db: Session,
    search: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[ContactGroup], int]:
    """그룹 목록 (검색, 페이지네이션).

    Returns:
        (groups, total_count) 튜플.
    """
    q = select(ContactGroup)

    if search:
        pattern = f"%{search}%"
        q = q.where(ContactGroup.name.like(pattern))

    count_q = select(func.count()).select_from(q.subquery())
    total = db.execute(count_q).scalar_one()

    offset = (page - 1) * per_page
    groups = list(
        db.execute(q.order_by(ContactGroup.name).offset(offset).limit(per_page)).scalars().all()
    )
    return groups, total


def add_members(
    db: Session,
    group_id: int,
    contact_ids: list[int],
    added_by: str | None = None,
) -> int:
    """그룹에 멤버 추가. 중복은 무시. 추가된 수 반환."""
    if not contact_ids:
        return 0

    # 기존 멤버 조회 (중복 방지)
    existing = set(
        db.execute(
            select(ContactGroupMember.contact_id).where(
                ContactGroupMember.group_id == group_id
            )
        ).scalars().all()
    )

    now = _now_iso()
    added = 0
    for cid in contact_ids:
        if cid in existing:
            continue
        member = ContactGroupMember(
            group_id=group_id,
            contact_id=cid,
            added_by=added_by,
            added_at=now,
        )
        db.add(member)
        existing.add(cid)
        added += 1

    db.flush()
    return added


def remove_members(
    db: Session,
    group_id: int,
    contact_ids: list[int],
) -> int:
    """그룹에서 멤버 제거. 제거된 수 반환."""
    if not contact_ids:
        return 0

    members = list(
        db.execute(
            select(ContactGroupMember).where(
                ContactGroupMember.group_id == group_id,
                ContactGroupMember.contact_id.in_(contact_ids),
            )
        ).scalars().all()
    )
    for m in members:
        db.delete(m)
    db.flush()
    return len(members)


def list_members(
    db: Session,
    group_id: int,
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[Contact], int]:
    """그룹 멤버 목록 (페이지네이션).

    Returns:
        (contacts, total_count) 튜플.
    """
    member_ids_q = select(ContactGroupMember.contact_id).where(
        ContactGroupMember.group_id == group_id
    )
    q = select(Contact).where(Contact.id.in_(member_ids_q))

    count_q = select(func.count()).select_from(q.subquery())
    total = db.execute(count_q).scalar_one()

    offset = (page - 1) * per_page
    contacts = list(
        db.execute(q.order_by(Contact.name).offset(offset).limit(per_page)).scalars().all()
    )
    return contacts, total


def expand_groups_to_contacts(
    db: Session,
    group_ids: list[int],
) -> list[Contact]:
    """그룹들을 펼쳐서 중복 제거된 Contact 리스트 반환."""
    if not group_ids:
        return []

    member_ids_q = (
        select(ContactGroupMember.contact_id)
        .where(ContactGroupMember.group_id.in_(group_ids))
        .distinct()
    )
    contacts = list(
        db.execute(
            select(Contact).where(Contact.id.in_(member_ids_q)).order_by(Contact.name)
        ).scalars().all()
    )
    return contacts


def get_group_size(db: Session, group_id: int) -> int:
    """그룹의 멤버 수 반환."""
    return db.execute(
        select(func.count()).where(ContactGroupMember.group_id == group_id)
    ).scalar_one()
