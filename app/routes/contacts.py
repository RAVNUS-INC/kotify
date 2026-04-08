"""주소록 라우트."""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.deps import require_role, require_setup_complete
from app.db import get_db
from app.models import User
from app.security.csrf import verify_csrf
from app.services import audit
from app.services.contacts import (
    create_contact,
    delete_contact,
    get_contact,
    list_contacts,
    update_contact,
)
from app.services.csv_import import export_contacts, import_contacts, parse_csv
from app.util.phone import normalize_phone
from app.web import templates

router = APIRouter(prefix="/contacts")

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
async def contacts_list(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_viewer_dep),
    _: None = Depends(require_setup_complete),
    search: str = Query(""),
    department: str = Query(""),
    active_only: bool = Query(False),
    page: int = Query(1, ge=1),
    per_page: int = Query(50),
    sort: str = Query("name"),
    order: str = Query("asc"),
) -> HTMLResponse:
    """연락처 목록. H7 per_page 지원."""
    # H7: clamp
    per_page = max(1, min(per_page, 200))
    contacts, total = list_contacts(
        db,
        search=search or None,
        department=department or None,
        active_only=active_only,
        page=page,
        per_page=per_page,
        sort=sort,
        order=order,
    )
    total_pages = max(1, (total + per_page - 1) // per_page)

    return templates.TemplateResponse(
        request,
        "contacts/list.html",
        {
            "user": user,
            "user_roles": _parse_user_roles(user),
            "contacts": contacts,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "per_page": per_page,
            "search": search,
            "department": department,
            "active_only": active_only,
            "sort": sort,
            "order": order,
        },
    )


# ── 새 연락처 폼 ──────────────────────────────────────────────────────────────


@router.get("/new", response_class=HTMLResponse)
async def contact_new_form(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """연락처 추가 폼."""
    return templates.TemplateResponse(
        request,
        "contacts/form.html",
        {
            "user": user,
            "user_roles": _parse_user_roles(user),
            "contact": None,
            "action": "/contacts",
        },
    )


# ── 생성 ─────────────────────────────────────────────────────────────────────


@router.post("")
async def contact_create(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _csrf: None = Depends(verify_csrf),
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    department: str = Form(""),
    notes: str = Form(""),
) -> RedirectResponse:
    """연락처 생성."""
    normalized_phone: str | None = None
    if phone.strip():
        normalized_phone = normalize_phone(phone.strip())
        if normalized_phone is None:
            return RedirectResponse("/contacts/new?error=invalid_phone", status_code=303)

    # M3: 전화번호 또는 이메일 중 하나 이상 필수 (라우트 레벨 검증)
    if not normalized_phone and not email.strip():
        return RedirectResponse("/contacts/new?error=phone_or_email_required", status_code=303)

    contact = create_contact(
        db,
        name=name.strip(),
        created_by=user.sub,
        phone=normalized_phone,
        email=email.strip() or None,
        department=department.strip() or None,
        notes=notes.strip() or None,
    )
    audit.log(
        db,
        actor_sub=user.sub,
        action="CONTACT_CREATE",
        target=f"contact:{contact.id}",
        detail={"name": name},
    )
    db.commit()
    return RedirectResponse(f"/contacts/{contact.id}?created=1", status_code=303)


# ── CSV import 폼 ─────────────────────────────────────────────────────────────


@router.get("/import", response_class=HTMLResponse)
async def contact_import_form(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """CSV import 폼."""
    return templates.TemplateResponse(
        request,
        "contacts/import.html",
        {
            "user": user,
            "user_roles": _parse_user_roles(user),
            "result": None,
        },
    )


# ── CSV import 처리 ───────────────────────────────────────────────────────────


@router.post("/import", response_class=HTMLResponse)
async def contact_import_post(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _csrf: None = Depends(verify_csrf),
    csv_file: UploadFile = File(...),
    mode: str = Form("skip"),
) -> HTMLResponse:
    """CSV 파일 업로드 처리."""
    raw_bytes = await csv_file.read()
    try:
        content = raw_bytes.decode("utf-8-sig")  # BOM 허용
    except UnicodeDecodeError:
        content = raw_bytes.decode("euc-kr", errors="replace")

    valid_rows, invalid_rows = parse_csv(content)
    import_result = import_contacts(db, valid_rows, created_by=user.sub, mode=mode)
    db.commit()

    audit.log(
        db,
        actor_sub=user.sub,
        action="CONTACT_IMPORT",
        detail={
            "created": import_result["created"],
            "updated": import_result["updated"],
            "skipped": import_result["skipped"],
            "invalid": len(invalid_rows),
        },
    )
    db.commit()

    return templates.TemplateResponse(
        request,
        "contacts/import.html",
        {
            "user": user,
            "user_roles": _parse_user_roles(user),
            "result": import_result,
            "invalid_rows": invalid_rows,
        },
    )


# ── CSV export ────────────────────────────────────────────────────────────────


@router.get("/export")
async def contact_export(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_viewer_dep),
    _: None = Depends(require_setup_complete),
) -> PlainTextResponse:
    """전체 연락처를 CSV로 다운로드."""
    csv_content = export_contacts(db)
    return PlainTextResponse(
        csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=contacts.csv"},
    )


# ── 상세 ─────────────────────────────────────────────────────────────────────


@router.get("/{contact_id}", response_class=HTMLResponse)
async def contact_detail(
    contact_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_viewer_dep),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """연락처 상세."""
    contact = get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(status_code=404)

    # 소속 그룹 목록
    from sqlalchemy import select

    from app.models import ContactGroup, ContactGroupMember
    groups = list(
        db.execute(
            select(ContactGroup)
            .join(ContactGroupMember, ContactGroupMember.group_id == ContactGroup.id)
            .where(ContactGroupMember.contact_id == contact_id)
            .order_by(ContactGroup.name)
        ).scalars().all()
    )

    return templates.TemplateResponse(
        request,
        "contacts/detail.html",
        {
            "user": user,
            "user_roles": _parse_user_roles(user),
            "contact": contact,
            "groups": groups,
        },
    )


# ── 편집 폼 ──────────────────────────────────────────────────────────────────


@router.get("/{contact_id}/edit", response_class=HTMLResponse)
async def contact_edit_form(
    contact_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """연락처 편집 폼."""
    contact = get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(status_code=404)

    return templates.TemplateResponse(
        request,
        "contacts/form.html",
        {
            "user": user,
            "user_roles": _parse_user_roles(user),
            "contact": contact,
            "action": f"/contacts/{contact_id}/edit",
        },
    )


# ── 편집 처리 ─────────────────────────────────────────────────────────────────


@router.post("/{contact_id}/edit")
async def contact_edit(
    contact_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_sender_dep),
    _csrf: None = Depends(verify_csrf),
    name: str = Form(...),
    phone: str = Form(""),
    email: str = Form(""),
    department: str = Form(""),
    notes: str = Form(""),
    active: str = Form("0"),
) -> RedirectResponse:
    """연락처 수정."""
    contact = get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(status_code=404)

    normalized_phone: str | None = None
    if phone.strip():
        normalized_phone = normalize_phone(phone.strip())
        if normalized_phone is None:
            return RedirectResponse(f"/contacts/{contact_id}/edit?error=invalid_phone", status_code=303)

    update_contact(
        db,
        contact_id,
        name=name.strip(),
        phone=normalized_phone,
        email=email.strip() or None,
        department=department.strip() or None,
        notes=notes.strip() or None,
        active=1 if active == "1" else 0,
    )
    audit.log(
        db,
        actor_sub=user.sub,
        action="CONTACT_UPDATE",
        target=f"contact:{contact_id}",
        detail={"name": name},
    )
    db.commit()
    return RedirectResponse(f"/contacts/{contact_id}?updated=1", status_code=303)


# ── 삭제 ─────────────────────────────────────────────────────────────────────


@router.post("/{contact_id}/delete")
async def contact_delete(
    contact_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(_admin_dep),
    _csrf: None = Depends(verify_csrf),
) -> RedirectResponse:
    """연락처 삭제 (admin 전용)."""
    contact = get_contact(db, contact_id)
    if contact is None:
        raise HTTPException(status_code=404)

    audit.log(
        db,
        actor_sub=user.sub,
        action="CONTACT_DELETE",
        target=f"contact:{contact_id}",
        detail={"name": contact.name},
    )
    delete_contact(db, contact_id)
    db.commit()
    return RedirectResponse("/contacts?deleted=1", status_code=303)
