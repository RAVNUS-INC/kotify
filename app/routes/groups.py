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
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_complete, require_user
from app.db import get_db
from app.models import (
    Campaign,
    Contact,
    ContactGroup,
    ContactGroupMember,
    Message,
)
from app.routes.contacts import (
    _batch_group_ids,
    _batch_last_campaign_labels,
    _contact_to_dict,
    _fmt_kst_dt,
)
from app.services.groups import list_groups as svc_list_groups

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
