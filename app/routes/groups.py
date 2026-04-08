"""그룹 라우트."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.deps import require_role, require_setup_complete
from app.db import get_db
from app.models import User
from app.security.csrf import verify_csrf
from app.services import audit
from app.services.contacts import list_contacts
from app.services.groups import (
    add_members,
    bulk_add_by_phones,
    create_group,
    delete_group,
    get_group,
    get_group_size,
    list_groups,
    list_members,
    remove_members,
    update_group,
)
from app.web import templates

router = APIRouter(prefix="/groups")

_viewer_dep = require_role("viewer", "sender", "admin")
_sender_dep = require_role("sender", "admin")
_admin_dep = require_role("admin")


def _parse_user_roles(user: User) -> list[str]:
    try:
        return json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        return []


# ── 목록 ─────────────────────────────────────────────────────────────────────


@router.get("", response_class=HTMLResponse)
async def groups_list(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_viewer_dep),
    _: None = Depends(require_setup_complete),
    search: str = Query(""),
    page: int = Query(1, ge=1),
) -> HTMLResponse:
    """그룹 목록."""
    per_page = 50
    groups, total = list_groups(db, search=search or None, page=page, per_page=per_page)
    total_pages = max(1, (total + per_page - 1) // per_page)

    # 각 그룹의 멤버 수 계산
    group_sizes = {g.id: get_group_size(db, g.id) for g in groups}

    return templates.TemplateResponse(
        request,
        "groups/list.html",
        {
            "user": user,
            "user_roles": _parse_user_roles(user),
            "groups": groups,
            "group_sizes": group_sizes,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "search": search,
        },
    )


# ── 새 그룹 폼 ────────────────────────────────────────────────────────────────


@router.get("/new", response_class=HTMLResponse)
async def group_new_form(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """그룹 추가 폼."""
    return templates.TemplateResponse(
        request,
        "groups/form.html",
        {
            "user": user,
            "user_roles": _parse_user_roles(user),
            "group": None,
            "action": "/groups",
        },
    )


# ── 생성 ─────────────────────────────────────────────────────────────────────


@router.post("")
async def group_create(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _csrf: None = Depends(verify_csrf),
    name: str = Form(...),
    description: str = Form(""),
) -> RedirectResponse:
    """그룹 생성."""
    group = create_group(
        db,
        name=name.strip(),
        created_by=user.sub,
        description=description.strip() or None,
    )
    audit.log(
        db,
        actor_sub=user.sub,
        action="GROUP_CREATE",
        target=f"group:{group.id}",
        detail={"name": name},
    )
    db.commit()
    return RedirectResponse(f"/groups/{group.id}?created=1", status_code=303)


# ── 상세 + 멤버 관리 ──────────────────────────────────────────────────────────


@router.get("/{group_id}", response_class=HTMLResponse)
async def group_detail(
    group_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_viewer_dep),
    _: None = Depends(require_setup_complete),
    page: int = Query(1, ge=1),
    search: str = Query(""),
) -> HTMLResponse:
    """그룹 상세 및 멤버 관리."""
    group = get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404)

    per_page = 50
    members, member_total = list_members(db, group_id, page=page, per_page=per_page)
    member_total_pages = max(1, (member_total + per_page - 1) // per_page)

    # 멤버 추가용 연락처 검색
    all_contacts, _ = list_contacts(db, search=search or None, per_page=200)

    # 현재 멤버 ID 집합 (체크박스 상태용)
    member_ids = {m.id for m in members}

    return templates.TemplateResponse(
        request,
        "groups/detail.html",
        {
            "user": user,
            "user_roles": _parse_user_roles(user),
            "group": group,
            "members": members,
            "member_total": member_total,
            "member_total_pages": member_total_pages,
            "page": page,
            "per_page": per_page,
            "all_contacts": all_contacts,
            "member_ids": member_ids,
            "search": search,
        },
    )


# ── 편집 폼 ──────────────────────────────────────────────────────────────────


@router.get("/{group_id}/edit", response_class=HTMLResponse)
async def group_edit_form(
    group_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """그룹 편집 폼."""
    group = get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404)

    return templates.TemplateResponse(
        request,
        "groups/form.html",
        {
            "user": user,
            "user_roles": _parse_user_roles(user),
            "group": group,
            "action": f"/groups/{group_id}/edit",
        },
    )


# ── 편집 처리 ─────────────────────────────────────────────────────────────────


@router.post("/{group_id}/edit")
async def group_edit(
    group_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _csrf: None = Depends(verify_csrf),
    name: str = Form(...),
    description: str = Form(""),
) -> RedirectResponse:
    """그룹 수정."""
    group = get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404)

    update_group(db, group_id, name=name.strip(), description=description.strip() or None)
    audit.log(
        db,
        actor_sub=user.sub,
        action="GROUP_UPDATE",
        target=f"group:{group_id}",
        detail={"name": name},
    )
    db.commit()
    return RedirectResponse(f"/groups/{group_id}?updated=1", status_code=303)


# ── 삭제 ─────────────────────────────────────────────────────────────────────


@router.post("/{group_id}/delete")
async def group_delete(
    group_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_admin_dep),
    _csrf: None = Depends(verify_csrf),
) -> RedirectResponse:
    """그룹 삭제 (admin 전용)."""
    group = get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404)

    audit.log(
        db,
        actor_sub=user.sub,
        action="GROUP_DELETE",
        target=f"group:{group_id}",
        detail={"name": group.name},
    )
    delete_group(db, group_id)
    db.commit()
    return RedirectResponse("/groups?deleted=1", status_code=303)


# ── 멤버 추가 ─────────────────────────────────────────────────────────────────


@router.post("/{group_id}/members/add")
async def group_members_add(
    group_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _csrf: None = Depends(verify_csrf),
) -> RedirectResponse:
    """멤버 추가 (form: contact_ids, 다중 값)."""
    group = get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404)

    form_data = await request.form()
    raw_ids = form_data.getlist("contact_ids")
    contact_ids = []
    for v in raw_ids:
        try:
            contact_ids.append(int(v))
        except (ValueError, TypeError):
            pass

    added = add_members(db, group_id, contact_ids, added_by=user.sub)
    audit.log(
        db,
        actor_sub=user.sub,
        action="GROUP_MEMBERS_ADD",
        target=f"group:{group_id}",
        detail={"added": added},
    )
    db.commit()
    return RedirectResponse(f"/groups/{group_id}?added={added}", status_code=303)


# ── 멤버 일괄 추가 (전화번호 paste) ──────────────────────────────────────────


@router.post("/{group_id}/members/bulk-add")
async def group_members_bulk_add(
    group_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _csrf: None = Depends(verify_csrf),
    phones_text: str = Form(...),
    auto_create: str = Form(""),
) -> RedirectResponse:
    """전화번호 일괄 paste로 멤버 추가.

    phones_text: 줄바꿈/콤마/세미콜론으로 구분된 전화번호 텍스트.
    auto_create: "1"이면 없는 연락처 자동 생성.
    """
    from app.util.phone import parse_phone_list

    group = get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404)

    valid_phones, invalid_originals = parse_phone_list(phones_text)
    auto_create_flag = auto_create == "1"

    result = bulk_add_by_phones(
        db,
        group_id=group_id,
        phones=valid_phones,
        added_by=user.sub,
        auto_create=auto_create_flag,
    )

    audit.log(
        db,
        actor_sub=user.sub,
        action="GROUP_MEMBERS_BULK_ADD",
        target=f"group:{group_id}",
        detail={
            "valid": len(valid_phones),
            "invalid": len(invalid_originals),
            **result,
        },
    )
    db.commit()

    # 결과를 query string으로 전달
    params = {
        "bulk_added": result["added_existing"],
        "bulk_created": result["created_new"],
        "bulk_skipped_member": result["skipped_existing_member"],
        "bulk_skipped_no_contact": result["skipped_no_contact"],
        "bulk_invalid": len(invalid_originals),
    }
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    return RedirectResponse(f"/groups/{group_id}?{qs}", status_code=303)


# ── 멤버 제거 ─────────────────────────────────────────────────────────────────


@router.post("/{group_id}/members/remove")
async def group_members_remove(
    group_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _csrf: None = Depends(verify_csrf),
) -> RedirectResponse:
    """멤버 제거 (form: contact_ids, 다중 값)."""
    group = get_group(db, group_id)
    if group is None:
        raise HTTPException(status_code=404)

    form_data = await request.form()
    raw_ids = form_data.getlist("contact_ids")
    contact_ids = []
    for v in raw_ids:
        try:
            contact_ids.append(int(v))
        except (ValueError, TypeError):
            pass

    removed = remove_members(db, group_id, contact_ids)
    audit.log(
        db,
        actor_sub=user.sub,
        action="GROUP_MEMBERS_REMOVE",
        target=f"group:{group_id}",
        detail={"removed": removed},
    )
    db.commit()
    return RedirectResponse(f"/groups/{group_id}?removed={removed}", status_code=303)
