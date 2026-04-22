"""통합 검색 API — S17.

실 DB cross-cutting 검색. 4 섹션(contacts/threads/campaigns/auditLogs) 를
각 10건 상한으로 반환하고 total 카운트도 별도 제공.

api-contract.md §S17 — web/types/search.ts SearchResult shape.

⚠ 이전 구현은 제거된 mock 리스트(_MOCK_*)를 import 해서 import 단계에서
실패했다. 전면 재작성으로 실 DB 기반 전환.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_complete, require_user
from app.db import get_db
from app.models import AuditLog, Campaign, Contact, Message, MoMessage, User
from app.routes.audit_api import _escape_like
from app.routes.contacts import _contact_to_dict

router = APIRouter(
    dependencies=[Depends(require_user), Depends(require_setup_complete)],
)

KST = ZoneInfo("Asia/Seoul")

# 섹션당 반환 상한. total 은 별도로 계산해 배지에 표시.
_SECTION_LIMIT = 10
# 스캔 상한 — SELECT 결과 풀 사이즈. 너무 크면 메모리/레이턴시 악영향.
_SCAN_LIMIT = 500


# ── 포맷 헬퍼 ────────────────────────────────────────────────────────────────


def _fmt_kst_dt(iso_utc: str | None) -> str:
    if not iso_utc:
        return ""
    try:
        dt = datetime.fromisoformat(iso_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return ""


def _fmt_kst_full(iso_utc: str | None) -> str:
    if not iso_utc:
        return ""
    try:
        dt = datetime.fromisoformat(iso_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return ""


def _campaign_label(subject: str | None, content: str | None, cid: int) -> str:
    if subject:
        return subject
    if content:
        first = content.strip().split("\n", 1)[0]
        return first[:30] + ("…" if len(first) > 30 else "")
    return f"캠페인 #{cid}"


# ── 섹션별 검색 ──────────────────────────────────────────────────────────────


def _search_contacts(db: Session, pat_like: str) -> tuple[list[dict], int]:
    """이름/번호/이메일/부서 부분매치. total + 첫 N개 반환."""
    stmt = select(Contact).where(
        or_(
            Contact.name.ilike(pat_like, escape="\\"),
            Contact.phone.ilike(pat_like, escape="\\"),
            Contact.email.ilike(pat_like, escape="\\"),
            Contact.department.ilike(pat_like, escape="\\"),
        )
    )
    rows = db.execute(stmt.limit(_SCAN_LIMIT)).scalars().all()
    total = len(rows)
    rows = rows[:_SECTION_LIMIT]
    # 통합검색 결과엔 groupIds/lastCampaign 까진 불요 (섹션 라벨만 필요).
    out = [_contact_to_dict(c, group_ids=None, last_campaign=None) for c in rows]
    return out, total


def _search_campaigns(db: Session, pat_like: str) -> tuple[list[dict], int]:
    """Campaign.subject/content 부분매치. 최신순."""
    stmt = (
        select(Campaign)
        .where(
            or_(
                Campaign.subject.ilike(pat_like, escape="\\"),
                Campaign.content.ilike(pat_like, escape="\\"),
            )
        )
        .order_by(Campaign.id.desc())
    )
    rows = db.execute(stmt.limit(_SCAN_LIMIT)).scalars().all()
    total = len(rows)
    rows = rows[:_SECTION_LIMIT]
    out = [
        {
            "id": str(c.id),
            "name": _campaign_label(c.subject, c.content, c.id),
            "status": (c.state or "").lower(),
            "createdAt": _fmt_kst_dt(c.created_at),
        }
        for c in rows
    ]
    return out, total


def _search_audit(db: Session, pat_like: str) -> tuple[list[dict], int]:
    """actor name/email + action + target 부분매치. 최신순."""
    stmt = (
        select(AuditLog, User.name, User.email)
        .select_from(AuditLog)
        .outerjoin(User, User.sub == AuditLog.actor_sub)
        .where(
            or_(
                User.name.ilike(pat_like, escape="\\"),
                User.email.ilike(pat_like, escape="\\"),
                AuditLog.action.ilike(pat_like, escape="\\"),
                AuditLog.target.ilike(pat_like, escape="\\"),
            )
        )
        .order_by(AuditLog.id.desc())
    )
    rows = db.execute(stmt.limit(_SCAN_LIMIT)).all()
    total = len(rows)
    rows = rows[:_SECTION_LIMIT]
    out = [
        {
            "id": f"a-{log.id}",
            "time": _fmt_kst_full(log.created_at),
            "actor": name or ("시스템" if log.actor_sub is None else "(탈퇴)"),
            "action": log.action,
            "target": log.target or "-",
        }
        for log, name, _email in rows
    ]
    return out, total


def _search_threads(db: Session, pat_like: str) -> tuple[list[dict], int]:
    """스레드(대화방) 검색 — MT(Campaign.subject/content 매치) 또는
    MO(mo_msg 매치). (caller, phone) 단위로 dedup, 최신 ts_iso 기록 유지.

    NOTE: 실제 스레드 id 규약은 threads.py 의 '{caller}:{phone}'. 여기서는
    매치된 메시지가 속한 (caller, phone) 을 뽑아 최신순 정렬.
    """
    # 1) MT 매치: subject 또는 content 둘 다 확인 (campaigns 섹션과 동일 기준).
    mt_rows = db.execute(
        select(
            Campaign.caller_number,
            Message.to_number,
            Message.id,
            Campaign.subject,
            Campaign.content,
            Message.complete_time,
        )
        .join(Message, Message.campaign_id == Campaign.id)
        .where(
            or_(
                Campaign.content.ilike(pat_like, escape="\\"),
                Campaign.subject.ilike(pat_like, escape="\\"),
            )
        )
        .order_by(Message.id.desc())
        .limit(_SCAN_LIMIT)
    ).all()

    # 2) MO 매치: mo_messages.mo_msg 매치. mo_callback=caller, mo_number=phone.
    mo_rows = db.execute(
        select(
            MoMessage.mo_callback,
            MoMessage.mo_number,
            MoMessage.id,
            MoMessage.mo_msg,
            MoMessage.received_at,
        )
        .where(MoMessage.mo_msg.ilike(pat_like, escape="\\"))
        .order_by(MoMessage.id.desc())
        .limit(_SCAN_LIMIT)
    ).all()

    # MT 와 MO 양쪽을 (caller, phone) 로 dedup. ts_iso 비교해 **더 최신만** 보관.
    # (이전 구현은 MT 먼저 삽입 후 MO 덮어쓰기를 거부 — MO 가 최신이면 snippet 이
    # 구 MT 로 고정되는 버그.)
    combined: dict[tuple[str, str], dict] = {}

    def _upsert(key, entry):
        existing = combined.get(key)
        if existing is None or (entry["ts_iso"] or "") > (existing["ts_iso"] or ""):
            combined[key] = entry

    for caller, phone, _mid, subj, content, ts in mt_rows:
        if not caller or not phone:
            continue
        # MT snippet 우선순위: content 가 매치 원천일 가능성 높음. subject 만 있으면 subject.
        snippet_src = content or subj or ""
        _upsert((caller, phone), {
            "caller": caller,
            "phone": phone,
            "snippet": snippet_src[:120],
            "ts_iso": ts or "",
            "campaign_name": _campaign_label(subj, content, 0) if (subj or content) else None,
        })
    for caller, phone, _mid, body, recv in mo_rows:
        if not caller or not phone:
            continue
        _upsert((caller, phone), {
            "caller": caller,
            "phone": phone,
            "snippet": (body or "")[:120],
            "ts_iso": recv or "",
            "campaign_name": None,
        })

    # 최근 ts 기준 정렬. ts_iso 는 MT 의 complete_time (UTC ISO) 또는 MO 의
    # received_at (UTC ISO) — 둘 다 '+00:00' 접미 이라 lexicographic OK.
    ordered = sorted(
        combined.values(),
        key=lambda r: r.get("ts_iso", ""),
        reverse=True,
    )
    total = len(ordered)
    ordered = ordered[:_SECTION_LIMIT]
    out = [
        {
            "id": f"{r['caller']}:{r['phone']}",
            "name": r["phone"],  # 연락처 이름 미연결 — 번호로 표시
            "phone": r["phone"],
            "snippet": r["snippet"],
            "time": _fmt_kst_dt(r.get("ts_iso") or None),
            **({"campaignName": r["campaign_name"]} if r.get("campaign_name") else {}),
        }
        for r in ordered
    ]
    return out, total


# ── 라우트 ───────────────────────────────────────────────────────────────────


def _empty_result() -> dict:
    return {
        "data": {
            "contacts": [],
            "threads": [],
            "campaigns": [],
            "auditLogs": [],
            "counts": {
                "total": 0,
                "contacts": 0,
                "threads": 0,
                "campaigns": 0,
                "auditLogs": 0,
            },
        }
    }


@router.get("/search")
def search(
    q: str = Query(default="", description="검색어"),
    db: Session = Depends(get_db),
) -> dict:
    """통합 검색 — 4 섹션 병렬. 빈 쿼리는 즉시 빈 결과."""
    query = q.strip()
    if not query:
        return _empty_result()

    pat = f"%{_escape_like(query)}%"

    contacts, c_total = _search_contacts(db, pat)
    threads, t_total = _search_threads(db, pat)
    campaigns, cam_total = _search_campaigns(db, pat)
    audit, a_total = _search_audit(db, pat)

    # total 이 SCAN 상한에 도달하면 "이상일 수 있음" 시그널 — 프론트가
    # "500+" 같은 표기를 선택할 수 있게 한다.
    capped = any(t == _SCAN_LIMIT for t in (c_total, t_total, cam_total, a_total))

    counts: dict = {
        "total": c_total + t_total + cam_total + a_total,
        "contacts": c_total,
        "threads": t_total,
        "campaigns": cam_total,
        "auditLogs": a_total,
    }
    if capped:
        counts["capped"] = True

    return {
        "data": {
            "contacts": contacts,
            "threads": threads,
            "campaigns": campaigns,
            "auditLogs": audit,
            "counts": counts,
        }
    }
