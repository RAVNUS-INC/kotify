"""주소록 API — S7 목록 / S8 상세.

실 DB (contacts + contact_group_members + messages/campaigns + mo_messages)
기반. services.contacts.list_contacts 를 재사용해 검색/필터 중복 구현 회피.

api-contract.md §S7/S8 — web/types/contact.ts 의 Contact / ContactDetail shape.

NOTE: Contact DB 컬럼은 `department`, TS 계약은 `team` 이므로 여기서 alias.
`tags` 컬럼은 현재 스키마에 없어 상세/목록 모두 omit (TS 는 optional 이라 안전).
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
    ContactGroupMember,
    Message,
    MoMessage,
)
from app.services.contacts import list_contacts as svc_list_contacts

router = APIRouter(
    dependencies=[Depends(require_user), Depends(require_setup_complete)],
)

KST = ZoneInfo("Asia/Seoul")


def _fmt_kst_date(iso_utc: str | None) -> str:
    """UTC ISO → 'YYYY-MM-DD' KST. 실패/None 은 빈 문자열.

    campaigns.py/_fmt_kst 와 null 처리 일관성 유지 — TS 계약(createdAt?:string)
    은 undefined 또는 string 만 허용, null 은 타입 불일치.
    """
    if not iso_utc:
        return ""
    try:
        dt = datetime.fromisoformat(iso_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(KST).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return ""


def _fmt_kst_dt(iso_utc: str | None) -> str:
    """UTC ISO → 'YYYY-MM-DD HH:MM' KST. 실패 시 빈 문자열."""
    if not iso_utc:
        return ""
    try:
        dt = datetime.fromisoformat(iso_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return ""


def _campaign_label(subject: str | None, content: str | None, cid: int) -> str:
    """(subject, content, id) → 표시 라벨. threads.py 와 동일 규칙."""
    if subject:
        return subject
    if content:
        first = content.strip().split("\n", 1)[0]
        return first[:24] + ("…" if len(first) > 24 else "")
    return f"캠페인 #{cid}"


# ── 배치 헬퍼 ────────────────────────────────────────────────────────────────


def _batch_group_ids(db: Session, contact_ids: list[int]) -> dict[int, list[str]]:
    """contact_id → ["g-{group_id}", ...] 매핑. 1쿼리."""
    if not contact_ids:
        return {}
    rows = db.execute(
        select(ContactGroupMember.contact_id, ContactGroupMember.group_id)
        .where(ContactGroupMember.contact_id.in_(contact_ids))
    ).all()
    result: dict[int, list[str]] = {}
    for cid, gid in rows:
        result.setdefault(cid, []).append(f"g-{gid}")
    return result


def _batch_last_campaign_labels(
    db: Session, phones: list[str]
) -> dict[str, str]:
    """phone → 최근 캠페인 라벨 배치 집계 (2쿼리).

    threads.py 와 동일 패턴 — max(Message.id) 로 최근 메시지를 앵커하고
    그 메시지의 campaign 을 JOIN 으로 끌어온다.
    """
    if not phones:
        return {}
    subq = (
        select(
            Message.to_number.label("p"),
            func.max(Message.id).label("last_mid"),
        )
        .where(Message.to_number.in_(phones))
        .group_by(Message.to_number)
    ).subquery()

    rows = db.execute(
        select(subq.c.p, Campaign.id, Campaign.subject, Campaign.content)
        .join(Message, Message.id == subq.c.last_mid)
        .join(Campaign, Campaign.id == Message.campaign_id)
    ).all()
    return {
        r.p: _campaign_label(r.subject, r.content, r.id)
        for r in rows
        if r.p
    }


# ── 매핑 ─────────────────────────────────────────────────────────────────────


def _contact_to_dict(
    c: Contact,
    group_ids: list[str] | None,
    last_campaign: str | None,
) -> dict:
    """Contact ORM → web/types/contact.ts Contact shape."""
    row: dict = {
        "id": str(c.id),
        "name": c.name,
        "phone": c.phone or "",
    }
    created_at = _fmt_kst_date(c.created_at)
    if created_at:
        row["createdAt"] = created_at
    if c.email:
        row["email"] = c.email
    if c.department:
        row["team"] = c.department
    if group_ids:
        row["groupIds"] = group_ids
    if last_campaign:
        row["lastCampaign"] = last_campaign
    return row


# ── S7: GET /contacts ────────────────────────────────────────────────────────


_CONTACTS_PAGE_SIZE = 1000


@router.get("/contacts", response_model=None)
def list_contacts_route(
    q: Optional[str] = None,
    groupId: Optional[str] = None,
    tag: Optional[str] = None,  # 현 스키마엔 tags 컬럼 없음 — 무시
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    """주소록 목록. q(이름·번호·이메일), groupId 필터. tag 는 스키마 미지원."""
    del tag  # explicit ignore — schema 에 tags 없음

    # 잘못된 groupId 는 '빈 목록 200' 대신 400 으로 — 클라이언트 버그 은폐 방지.
    gid_int: int | None = None
    if groupId:
        try:
            gid_int = (
                int(groupId[2:]) if groupId.startswith("g-") else int(groupId)
            )
        except (ValueError, TypeError):
            return JSONResponse(
                {"error": {
                    "code": "invalid_param",
                    "message": "groupId 형식이 올바르지 않습니다",
                }},
                status_code=400,
            )

    # services.contacts.list_contacts 는 page/per_page 기준이라 여기서 한 번에 로드.
    # 1000 상한 — 초과 시 hasMore 플래그로 프론트에 신호. svc_total 은 필터 전
    # 총합(검색 반영)이라 hasMore 산정에 적합.
    contacts, svc_total = svc_list_contacts(
        db,
        search=q or None,
        department=None,
        active_only=False,
        page=1,
        per_page=_CONTACTS_PAGE_SIZE,
        sort="name",
        order="asc",
    )

    if gid_int is not None:
        member_ids = set(
            db.execute(
                select(ContactGroupMember.contact_id)
                .where(ContactGroupMember.group_id == gid_int)
            ).scalars().all()
        )
        contacts = [c for c in contacts if c.id in member_ids]

    # 배치: groupIds + lastCampaign. 빈 리스트 시 헬퍼가 즉시 {} 반환.
    ids = [c.id for c in contacts]
    phones = [c.phone for c in contacts if c.phone]
    group_map = _batch_group_ids(db, ids)
    label_map = _batch_last_campaign_labels(db, phones)

    rows = [
        _contact_to_dict(
            c,
            group_ids=group_map.get(c.id),
            last_campaign=(label_map.get(c.phone) if c.phone else None),
        )
        for c in contacts
    ]
    # total 은 서비스 기준(검색 반영). groupId 로 걸러진 후의 개수는 len(rows).
    # hasMore 는 pre-group 총합 기준 — 1000 페이지 상한 도달 여부를 본다.
    return {
        "data": rows,
        "meta": {
            "total": svc_total,
            "hasMore": svc_total > _CONTACTS_PAGE_SIZE,
        },
    }


# ── S8: GET /contacts/{id} ───────────────────────────────────────────────────


@router.get("/contacts/{cid}", response_model=None)
def get_contact_route(cid: str, db: Session = Depends(get_db)) -> dict | JSONResponse:
    """연락처 상세 — 최근 캠페인 N건 + 회신(MO) 이력."""
    try:
        contact_id = int(cid)
    except (ValueError, TypeError):
        return JSONResponse(
            {"error": {"code": "not_found", "message": "연락처를 찾을 수 없습니다"}},
            status_code=404,
        )
    contact = db.get(Contact, contact_id)
    if contact is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "연락처를 찾을 수 없습니다"}},
            status_code=404,
        )

    group_ids = _batch_group_ids(db, [contact.id]).get(contact.id)
    last_label = None
    if contact.phone:
        last_label = _batch_last_campaign_labels(db, [contact.phone]).get(contact.phone)

    base = _contact_to_dict(contact, group_ids, last_label)

    # 최근 캠페인: 이 연락처의 phone 으로 보낸 메시지의 campaign 목록 (최근 5건).
    # 한 캠페인이 여러 메시지(재시도/분할)를 생성할 수 있으므로 campaign_id 별로
    # max(Message.id) 를 뽑아 중복 제거 — 그렇지 않으면 같은 캠페인이 5행
    # 반복되어 recentCampaigns 가 사실상 1~2개 캠페인만 보이게 된다.
    recent: list[dict] = []
    if contact.phone:
        recent_subq = (
            select(
                Message.campaign_id.label("cid"),
                func.max(Message.id).label("last_mid"),
            )
            .where(Message.to_number == contact.phone)
            .group_by(Message.campaign_id)
        ).subquery()

        # FROM 중복 방지: subq 에서 직접 Campaign 을 JOIN 하지 않고 Message
        # 를 경유 (Message.campaign_id → Campaign). threads.py 와 동일 패턴.
        rows = db.execute(
            select(
                Campaign.id,
                Campaign.subject,
                Campaign.content,
                Campaign.state,
                Message.complete_time,
                Message.report_dt,
            )
            .select_from(recent_subq)
            .join(Message, Message.id == recent_subq.c.last_mid)
            .join(Campaign, Campaign.id == Message.campaign_id)
            .order_by(Message.id.desc())
            .limit(5)
        ).all()
        # state 는 프론트 status 에 그대로 소문자 노출.
        for r in rows:
            sent_at = _fmt_kst_dt(r.complete_time or r.report_dt)
            recent.append({
                "id": str(r.id),
                "name": _campaign_label(r.subject, r.content, r.id),
                "status": (r.state or "").lower(),
                "sentAt": sent_at,
            })

    # 회신 이력: mo_messages 는 mo_number (고객 번호) 기준으로 수집.
    # 스키마상 MO 는 특정 campaign 에 직결되지 않으므로 campaignName 은
    # 시간적으로 가장 근접한 MT 캠페인을 추정 (같은 phone 의 최근 캠페인).
    replies: list[dict] = []
    if contact.phone:
        mo_rows = db.execute(
            select(MoMessage)
            .where(MoMessage.mo_number == contact.phone)
            .order_by(MoMessage.id.desc())
            .limit(10)
        ).scalars().all()
        # 이 phone 으로의 최근 캠페인 라벨 하나 — 없으면 빈 문자열.
        approx_camp = last_label or ""
        for m in mo_rows:
            replies.append({
                "id": f"mo-{m.id}",
                "campaignName": approx_camp,
                "text": m.mo_msg or "",
                "at": _fmt_kst_dt(m.mo_recv_dt),
            })

    detail = {**base}
    if recent:
        detail["recentCampaigns"] = recent
    if replies:
        detail["replyHistory"] = replies
    return {"data": detail}
