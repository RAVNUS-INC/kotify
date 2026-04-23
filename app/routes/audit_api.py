"""감사 로그 API — S13.

실 DB (audit_logs LEFT JOIN users) 기반. services.audit.log() 로 기록된
모든 액션을 최신순으로 조회. CSV export 는 CSV injection 방어.

api-contract.md §S13 — web/types/audit.ts AuditEntry shape.
"""
from __future__ import annotations

import csv
import io
from datetime import UTC, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.auth.deps import require_role, require_setup_complete
from app.db import get_db
from app.models import AuditLog, User
from app.util.csv_safe import safe_csv_cell as _safe_csv_cell

# 감사 로그는 admin 전용
router = APIRouter(
    dependencies=[Depends(require_role("admin")), Depends(require_setup_complete)],
)

KST = ZoneInfo("Asia/Seoul")

# 상한 — ORDER BY id DESC 는 PK 인덱스 사용, LIMIT 1000 은 MVP 규모에서 충분.
# action/q 필터는 현재 전체 스캔(audit_logs 에 별도 인덱스 없음). 규모가 커지면
# action + created_at 복합 인덱스를 추가 마이그레이션으로 도입.
_AUDIT_PAGE_SIZE = 1000


def _escape_like(s: str) -> str:
    """LIKE 와일드카드(%, _, \\) 이스케이프. 리터럴 검색 보장.

    사용자가 '100%' 로 검색하면 '%' 를 와일드카드가 아닌 리터럴로 취급해야
    '1000'/'10000' 같은 오매칭을 막는다. 백슬래시는 반드시 먼저 치환
    (그래야 뒤이어 추가되는 \\% / \\_ 이 두 번 이스케이프되지 않음).
    """
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _fmt_kst_full(iso_utc: str | None) -> str:
    """UTC ISO → 'YYYY-MM-DD HH:MM:SS' KST. 실패 시 빈 문자열."""
    if not iso_utc:
        return ""
    try:
        dt = datetime.fromisoformat(iso_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return ""


def _actor_fallback(actor_sub: str | None) -> str:
    """User JOIN 실패 시 대체 표시.

    - actor_sub NULL (시스템 액션) → "시스템"
    - actor_sub 는 있는데 users row 없음(탈퇴한 사용자) → "(탈퇴:xxxxxxxx)"
      로 앞 8자 노출해 감사 추적 가능하게.
    """
    if actor_sub is None:
        return "시스템"
    return f"(탈퇴:{actor_sub[:8]})"


def _entry_to_dict(
    log: AuditLog, actor_name: str | None, actor_email: str | None
) -> dict:
    """AuditLog + joined User → web/types/audit.ts AuditEntry shape."""
    return {
        "id": f"a-{log.id}",
        "time": _fmt_kst_full(log.created_at),
        "actor": actor_name or _actor_fallback(log.actor_sub),
        "actorEmail": actor_email or "",
        "action": log.action,
        "target": log.target or "-",
        "ip": log.ip or "-",
    }


def _query_audit(
    db: Session, q: Optional[str], action: Optional[str]
) -> list[tuple[AuditLog, str | None, str | None]]:
    """SELECT audit_logs LEFT JOIN users ORDER BY id DESC.

    id 는 autoincrement PK 라 insert 순 == 조회 역순. services.audit.log 가
    항상 now() 로 created_at 을 채우므로 id DESC 와 created_at DESC 가 일치,
    그리고 id DESC 는 PK 인덱스 활용이라 정렬 비용이 없다.

    q 는 actor name/email/target 에 부분매치(LIKE wildcard 이스케이프).
    action 은 정확일치.
    """
    # 표시는 display_name 우선 (fallback name). 검색 LIKE 는 display_name/name
    # 둘 다 매칭 — 백필 전 레거시 row 에서 name 만 있어도 필터링 가능.
    actor_display = func.coalesce(User.display_name, User.name)
    stmt = (
        select(AuditLog, actor_display, User.email)
        .select_from(AuditLog)
        .outerjoin(User, User.sub == AuditLog.actor_sub)
    )
    if action and action != "all":
        stmt = stmt.where(AuditLog.action == action)
    if q:
        pat = f"%{_escape_like(q)}%"
        stmt = stmt.where(
            or_(
                User.display_name.ilike(pat, escape="\\"),
                User.name.ilike(pat, escape="\\"),
                User.email.ilike(pat, escape="\\"),
                AuditLog.target.ilike(pat, escape="\\"),
            )
        )
    stmt = stmt.order_by(AuditLog.id.desc()).limit(_AUDIT_PAGE_SIZE)
    rows = db.execute(stmt).all()
    return [(r[0], r[1], r[2]) for r in rows]


# ── S13: GET /audit ──────────────────────────────────────────────────────────


@router.get("/audit")
def list_audit(
    q: Optional[str] = None,
    action: Optional[str] = None,
    db: Session = Depends(get_db),
) -> dict:
    """감사 로그 목록 — created_at DESC, 최대 1000건."""
    rows = _query_audit(db, q, action)
    return {
        "data": [_entry_to_dict(log, name, email) for log, name, email in rows],
        "meta": {
            "total": len(rows),
            "hasMore": len(rows) >= _AUDIT_PAGE_SIZE,
        },
    }


@router.get("/audit/export.csv")
def export_audit_csv(
    q: Optional[str] = None,
    action: Optional[str] = None,
    db: Session = Depends(get_db),
) -> Response:
    """CSV 다운로드 — UTF-8 BOM + CSV injection 방어 (util.csv_safe)."""
    rows = _query_audit(db, q, action)

    buf = io.StringIO()
    # UTF-8 BOM 으로 Excel 한글 호환
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(["시간", "주체", "이메일", "액션", "대상", "IP"])
    for log, name, email in rows:
        entry = _entry_to_dict(log, name, email)
        writer.writerow([
            _safe_csv_cell(entry["time"]),
            _safe_csv_cell(entry["actor"]),
            _safe_csv_cell(entry["actorEmail"]),
            _safe_csv_cell(entry["action"]),
            _safe_csv_cell(entry["target"]),
            _safe_csv_cell(entry["ip"]),
        ])

    return Response(
        content=buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="kotify-audit.csv"'},
    )
