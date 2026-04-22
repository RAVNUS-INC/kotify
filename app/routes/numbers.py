"""발신번호 API — S11 & S2 (발신번호 드롭다운).

api-contract.md §S11 계약:
    GET /api/numbers?status=approved|pending|rejected|expired|all
    GET /api/numbers/{id}

실 DB 소스: callers 테이블 (msghub Phase 에서 관리되는 발신번호).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_role, require_setup_complete
from app.db import get_db
from app.models import Caller, Campaign

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


@router.get("/numbers/{nid}")
def get_number(nid: str, db: Session = Depends(get_db)):
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
