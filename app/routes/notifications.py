"""알림센터 API — S15.

실 DB 기반 *파생 뷰*:
    - send_result 계열: campaigns 테이블의 최근 20건을 state → level/title 매핑.
    - security/system 계열: audit_logs 의 최근 20건을 action → kind/level 매핑.

별도 notifications 테이블을 두지 않는 이유: 알림은 도메인 이벤트의 *뷰* 일
뿐이고 중복 저장은 incident 동기화 비용을 유발. 스키마가 없으므로 사용자별
읽음 상태는 Setting 테이블의 두 키로 관리:

    notif.last_read_at.{sub}  — mark-all-read 시점 (ISO8601)
    notif.read_ids.{sub}      — 개별 dismiss 된 알림 id JSON 리스트 (최대 200)

unread 판정: `createdAt > last_read_at` AND `id NOT IN read_ids`.

api-contract.md §S15 — web/types/notification.ts Notification shape.
"""
from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import require_setup_complete, require_user
from app.db import get_db
from app.models import AuditLog, Campaign, Setting, User
from app.security.csrf import verify_csrf

router = APIRouter(
    dependencies=[Depends(require_user), Depends(require_setup_complete)],
)

KST = ZoneInfo("Asia/Seoul")

# 크로스-스레드 직렬화 — settings 업데이트 race 방지.
_notif_lock = threading.Lock()

# 각 소스 상한. 총 최대 건수 = _CAMPAIGN_LIMIT + _AUDIT_LIMIT.
_CAMPAIGN_LIMIT = 20
_AUDIT_LIMIT = 20
# per-user read_ids 저장 상한 — 과도한 DB row 팽창 방지.
_MAX_READ_IDS = 200


# ── 시간 포맷 ────────────────────────────────────────────────────────────────


def _fmt_kst_min(iso_utc: str | None) -> str:
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


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


# ── Campaign → Notification 매핑 ─────────────────────────────────────────────


def _campaign_title(c: Campaign) -> str:
    if c.subject:
        return c.subject
    if c.content:
        first = c.content.strip().split("\n", 1)[0]
        return first[:30] + ("…" if len(first) > 30 else "")
    return f"캠페인 #{c.id}"


def _campaign_notif(c: Campaign) -> dict | None:
    """Campaign 한 건 → Notification dict. 파생 불가한 상태면 None."""
    name = _campaign_title(c)
    total = c.total_count or 0
    ok = c.ok_count or 0
    fail = c.fail_count or 0
    state = c.state or ""

    mapping = {
        "COMPLETED": ("success", f"{name} 발송 완료", f"{ok}/{total} 도달"),
        "DISPATCHED": ("success", f"{name} 발송 완료", f"{ok}/{total} 도달"),
        "PARTIAL_FAILED": ("warning", f"{name} 일부 실패", f"{ok}/{total} 성공 · {fail}건 실패"),
        "FAILED": ("error", f"{name} 발송 실패", f"{total}건 미발송"),
        "DISPATCHING": ("info", f"{name} 발송 중", f"{ok}/{total} 진행"),
        "RESERVED": ("info", f"{name} 예약됨", c.reserve_time or "—"),
        "RESERVE_FAILED": ("error", f"{name} 예약 실패", "재시도 필요"),
        "RESERVE_CANCELED": ("warning", f"{name} 예약 취소", "사용자 취소"),
        "DRAFT": ("info", f"{name} 초안 저장", ""),
    }
    entry = mapping.get(state)
    if entry is None:
        return None
    level, title, subtitle = entry

    # created_at 기준 — UTC ISO. completed 이면 completed_at 우선 (UX 기준 시각).
    ts = c.completed_at or c.created_at or ""
    return {
        "id": f"campaign-{c.id}",
        "kind": "send_result",
        "level": level,
        "title": title,
        "subtitle": subtitle,
        "_ts_iso": ts,
        "createdAt": _fmt_kst_min(ts),
        "href": f"/campaigns/{c.id}",
    }


# ── AuditLog → Notification 매핑 ────────────────────────────────────────────

# action → (kind, level, title prefix). 누락된 action 은 필터아웃.
_AUDIT_ACTION_MAP: dict[str, tuple[str, str, str]] = {
    "LOGIN": ("security", "info", "로그인"),
    "LOGOUT": ("security", "info", "로그아웃"),
    "SEND": ("send_result", "info", "발송 트리거"),
    "CANCEL_RESERVE": ("send_result", "warning", "예약 취소"),
    "CALLER_CREATE": ("system", "info", "발신번호 등록"),
    "CALLER_UPDATE": ("system", "info", "발신번호 수정"),
    "CALLER_DELETE": ("security", "warning", "발신번호 삭제"),
    "CALLER_DEFAULT": ("system", "info", "기본 발신번호 변경"),
    "SETTINGS_UPDATE": ("system", "info", "설정 변경"),
    "SETUP_COMPLETED": ("system", "info", "초기 설정 완료"),
    "BOOTSTRAP_INIT": ("system", "info", "시스템 초기화"),
}


def _audit_notif(log: AuditLog, actor_name: str | None) -> dict | None:
    meta = _AUDIT_ACTION_MAP.get(log.action)
    if meta is None:
        return None
    kind, level, label = meta
    who = actor_name or ("시스템" if log.actor_sub is None else "알 수 없음")
    subtitle_parts = [who]
    if log.target:
        subtitle_parts.append(log.target)
    href = None
    if log.action.startswith("CALLER_"):
        href = "/numbers"
    elif log.action == "SETTINGS_UPDATE":
        href = "/settings"
    # LOGIN/LOGOUT 은 admin 전용 /audit 로 보내면 operator/viewer 가 403.
    # 알림 자체가 정보성이므로 href 를 생략 (클릭 불가 상태로 표시).
    return {
        "id": f"audit-{log.id}",
        "kind": kind,
        "level": level,
        "title": label,
        "subtitle": " · ".join(subtitle_parts),
        "_ts_iso": log.created_at or "",
        "createdAt": _fmt_kst_min(log.created_at),
        **({"href": href} if href else {}),
    }


# ── 사용자별 읽음 상태 ───────────────────────────────────────────────────────


def _setting_get(db: Session, key: str) -> str | None:
    s = db.get(Setting, key)
    return s.value if s else None


def _setting_upsert(
    db: Session, key: str, value: str, updated_by: str | None
) -> None:
    now = _now_iso()
    existing = db.get(Setting, key)
    if existing is None:
        db.add(Setting(
            key=key, value=value, is_secret=0,
            updated_by=updated_by, updated_at=now,
        ))
    else:
        existing.value = value
        existing.updated_by = updated_by
        existing.updated_at = now


def _last_read_key(sub: str) -> str:
    return f"notif.last_read_at.{sub}"


def _read_ids_key(sub: str) -> str:
    return f"notif.read_ids.{sub}"


def _nid_sort_key(nid: str) -> tuple[str, int]:
    """파생 id 를 (prefix, numeric_suffix) 로 파싱해 정렬 가능하게.

    "campaign-42" → ("campaign", 42). 잘못된 포맷은 ("", 0) 로 가장 앞.
    prune 시 최신 id 를 보존하기 위해 이 키로 정렬 후 tail 유지.
    """
    prefix, _, raw = nid.partition("-")
    try:
        return (prefix, int(raw))
    except (ValueError, TypeError):
        return ("", 0)


def _load_read_state(db: Session, sub: str) -> tuple[str, set[str]]:
    """per-user last_read_at(ISO) + read_ids set. 없으면 epoch / 빈 set."""
    last = _setting_get(db, _last_read_key(sub)) or "1970-01-01T00:00:00+00:00"
    raw_ids = _setting_get(db, _read_ids_key(sub)) or "[]"
    try:
        ids = set(json.loads(raw_ids))
        if not all(isinstance(x, str) for x in ids):
            ids = set()
    except (json.JSONDecodeError, TypeError):
        ids = set()
    return last, ids


# ── 빌드 ────────────────────────────────────────────────────────────────────


def _build_notifications(db: Session) -> list[dict]:
    """DB 상태로부터 알림 목록 파생. 정렬 없이 raw list 반환."""
    # 최근 campaigns — created_at DESC, 상한.
    camps = db.execute(
        select(Campaign).order_by(Campaign.id.desc()).limit(_CAMPAIGN_LIMIT)
    ).scalars().all()
    notifs = [n for n in (_campaign_notif(c) for c in camps) if n is not None]

    # 최근 audit_logs — User JOIN 으로 actor 표시명 동시 수집.
    # display_name 우선, 없으면 name (레거시/백필 row) 사용.
    rows = db.execute(
        select(AuditLog, func.coalesce(User.display_name, User.name))
        .select_from(AuditLog)
        .outerjoin(User, User.sub == AuditLog.actor_sub)
        .order_by(AuditLog.id.desc())
        .limit(_AUDIT_LIMIT)
    ).all()
    for log, actor_name in rows:
        n = _audit_notif(log, actor_name)
        if n is not None:
            notifs.append(n)
    return notifs


def _apply_read_state(
    notifs: list[dict], last_read_at: str, read_ids: set[str]
) -> list[dict]:
    """각 알림에 unread 플래그 부착. _ts_iso 내부 필드는 제거.

    ⚠ ts / last_read_at 모두 `datetime.now(UTC).isoformat()` 결과 (항상
    "+00:00" 접미사) 라는 전제로 문자열 lexicographic 비교. 'Z' 접미사나
    naive timestamp 가 섞이면 잘못된 순서가 나오니 write 경로에서 isoformat
    규약을 유지해야 한다.
    """
    out: list[dict] = []
    for n in notifs:
        ts = n.get("_ts_iso", "")
        unread = bool(ts) and ts > last_read_at and n["id"] not in read_ids
        row = {k: v for k, v in n.items() if k != "_ts_iso"}
        # TS 계약: unread 가 true 일 때만 포함 (optional boolean).
        if unread:
            row["unread"] = True
        out.append(row)
    return out


# ── S15: GET /notifications ─────────────────────────────────────────────────


@router.get("/notifications")
def list_notifications(
    kind: Optional[str] = None,
    unread: Optional[bool] = None,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    """알림 목록 — 최근 campaigns + audit_logs 파생. 최신순.

    unreadTotal 은 kind/unread 필터와 무관하게 전체(스코프 전) 미읽음 수를
    반환한다 — 프론트에서 tab 배지/상단 badge 를 일관된 값으로 쓴다.
    """
    all_notifs = _build_notifications(db)
    last_read_at, read_ids = _load_read_state(db, user.sub)
    stated = _apply_read_state(all_notifs, last_read_at, read_ids)

    # ★ 필터와 독립적으로 글로벌 unread 집계 (배지 일관성).
    unread_total = sum(1 for n in stated if n.get("unread"))

    if kind and kind != "all":
        filtered = [n for n in stated if n.get("kind") == kind]
    else:
        filtered = list(stated)
    if unread:
        filtered = [n for n in filtered if n.get("unread")]

    # 최신순 — createdAt 포맷 "YYYY-MM-DD HH:MM" 은 문자열 정렬 가능.
    filtered.sort(key=lambda r: r.get("createdAt", ""), reverse=True)
    return {
        "data": filtered,
        "meta": {"total": len(filtered), "unreadTotal": unread_total},
    }


# ── POST /notifications/{id}/read ───────────────────────────────────────────


@router.post(
    "/notifications/{nid}/read",
    dependencies=[Depends(verify_csrf)],
    response_model=None,
)
def mark_read(
    nid: str,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    """개별 알림을 읽음 처리 — read_ids JSON 리스트에 추가 (최대 200개).

    검증: "campaign-{digits}" 또는 "audit-{digits}" 만 허용. 그 외 포맷은 404.
    """
    prefix, _, raw = nid.partition("-")
    if prefix not in ("campaign", "audit") or not raw.isdigit():
        return JSONResponse(
            {"error": {"code": "not_found", "message": "알림을 찾을 수 없습니다"}},
            status_code=404,
        )

    with _notif_lock:
        _, read_ids = _load_read_state(db, user.sub)
        if nid in read_ids:
            return {"data": {"id": nid, "unread": False}}
        read_ids.add(nid)
        # 상한 초과 시 (prefix, int(suffix)) 로 정렬해 "가장 오래된" 을 제거.
        # 문자열 정렬은 'audit-9' > 'audit-137' 등 오류 발생 → _nid_sort_key 사용.
        if len(read_ids) > _MAX_READ_IDS:
            read_ids = set(
                sorted(read_ids, key=_nid_sort_key)[-_MAX_READ_IDS:]
            )
        _setting_upsert(
            db, _read_ids_key(user.sub),
            json.dumps(sorted(read_ids, key=_nid_sort_key)),
            user.sub,
        )
        db.commit()
    return {"data": {"id": nid, "unread": False}}


# ── POST /notifications/read-all ────────────────────────────────────────────


@router.post(
    "/notifications/read-all",
    dependencies=[Depends(verify_csrf)],
)
def mark_all_read(
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    """전체 읽음 — last_read_at 을 now 로 갱신하고 read_ids 초기화."""
    with _notif_lock:
        # 현재 미읽음 개수를 계산해서 응답 (UX 용).
        notifs = _build_notifications(db)
        last_read_at, read_ids = _load_read_state(db, user.sub)
        current_unread = sum(
            1 for n in _apply_read_state(notifs, last_read_at, read_ids)
            if n.get("unread")
        )

        _setting_upsert(db, _last_read_key(user.sub), _now_iso(), user.sub)
        _setting_upsert(db, _read_ids_key(user.sub), "[]", user.sub)
        db.commit()
    return {"data": {"readCount": current_unread}}
