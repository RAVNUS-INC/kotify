"""캠페인 이력 라우트."""
from __future__ import annotations

import csv
import io
import json
from datetime import UTC

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_complete, require_user
from app.db import get_db
from app.models import Attachment, Campaign, Message, MsghubRequest, User
from app.security.csrf import verify_csrf
from app.web import templates

router = APIRouter(prefix="/campaigns")


def _is_admin(user: User) -> bool:
    try:
        return "admin" in json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        return False


def _can_access_campaign(user: User, campaign: Campaign) -> bool:
    return _is_admin(user) or campaign.created_by == user.sub


@router.get("", response_class=HTMLResponse)
async def campaigns_list(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
    status: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20),
    sort: str = Query("created_at"),
    order: str = Query("desc"),
) -> HTMLResponse:
    """캠페인 목록. viewer는 본인 것만, admin은 전체. H7 per_page, M16 작성자 email."""
    # H7: per_page clamp
    per_page = max(1, min(per_page, 200))

    # H5: 정렬 컬럼 허용 목록
    _sort_cols = {
        "created_at": Campaign.created_at,
        "ok_count": Campaign.ok_count,
        "fail_count": Campaign.fail_count,
    }
    sort_col = _sort_cols.get(sort, Campaign.created_at)
    sort_expr = sort_col.desc() if order != "asc" else sort_col.asc()
    stmt = select(Campaign).order_by(sort_expr)

    if not _is_admin(user):
        stmt = stmt.where(Campaign.created_by == user.sub)

    if status:
        stmt = stmt.where(Campaign.state == status)
    if date_from:
        stmt = stmt.where(Campaign.created_at >= date_from)
    if date_to:
        # 다음 날 00:00:00 미만으로 비교하여 date_to 당일 전체를 포함 (I6)
        from datetime import datetime, timedelta
        try:
            date_to_dt = datetime.strptime(date_to, "%Y-%m-%d").replace(tzinfo=UTC)
            next_day_dt = date_to_dt + timedelta(days=1)
            stmt = stmt.where(Campaign.created_at < next_day_dt.isoformat())
        except ValueError:
            stmt = stmt.where(Campaign.created_at <= date_to + "T23:59:59.999999+00:00")

    offset = (page - 1) * per_page

    # #14: COUNT 쿼리로 OOM 방지
    total_count = db.execute(
        select(func.count()).select_from(stmt.subquery())
    ).scalar_one()

    paginated = list(
        db.execute(stmt.offset(offset).limit(per_page)).scalars().all()
    )

    # M16: 작성자 sub → email 매핑 (admin 전용)
    creator_emails: dict[str, str] = {}
    if _is_admin(user) and paginated:
        subs = list({c.created_by for c in paginated if c.created_by})
        if subs:
            rows = db.execute(
                select(User.sub, User.email).where(User.sub.in_(subs))
            ).all()
            creator_emails = {row[0]: row[1] for row in rows if row[1]}

    try:
        user_roles = json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        user_roles = []

    return templates.TemplateResponse(
        request,
        "campaigns/list.html",
        {
            "user": user,
            "user_roles": user_roles,
            "campaigns": paginated,
            "total_count": total_count,
            "page": page,
            "per_page": per_page,
            "status_filter": status,
            "date_from": date_from,
            "date_to": date_to,
            "is_admin": _is_admin(user),
            "sort": sort,
            "order": order,
            "creator_emails": creator_emails,
        },
    )


@router.get("/{campaign_id}", response_class=HTMLResponse)
async def campaign_detail(
    campaign_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """캠페인 상세. H14: 첫 페이지 수신자를 미리 fetch하여 더블 깜박임 제거."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="캠페인을 찾을 수 없습니다.")
    if not _can_access_campaign(user, campaign):
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    try:
        user_roles = json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        user_roles = []

    # H14: 첫 페이지 수신자 미리 로드 (HTMX는 폴링에만 갱신)
    per_page = 50
    first_page_messages = list(
        db.execute(
            select(Message)
            .where(Message.campaign_id == campaign_id)
            .order_by(Message.id)
            .limit(per_page)
        ).scalars().all()
    )
    total_recipients = db.execute(
        select(func.count()).select_from(
            select(Message).where(Message.campaign_id == campaign_id).subquery()
        )
    ).scalar_one()

    return templates.TemplateResponse(
        request,
        "campaigns/detail.html",
        {
            "user": user,
            "user_roles": user_roles,
            "campaign": campaign,
            "is_admin": _is_admin(user),
            "first_page_messages": first_page_messages,
            "total_recipients": total_recipients,
            "per_page": per_page,
        },
    )


@router.get("/{campaign_id}/progress", response_class=HTMLResponse)
async def campaign_progress(
    campaign_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
) -> HTMLResponse:
    """진행 카드 fragment (HTMX 폴링용)."""
    campaign = db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404)
    if not _can_access_campaign(user, campaign):
        raise HTTPException(403)
    return templates.TemplateResponse(
        request,
        "campaigns/_progress.html",
        {"campaign": campaign},
    )


@router.get("/{campaign_id}/recipients", response_class=HTMLResponse)
async def campaign_recipients(
    campaign_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
    page: int = Query(1, ge=1),
    status: str | None = Query(None),
) -> HTMLResponse:
    """HTMX fragment — 수신자 결과 테이블 (페이지네이션 50건)."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404)
    if not _can_access_campaign(user, campaign):
        raise HTTPException(status_code=403)

    per_page = 50
    offset = (page - 1) * per_page

    # C2: status 필터 적용
    base_stmt = select(Message).where(Message.campaign_id == campaign_id)
    if status == "success":
        base_stmt = base_stmt.where(
            Message.status == "DONE", Message.result_code == "10000"
        )
    elif status == "fail":
        base_stmt = base_stmt.where(
            (Message.status == "FAILED")
            | ((Message.status == "DONE") & (Message.result_code != "10000"))
        )
    elif status == "pending":
        base_stmt = base_stmt.where(Message.status.in_(["PENDING", "REG", "ING", "FB_PENDING"]))

    total_count = db.execute(
        select(func.count()).select_from(base_stmt.subquery())
    ).scalar_one()

    messages = list(
        db.execute(
            base_stmt.order_by(Message.id).offset(offset).limit(per_page)
        ).scalars().all()
    )

    try:
        user_roles = json.loads(user.roles)
    except (json.JSONDecodeError, TypeError):
        user_roles = []

    return templates.TemplateResponse(
        request,
        "campaigns/_recipients.html",
        {
            "messages": messages,
            "campaign": campaign,
            "page": page,
            "per_page": per_page,
            "total_count": total_count,
            "status_filter": status,
            "user_roles": user_roles,
        },
    )


@router.get("/{campaign_id}/export")
async def campaign_export(
    campaign_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
    status: str | None = Query(None),
) -> StreamingResponse:
    """C2: 수신자 CSV 다운로드 (status=fail 등 필터 지원)."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404)
    if not _can_access_campaign(user, campaign):
        raise HTTPException(status_code=403)

    base_stmt = select(Message).where(Message.campaign_id == campaign_id)
    if status == "success":
        base_stmt = base_stmt.where(
            Message.status == "DONE", Message.result_code == "10000"
        )
    elif status == "fail":
        base_stmt = base_stmt.where(
            (Message.status == "FAILED")
            | ((Message.status == "DONE") & (Message.result_code != "10000"))
        )
    elif status == "pending":
        base_stmt = base_stmt.where(Message.status.in_(["PENDING", "REG", "ING", "FB_PENDING"]))

    messages = list(db.execute(base_stmt.order_by(Message.id)).scalars().all())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["번호", "채널", "상태", "결과코드", "결과설명", "Fallback사유", "비용(원)", "완료시각"])
    for msg in messages:
        fb_desc = ""
        if msg.fb_reason:
            try:
                fb_list = json.loads(msg.fb_reason)
                fb_desc = "; ".join(f.get("desc", f.get("code", "")) for f in fb_list)
            except (ValueError, TypeError):
                fb_desc = ""
        writer.writerow([
            msg.to_number,
            msg.channel or "",
            "성공" if msg.result_code == "10000" else ("실패" if msg.status in ("DONE", "FAILED") else "대기"),
            msg.result_code or "",
            msg.result_desc or "",
            fb_desc,
            msg.cost if msg.cost else 0,
            msg.complete_time or "",
        ])

    fname_suffix = f"_{status}" if status else ""
    filename = f"campaign_{campaign_id}{fname_suffix}.csv"

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/{campaign_id}/cancel-reservation", response_class=HTMLResponse)
async def campaign_cancel_reservation(
    campaign_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
    _csrf: None = Depends(verify_csrf),
) -> HTMLResponse:
    """예약 발송을 취소한다 (sender/admin 전용).

    권한/상태 체크:
    - 권한: sender/admin (본인 캠페인이거나 admin)
    - 상태: ``campaign.state == "RESERVED"`` 인 경우만 허용
    - 캠페인에는 청크 수만큼 MsghubRequest가 있고, 각각이 별도의 msghub 예약이다.
      모든 MsghubRequest.request_id 에 대해 개별적으로 취소를 시도한다.
    """
    from app.msghub.schemas import MsghubBadRequest, MsghubError
    from app.services import audit

    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="캠페인을 찾을 수 없습니다.")
    if not _can_access_campaign(user, campaign):
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    # sender/admin 역할 체크 (viewer는 자기 캠페인이어도 취소 불가)
    try:
        roles = set(json.loads(user.roles))
    except (json.JSONDecodeError, TypeError):
        roles = set()
    if not (roles & {"sender", "admin"}):
        raise HTTPException(status_code=403, detail="예약 취소 권한이 없습니다.")

    if campaign.state != "RESERVED":
        raise HTTPException(
            status_code=400,
            detail=f"예약 상태({campaign.state})가 아니므로 취소할 수 없습니다.",
        )

    from app.main import get_msghub_client  # noqa: PLC0415
    msghub_client = get_msghub_client()
    if msghub_client is None:
        raise HTTPException(status_code=503, detail="msghub 설정이 완료되지 않았습니다.")

    # msghub는 캠페인당 web_req_id 하나로 예약 취소
    if not campaign.web_req_id:
        raise HTTPException(status_code=400, detail="예약 ID가 없습니다.")

    try:
        await msghub_client.cancel_reservation(campaign.web_req_id, reason="사용자 취소")
        campaign.state = "RESERVE_CANCELED"
        final_msg = "예약이 취소되었습니다."
    except MsghubBadRequest as exc:
        # 이미 실행되었거나 취소된 예약
        campaign.state = "RESERVE_CANCELED"
        final_msg = f"예약이 이미 처리되었습니다: {exc}"
    except MsghubError as exc:
        db.rollback()
        raise HTTPException(
            status_code=400,
            detail=f"예약 취소 실패: {exc}. 잠시 후 다시 시도해주세요.",
        )

    audit.log(
        db,
        actor_sub=user.sub,
        action=audit.CANCEL_RESERVE,
        target=f"campaign:{campaign.id}",
        detail={
            "successes": len(successes),
            "already_gone": len(already_gone),
            "resolved_done": resolved_done,
            "final_state": campaign.state,
        },
    )
    db.commit()
    return HTMLResponse(f'<span class="ok">✓ {final_msg}</span>')


@router.get("/{campaign_id}/attachment/{attachment_id}")
async def campaign_attachment(
    campaign_id: int,
    attachment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
) -> Response:
    """첨부 이미지 BLOB 스트리밍 (MMS 캠페인 상세에서 사용)."""
    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="캠페인을 찾을 수 없습니다.")
    if not _can_access_campaign(user, campaign):
        raise HTTPException(status_code=403, detail="권한이 없습니다.")

    attachment = db.get(Attachment, attachment_id)
    if attachment is None or attachment.campaign_id != campaign_id:
        raise HTTPException(status_code=404, detail="첨부 파일을 찾을 수 없습니다.")

    return Response(
        content=attachment.content_blob,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, max-age=3600",
            "Content-Length": str(attachment.file_size_bytes),
        },
    )


@router.post("/{campaign_id}/refresh", response_class=HTMLResponse)
async def campaign_refresh(
    campaign_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    _: None = Depends(require_setup_complete),
    _csrf: None = Depends(verify_csrf),
) -> HTMLResponse:
    """HTMX — 미완료 메시지를 msghub에서 cliKey로 재조회.

    msghub는 웹훅 기반이라 대부분 자동 반영되지만, 네트워크 단절/웹훅 유실 등
    엣지 케이스에서 수동으로 상태를 동기화할 수 있게 한다.
    """
    from sqlalchemy import select as sa_select  # noqa: PLC0415

    from app.main import get_msghub_client  # noqa: PLC0415
    from app.models import Message  # noqa: PLC0415
    from app.services.report import process_sent_query  # noqa: PLC0415

    campaign = db.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404)
    if not _can_access_campaign(user, campaign):
        raise HTTPException(status_code=403)

    msghub_client = get_msghub_client()
    if msghub_client is None:
        return HTMLResponse(
            '<span class="err">msghub 설정이 완료되지 않았습니다.</span>'
        )

    # 미완료 메시지 조회 (최대 10건 — msghub query_sent 제약)
    pending_msgs = list(
        db.execute(
            sa_select(Message)
            .where(
                Message.campaign_id == campaign_id,
                Message.status.in_(("PENDING", "REG", "ING", "FB_PENDING")),
                Message.cli_key.is_not(None),
            )
            .limit(10)
        ).scalars().all()
    )

    if not pending_msgs:
        return HTMLResponse(
            '<span class="text-muted">대기 중인 메시지가 없습니다.</span>'
        )

    # cliKey + 발송일(YYYY-MM-DD) 튜플로 변환
    req_dt = (campaign.created_at or "")[:10]
    cli_keys = [(m.cli_key, req_dt) for m in pending_msgs]

    try:
        raw_items = await msghub_client.query_sent(cli_keys)
    except Exception as exc:
        return HTMLResponse(
            f'<span class="err">조회 실패: {exc}</span>'
        )

    processed = process_sent_query(db, raw_items)
    db.commit()

    return HTMLResponse(
        f'<span class="ok">✓ {processed}건 상태 갱신됨</span>'
    )
