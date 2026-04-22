"""발신번호 API — S11 & S2 (발신번호 드롭다운).

api-contract.md §S11 계약:
    GET    /api/numbers?status=approved|pending|rejected|expired|all
    GET    /api/numbers/{id}
    POST   /api/numbers                  (새 발신번호 등록)
    POST   /api/numbers/{id}/toggle      (활성/비활성 전환)
    POST   /api/numbers/{id}/default     (기본 발신번호 지정)
    DELETE /api/numbers/{id}             (삭제 — 비활성 상태만 가능)

실 DB 소스: callers 테이블 (msghub Phase 에서 관리되는 발신번호).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.deps import require_role, require_setup_complete, require_user
from app.db import get_db
from app.models import Caller, Campaign, User
from app.security.csrf import verify_csrf
from app.services import audit

# 발신번호 관리는 admin 전용
router = APIRouter(
    dependencies=[Depends(require_role("admin")), Depends(require_setup_complete)],
)

KST = ZoneInfo("Asia/Seoul")


def _infer_kind(number: str) -> str:
    """번호 형식으로 kind 추론. 010/011 등 이동전화는 'mobile', 나머지는 'rep'."""
    digits = "".join(c for c in number if c.isdigit())
    if digits.startswith(("010", "011", "016", "017", "018", "019")):
        return "mobile"
    return "rep"


def _today_kst_range_utc() -> tuple[str, str]:
    """오늘 00:00 KST ~ 내일 00:00 KST 를 UTC ISO 로 반환."""
    now_kst = datetime.now(UTC).astimezone(KST)
    start_kst = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    end_kst = start_kst + timedelta(days=1)
    return start_kst.astimezone(UTC).isoformat(), end_kst.astimezone(UTC).isoformat()


def _caller_to_dict(caller: Caller, daily_usage: int) -> dict:
    """Caller ORM → web/types/number.ts SenderNumber shape.

    현재 Caller 모델엔 pending/rejected 개념이 없어 active=1 → approved,
    active=0 → expired 로 이원화. 향후 외부 통신사 등록 상태 관리가 추가되면
    별도 컬럼으로 확장 예정.
    """
    supports = ["sms"]
    if caller.rcs_enabled:
        supports.insert(0, "rcs")
    status = "approved" if caller.active else "expired"
    registered_at = (caller.created_at or "")[:10]  # YYYY-MM-DD 만
    return {
        "id": str(caller.id),
        "number": caller.number,
        "kind": _infer_kind(caller.number),
        "supports": supports,
        "brand": caller.label or caller.number,
        "status": status,
        "dailyUsage": daily_usage,
        "dailyLimit": None,
        "registeredAt": registered_at,
    }


def _daily_usage_map(db: Session) -> dict[str, int]:
    """caller_number 별 오늘 발송 건수 집계 (messages 기준)."""
    day_start, day_end = _today_kst_range_utc()
    rows = db.execute(
        select(
            Campaign.caller_number.label("num"),
            func.coalesce(func.sum(Campaign.total_count), 0).label("sent"),
        )
        .where(
            and_(
                Campaign.created_at >= day_start,
                Campaign.created_at < day_end,
            )
        )
        .group_by(Campaign.caller_number)
    ).all()
    return {r.num: int(r.sent or 0) for r in rows if r.num}


@router.get("/numbers")
def list_numbers(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
) -> dict:
    """발신번호 목록. status 필터 지원 (approved/pending/rejected/expired/all)."""
    q = select(Caller).order_by(Caller.is_default.desc(), Caller.id.asc())
    if status == "approved":
        q = q.where(Caller.active == 1)
    elif status == "expired":
        q = q.where(Caller.active == 0)
    elif status in ("pending", "rejected"):
        # 현 스키마에선 이 상태가 존재 불가능 — 빈 결과로 반환.
        return {"data": [], "meta": {"total": 0}}
    # "all" 또는 None 은 전체.

    callers = db.execute(q).scalars().all()
    usage = _daily_usage_map(db)
    rows = [_caller_to_dict(c, usage.get(c.number, 0)) for c in callers]
    return {"data": rows, "meta": {"total": len(rows)}}


@router.get("/numbers/{nid}", response_model=None)
def get_number(nid: str, db: Session = Depends(get_db)) -> dict | JSONResponse:
    """개별 발신번호 상세. nid 는 정수 문자열 (Caller.id)."""
    try:
        caller_id = int(nid)
    except (ValueError, TypeError):
        return JSONResponse(
            {"error": {"code": "not_found", "message": "발신번호를 찾을 수 없습니다"}},
            status_code=404,
        )
    caller = db.get(Caller, caller_id)
    if caller is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "발신번호를 찾을 수 없습니다"}},
            status_code=404,
        )
    usage = _daily_usage_map(db).get(caller.number, 0)
    return {"data": _caller_to_dict(caller, usage)}


# ── CRUD: POST/PATCH/DELETE — admin 전용, CSRF 필수 ─────────────────────────


class CallerCreateBody(BaseModel):
    """POST /numbers 요청 body.

    number 는 하이픈/공백 등을 허용하고 내부에서 숫자만 추출.
    label 은 UI 표시용 브랜드명 (필수).
    rcsEnabled 는 선택 — 기본 False.
    """

    number: str = Field(..., min_length=1, max_length=40)
    label: str = Field(..., min_length=1, max_length=80)
    rcsEnabled: bool = False

    @field_validator("number")
    @classmethod
    def _normalize(cls, v: str) -> str:
        digits = "".join(c for c in v if c.isdigit())
        if not digits:
            raise ValueError("유효한 번호 형식이 아닙니다")
        return digits

    @field_validator("label")
    @classmethod
    def _strip_label(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("브랜드/라벨은 비어 있을 수 없습니다")
        return stripped


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@router.post("/numbers", dependencies=[Depends(verify_csrf)], response_model=None)
def create_number(
    body: CallerCreateBody,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    """새 발신번호 등록. 중복 번호는 409."""
    existing = db.execute(
        select(Caller).where(Caller.number == body.number)
    ).scalar_one_or_none()
    if existing is not None:
        return JSONResponse(
            {"error": {
                "code": "duplicate_number",
                "message": "이미 등록된 번호입니다",
                "fields": {"number": "중복"},
            }},
            status_code=409,
        )

    caller = Caller(
        number=body.number,
        label=body.label,
        active=1,
        is_default=0,
        rcs_enabled=1 if body.rcsEnabled else 0,
        created_at=_now_iso(),
    )
    db.add(caller)
    try:
        db.flush()
    except IntegrityError:
        # TOCTOU: 두 admin 이 동시 POST 한 경우 앞 select 검사 통과 후에도
        # unique 제약 때문에 둘째가 여기서 실패한다. 409 envelope 로 정상화.
        db.rollback()
        return JSONResponse(
            {"error": {
                "code": "duplicate_number",
                "message": "이미 등록된 번호입니다",
                "fields": {"number": "중복"},
            }},
            status_code=409,
        )
    audit.log(
        db,
        actor_sub=user.sub,
        action=audit.CALLER_CREATE,
        target=f"caller:{caller.id}",
        detail={"number": body.number, "label": body.label},
    )
    db.commit()
    usage = _daily_usage_map(db).get(caller.number, 0)
    return {"data": _caller_to_dict(caller, usage)}


@router.post(
    "/numbers/{nid}/toggle",
    dependencies=[Depends(verify_csrf)],
    response_model=None,
)
def toggle_number(
    nid: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    """발신번호 활성/비활성 토글."""
    try:
        caller_id = int(nid)
    except (ValueError, TypeError):
        return JSONResponse(
            {"error": {"code": "not_found", "message": "발신번호를 찾을 수 없습니다"}},
            status_code=404,
        )
    caller = db.get(Caller, caller_id)
    if caller is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "발신번호를 찾을 수 없습니다"}},
            status_code=404,
        )

    was_default = bool(caller.is_default)
    caller.active = 0 if caller.active else 1
    # 비활성화 시 기본 플래그도 해제해야 "기본=비활성" 상태 회피.
    if not caller.active and was_default:
        caller.is_default = 0
        # 조직에 기본 번호 0 개가 되는 상태 방지 — 다른 활성 번호 중 id 최소를
        # 후임으로 승격. 후보 없으면 0 상태 수용 (주석: campaign compose 쪽이
        # default 부재를 graceful 하게 다뤄야 함).
        fallback = db.execute(
            select(Caller)
            .where(and_(Caller.active == 1, Caller.id != caller_id))
            .order_by(Caller.id.asc())
            .limit(1)
        ).scalar_one_or_none()
        if fallback is not None:
            fallback.is_default = 1
    audit.log(
        db,
        actor_sub=user.sub,
        action=audit.CALLER_UPDATE,
        target=f"caller:{caller_id}",
        detail={"active": caller.active},
    )
    db.commit()
    usage = _daily_usage_map(db).get(caller.number, 0)
    return {"data": _caller_to_dict(caller, usage)}


@router.post(
    "/numbers/{nid}/default",
    dependencies=[Depends(verify_csrf)],
    response_model=None,
)
def set_default_number(
    nid: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    """기본 발신번호 지정 — 다른 기본은 자동 해제. 비활성 번호는 거부."""
    try:
        caller_id = int(nid)
    except (ValueError, TypeError):
        return JSONResponse(
            {"error": {"code": "not_found", "message": "발신번호를 찾을 수 없습니다"}},
            status_code=404,
        )
    caller = db.get(Caller, caller_id)
    if caller is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "발신번호를 찾을 수 없습니다"}},
            status_code=404,
        )
    if not caller.active:
        return JSONResponse(
            {"error": {
                "code": "inactive_caller",
                "message": "비활성 번호는 기본으로 지정할 수 없습니다",
            }},
            status_code=422,
        )

    # O(1) 2 UPDATE: 기존 default 전부 해제 → 대상 하나만 default=1.
    # Python 루프로 모든 caller 를 로드해 dirty 플래그 찍는 건 테이블이 커질수록
    # commit 시 UPDATE 문이 N 개 발행되므로 배치 UPDATE 로 고정 비용화.
    db.execute(
        update(Caller)
        .where(Caller.is_default == 1)
        .values(is_default=0)
    )
    db.execute(
        update(Caller)
        .where(Caller.id == caller_id)
        .values(is_default=1)
    )
    # SQLAlchemy ORM session 이 caller 객체 캐시에 갖고 있는 is_default 는
    # UPDATE 이후 stale — refresh 로 동기화해 응답 dict 가 최신값을 반영하게.
    db.refresh(caller)

    audit.log(
        db,
        actor_sub=user.sub,
        action=audit.CALLER_DEFAULT,
        target=f"caller:{caller_id}",
    )
    db.commit()
    usage = _daily_usage_map(db).get(caller.number, 0)
    return {"data": _caller_to_dict(caller, usage)}


@router.delete(
    "/numbers/{nid}",
    dependencies=[Depends(verify_csrf)],
    response_model=None,
)
def delete_number(
    nid: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    """발신번호 삭제. 활성 상태면 422 (먼저 비활성화 후 삭제)."""
    try:
        caller_id = int(nid)
    except (ValueError, TypeError):
        return JSONResponse(
            {"error": {"code": "not_found", "message": "발신번호를 찾을 수 없습니다"}},
            status_code=404,
        )
    caller = db.get(Caller, caller_id)
    if caller is None:
        return JSONResponse(
            {"error": {"code": "not_found", "message": "발신번호를 찾을 수 없습니다"}},
            status_code=404,
        )
    if caller.active:
        return JSONResponse(
            {"error": {
                "code": "active_cannot_delete",
                "message": "활성 번호는 삭제할 수 없습니다. 먼저 비활성화하세요",
            }},
            status_code=422,
        )

    audit.log(
        db,
        actor_sub=user.sub,
        action=audit.CALLER_DELETE,
        target=f"caller:{caller_id}",
        detail={"number": caller.number, "label": caller.label},
    )
    db.delete(caller)
    db.commit()
    return {"data": {"id": nid, "deleted": True}}
