"""그룹 API — S9 목록 / S10 상세.

실 DB (contact_groups + contact_group_members + contacts) 기반.
services.groups.list_groups 를 재사용.

api-contract.md §S9/S10 — web/types/group.ts Group / GroupDetail shape.

NOTE: 현재 스키마엔 source (ad/csv/api/manual) / lastSyncAt / reachRate /
lastCampaignAt 컬럼이 없다. TS 계약에서 source 는 필수이므로 "manual" 을
기본값으로 emit, 나머지 optional 필드는 omit. AD 동기화·CSV 자동화·리포트
연결이 추가되면 해당 필드를 도출한다.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_complete, require_user
from app.db import get_db
from app.models import (
    Campaign,
    Contact,
    ContactGroup,
    ContactGroupMember,
    Message,
    User,
)
from app.routes.contacts import (
    _batch_group_ids,
    _batch_last_campaign_labels,
    _contact_to_dict,
    _fmt_kst_dt,
)
from app.security.csrf import verify_csrf
from app.services import audit
from app.services.groups import (
    add_members as svc_add_members,
    bulk_add_by_phones as svc_bulk_add_by_phones,
    create_group as svc_create_group,
    delete_group as svc_delete_group,
    list_groups as svc_list_groups,
    remove_members as svc_remove_members,
    update_group as svc_update_group,
)

router = APIRouter(
    dependencies=[Depends(require_user), Depends(require_setup_complete)],
)

KST = ZoneInfo("Asia/Seoul")

# 그룹 멤버 상세 조회 상한 — 초과 시 meta.membersHasMore=true 로 signaling.
_GROUP_MEMBERS_LIMIT = 1000


def _batch_member_counts(
    db: Session, group_ids: list[int]
) -> dict[int, tuple[int, int]]:
    """group_id → (memberCount, validCount) 배치 집계 (1쿼리).

    validCount 는 contacts.active=1 만 카운트.
    """
    if not group_ids:
        return {}
    rows = db.execute(
        select(
            ContactGroupMember.group_id,
            func.count(Contact.id).label("total"),
            func.sum(Contact.active).label("active_count"),
        )
        .join(Contact, Contact.id == ContactGroupMember.contact_id)
        .where(ContactGroupMember.group_id.in_(group_ids))
        .group_by(ContactGroupMember.group_id)
    ).all()
    result: dict[int, tuple[int, int]] = {}
    for r in rows:
        total = int(r.total or 0)
        active = int(r.active_count or 0)
        result[r.group_id] = (total, active)
    return result


def _batch_last_campaign_times(
    db: Session, group_ids: list[int]
) -> dict[int, str]:
    """group_id → 최근 캠페인 발송 시각(KST 'YYYY-MM-DD HH:MM').

    그룹 멤버의 phone 으로 발송된 메시지 중 최근 complete_time 을 기준.
    1쿼리 GROUP BY.

    ⚠ 의미적 근사: "이 그룹을 통해 발송된 캠페인" 이 아니라 "이 그룹에
    *현재* 속한 phone 중 하나로 도달한 메시지 중 가장 최근" 을 반환한다.
    멤버십 추가/삭제 시점과 메시지 발송 시점의 순서는 고려하지 않으므로
    멤버가 그룹 가입 *이전* 에 개별적으로 받은 캠페인도 반영될 수 있다.
    정확한 계열 추적이 필요해지면 Campaign↔ContactGroup FK 를 추가하거나
    Message.group_id 컬럼을 도입해야 한다. MVP 수준 지표로 유지.
    """
    if not group_ids:
        return {}
    # max(Message.complete_time) per group_id — JOIN 경로:
    # ContactGroupMember → Contact → Message(by phone) 또는 (by contact_id 없음).
    # Message 는 contact_id 직접 연결 없어 phone 으로 매칭.
    # NOTE: Message.to_number 가 정규화 표기(01011112222)여야 Contact.phone
    # 과 일치. 이 전제는 app/services/compose.py 의 normalize_phone 에 의해
    # 보장된다고 가정.
    rows = db.execute(
        select(
            ContactGroupMember.group_id,
            func.max(Message.complete_time).label("last_ct"),
        )
        .join(Contact, Contact.id == ContactGroupMember.contact_id)
        .join(Message, Message.to_number == Contact.phone)
        .where(
            ContactGroupMember.group_id.in_(group_ids),
            Message.complete_time.isnot(None),
        )
        .group_by(ContactGroupMember.group_id)
    ).all()
    result: dict[int, str] = {}
    for r in rows:
        formatted = _fmt_kst_dt(r.last_ct)
        if formatted:
            result[r.group_id] = formatted
    return result


def _group_to_dict(
    g: ContactGroup,
    counts: tuple[int, int] | None,
    last_camp_at: str | None,
) -> dict:
    """ContactGroup ORM → web/types/group.ts Group shape.

    현 스키마 미지원 필드(source/lastSyncAt/reachRate) 정책:
      - source: 필수라 "manual" 기본값.
      - lastSyncAt/reachRate: optional 이라 omit (undefined 로 직렬화).
    """
    member_count, valid_count = counts if counts else (0, 0)
    row: dict = {
        "id": f"g-{g.id}",
        "name": g.name,
        "source": "manual",
        "memberCount": member_count,
        "validCount": valid_count,
    }
    if g.description:
        row["description"] = g.description
    if last_camp_at:
        row["lastCampaignAt"] = last_camp_at
    return row


def _parse_gid(gid: str) -> int | None:
    """'g-{n}' 또는 '{n}' → int. 실패 시 None."""
    raw = gid[2:] if gid.startswith("g-") else gid
    try:
        return int(raw)
    except (ValueError, TypeError):
        return None


# ── S9: GET /groups ─────────────────────────────────────────────────────────


@router.get("/groups", response_model=None)
def list_groups_route(
    q: Optional[str] = None,
    db: Session = Depends(get_db),
) -> dict:
    """그룹 목록. q 는 name 부분 매치 (service 에서 처리)."""
    groups, total = svc_list_groups(db, search=q or None, page=1, per_page=500)
    ids = [g.id for g in groups]

    counts = _batch_member_counts(db, ids)
    last_camp = _batch_last_campaign_times(db, ids)

    rows = [
        _group_to_dict(g, counts.get(g.id), last_camp.get(g.id))
        for g in groups
    ]
    return {
        "data": rows,
        "meta": {"total": total, "hasMore": total > 500},
    }


# ── S10: GET /groups/{id} ───────────────────────────────────────────────────


@router.get("/groups/{gid}", response_model=None)
def get_group_route(gid: str, db: Session = Depends(get_db)) -> dict | JSONResponse:
    """그룹 상세 — Group + members (Contact[])."""
    gid_int = _parse_gid(gid)
    if gid_int is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "그룹을 찾을 수 없습니다"}},
            status_code=404,
        )
    group = db.get(ContactGroup, gid_int)
    if group is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "그룹을 찾을 수 없습니다"}},
            status_code=404,
        )

    counts = _batch_member_counts(db, [group.id]).get(group.id)
    last_camp = _batch_last_campaign_times(db, [group.id]).get(group.id)
    base = _group_to_dict(group, counts, last_camp)

    # 멤버 조회 — 이름 기준 오름차순, 상한 _GROUP_MEMBERS_LIMIT.
    members: list[Contact] = list(
        db.execute(
            select(Contact)
            .join(ContactGroupMember, ContactGroupMember.contact_id == Contact.id)
            .where(ContactGroupMember.group_id == group.id)
            .order_by(Contact.name)
            .limit(_GROUP_MEMBERS_LIMIT)
        ).scalars().all()
    )

    # 멤버별 groupIds/lastCampaign 배치 — contacts 라우트와 동일 패턴 재사용.
    mids = [m.id for m in members]
    phones = [m.phone for m in members if m.phone]
    group_map = _batch_group_ids(db, mids)
    label_map = _batch_last_campaign_labels(db, phones)

    base["members"] = [
        _contact_to_dict(
            m,
            group_ids=group_map.get(m.id),
            last_campaign=(label_map.get(m.phone) if m.phone else None),
        )
        for m in members
    ]
    # 잘린 멤버가 있는지 프론트에 신호 — memberCount 는 기준(정확한 총합) 이미 포함.
    total_members = counts[0] if counts else 0
    meta: dict = {}
    if total_members > _GROUP_MEMBERS_LIMIT:
        meta["membersHasMore"] = True
        meta["membersTruncatedTo"] = _GROUP_MEMBERS_LIMIT
    return {"data": base, **({"meta": meta} if meta else {})}


# ── CRUD: POST /groups / PATCH /groups/{id} / DELETE /groups/{id} ─────────────


class GroupCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("이름은 비어 있을 수 없습니다")
        return s


class GroupUpdateBody(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    description: Optional[str] = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def _strip_name_opt(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = v.strip()
        if not s:
            raise ValueError("이름은 비어 있을 수 없습니다")
        return s


@router.post("/groups", dependencies=[Depends(verify_csrf)], response_model=None)
def create_group_route(
    body: GroupCreateBody,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    """그룹 생성. name 은 UNIQUE — 충돌 시 409."""
    try:
        g = svc_create_group(
            db, name=body.name, created_by=user.sub, description=body.description,
        )
        db.flush()
    except IntegrityError:
        db.rollback()
        return JSONResponse(
            {"error": {
                "code": "duplicate_name",
                "message": "같은 이름의 그룹이 이미 있습니다",
                "fields": {"name": "중복"},
            }},
            status_code=409,
        )
    audit.log(
        db,
        actor_sub=user.sub,
        action="GROUP_CREATE",
        target=f"group:{g.id}",
        detail={"name": g.name},
    )
    db.commit()
    return {"data": _group_to_dict(g, counts=(0, 0), last_camp_at=None)}


@router.patch(
    "/groups/{gid}",
    dependencies=[Depends(verify_csrf)],
    response_model=None,
)
def update_group_route(
    gid: str,
    body: GroupUpdateBody,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    gid_int = _parse_gid(gid)
    if gid_int is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "그룹을 찾을 수 없습니다"}},
            status_code=404,
        )
    updates = body.model_dump(exclude_none=True)
    if not updates:
        # 아무 변경 없음 → 현재 상태 그대로.
        g = db.get(ContactGroup, gid_int)
        if g is None:
            return JSONResponse(
                {"error": {"code": "not_found", "message": "그룹을 찾을 수 없습니다"}},
                status_code=404,
            )
        counts = _batch_member_counts(db, [g.id]).get(g.id)
        last_camp = _batch_last_campaign_times(db, [g.id]).get(g.id)
        return {"data": _group_to_dict(g, counts, last_camp)}
    try:
        g = svc_update_group(db, gid_int, **updates)
    except ValueError:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "그룹을 찾을 수 없습니다"}},
            status_code=404,
        )
    except IntegrityError:
        db.rollback()
        return JSONResponse(
            {"error": {
                "code": "duplicate_name",
                "message": "같은 이름의 그룹이 이미 있습니다",
            }},
            status_code=409,
        )
    audit.log(
        db,
        actor_sub=user.sub,
        action="GROUP_UPDATE",
        target=f"group:{gid_int}",
        detail={"fields": sorted(updates.keys())},
    )
    db.commit()
    counts = _batch_member_counts(db, [g.id]).get(g.id)
    last_camp = _batch_last_campaign_times(db, [g.id]).get(g.id)
    return {"data": _group_to_dict(g, counts, last_camp)}


@router.delete(
    "/groups/{gid}",
    dependencies=[Depends(verify_csrf)],
    response_model=None,
)
def delete_group_route(
    gid: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    """그룹 삭제. 멤버십(contact_group_members) 은 CASCADE 로 자동 정리."""
    gid_int = _parse_gid(gid)
    if gid_int is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "그룹을 찾을 수 없습니다"}},
            status_code=404,
        )
    existing = db.get(ContactGroup, gid_int)
    if existing is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "그룹을 찾을 수 없습니다"}},
            status_code=404,
        )
    try:
        svc_delete_group(db, gid_int)
    except ValueError:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "그룹을 찾을 수 없습니다"}},
            status_code=404,
        )
    audit.log(
        db,
        actor_sub=user.sub,
        action="GROUP_DELETE",
        target=f"group:{gid_int}",
        detail={"name": existing.name},
    )
    db.commit()
    return {"data": {"id": gid, "deleted": True}}


# ── 멤버 add/bulk-add/remove ─────────────────────────────────────────────────


class GroupMembersAddBody(BaseModel):
    """기존 연락처 id 목록을 그룹에 추가."""

    contactIds: list[int] = Field(..., min_length=1, max_length=10000)


class GroupMembersBulkAddBody(BaseModel):
    """전화번호 목록으로 일괄 추가. autoCreate=True 면 없는 연락처는 생성."""

    phones: list[str] = Field(..., min_length=1, max_length=10000)
    autoCreate: bool = True


class GroupMembersRemoveBody(BaseModel):
    contactIds: list[int] = Field(..., min_length=1, max_length=10000)


def _group_or_404(db: Session, gid: str) -> ContactGroup | JSONResponse:
    """gid 파싱 + DB 조회 묶음 헬퍼. 실패 시 JSONResponse 반환."""
    gid_int = _parse_gid(gid)
    if gid_int is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "그룹을 찾을 수 없습니다"}},
            status_code=404,
        )
    group = db.get(ContactGroup, gid_int)
    if group is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "그룹을 찾을 수 없습니다"}},
            status_code=404,
        )
    return group


@router.post(
    "/groups/{gid}/members/add",
    dependencies=[Depends(verify_csrf)],
    response_model=None,
)
def add_members_route(
    gid: str,
    body: GroupMembersAddBody,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    g_or_err = _group_or_404(db, gid)
    if isinstance(g_or_err, JSONResponse):
        return g_or_err
    group = g_or_err
    added = svc_add_members(
        db, group_id=group.id, contact_ids=body.contactIds, added_by=user.sub,
    )
    audit.log(
        db,
        actor_sub=user.sub,
        action="GROUP_MEMBERS_ADD",
        target=f"group:{group.id}",
        detail={"added": added, "requested": len(body.contactIds)},
    )
    db.commit()
    return {"data": {"added": added, "requested": len(body.contactIds)}}


@router.post(
    "/groups/{gid}/members/bulk-add",
    dependencies=[Depends(verify_csrf)],
    response_model=None,
)
def bulk_add_members_route(
    gid: str,
    body: GroupMembersBulkAddBody,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    """전화번호 리스트로 그룹에 멤버 일괄 추가.

    각 번호: (1) 기존 연락처 → 그룹 추가, (2) 없음 + autoCreate=true → 생성 후
    추가, (3) 없음 + autoCreate=false → skipped_no_contact.
    """
    g_or_err = _group_or_404(db, gid)
    if isinstance(g_or_err, JSONResponse):
        return g_or_err
    group = g_or_err
    # phone 정규화 — 숫자만 추출, 빈 값 제외, 중복 제거.
    normalized: list[str] = []
    seen: set[str] = set()
    for p in body.phones:
        digits = "".join(c for c in p if c.isdigit())
        if digits and digits not in seen:
            seen.add(digits)
            normalized.append(digits)
    if not normalized:
        return JSONResponse(
            {"error": {"code": "no_valid_phones", "message": "유효한 번호가 없습니다"}},
            status_code=422,
        )
    result = svc_bulk_add_by_phones(
        db,
        group_id=group.id,
        phones=normalized,
        added_by=user.sub,
        auto_create=body.autoCreate,
    )
    audit.log(
        db,
        actor_sub=user.sub,
        action="GROUP_MEMBERS_BULK_ADD",
        target=f"group:{group.id}",
        detail={**result, "requested": len(normalized)},
    )
    db.commit()
    return {"data": {**result, "requested": len(normalized)}}


@router.post(
    "/groups/{gid}/members/remove",
    dependencies=[Depends(verify_csrf)],
    response_model=None,
)
def remove_members_route(
    gid: str,
    body: GroupMembersRemoveBody,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    g_or_err = _group_or_404(db, gid)
    if isinstance(g_or_err, JSONResponse):
        return g_or_err
    group = g_or_err
    removed = svc_remove_members(
        db, group_id=group.id, contact_ids=body.contactIds,
    )
    audit.log(
        db,
        actor_sub=user.sub,
        action="GROUP_MEMBERS_REMOVE",
        target=f"group:{group.id}",
        detail={"removed": removed, "requested": len(body.contactIds)},
    )
    db.commit()
    return {"data": {"removed": removed, "requested": len(body.contactIds)}}
