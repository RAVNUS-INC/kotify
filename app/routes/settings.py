"""설정 API — S12 /org /members /api-keys /webhooks.

실 DB 기반:
    - /org   (GET/PATCH): Setting 테이블의 `org.*` 키 4개 (name/service/contact/
      timezone) 를 upsert. limits 는 현재 스키마에 rate-limit 컬럼이 없어
      고정값 (recipientsPerCampaign=1000, campaignsPerMinute=10).
    - /members (GET): users 테이블. User.roles(JSON) 의 첫 엔트리를 role 로,
      created_at 을 invitedAt 으로 alias.

스키마 미지원 (현재는 빈 리스트 반환):
    - /api-keys: api_keys 테이블 없음. Phase 후속.
    - /webhooks: webhook_subscriptions 테이블 없음. 현 webhook.py 는 msghub
      수신용이라 별개. Phase 후속.
"""
from __future__ import annotations

import threading
from datetime import UTC, datetime
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import (
    primary_role,
    require_role,
    require_setup_complete,
    require_user,
)
from app.db import get_db
from app.models import Setting, User
from app.security.csrf import verify_csrf

# 조직 설정은 admin 전용
router = APIRouter(
    dependencies=[Depends(require_role("admin")), Depends(require_setup_complete)],
)

KST = ZoneInfo("Asia/Seoul")

# 동시성 보호 — PATCH 중 다른 요청이 같은 키를 갈아치우면 race 발생 가능.
# 동기 handler + threading.Lock 조합: FastAPI 가 sync def 를 threadpool 에서
# 실행하므로 asyncio.Lock 은 부적절(동일 이벤트루프 내 coroutine 만 직렬화).
# 크로스-스레드 뮤텍스가 필요.
_settings_lock = threading.Lock()

# ── Org 기본값 및 Setting 키 매핑 ─────────────────────────────────────────────

_ORG_KEYS = {
    "name": "org.name",
    "service": "org.service",
    "contact": "org.contact",
    "timezone": "org.timezone",
}
_ORG_DEFAULTS = {
    "name": "",
    "service": "",
    "contact": "",
    "timezone": "Asia/Seoul",
}

# 현 스키마엔 rate-limit 저장소가 없어 고정값. 나중에 org_limits 테이블 또는
# Setting 에 `org.limits.*` 키를 도입해 치환한다.
_ORG_LIMITS = {
    "recipientsPerCampaign": 1000,
    "campaignsPerMinute": 10,
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _fmt_kst_date(iso_utc: str | None) -> str:
    """UTC ISO → 'YYYY-MM-DD' KST. 실패 시 빈 문자열."""
    if not iso_utc:
        return ""
    try:
        dt = datetime.fromisoformat(iso_utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(KST).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return ""


def _get_org_dict(db: Session) -> dict:
    """Setting 테이블에서 org.* 키 읽어 web/types/settings.ts Org 조립."""
    keys = list(_ORG_KEYS.values())
    rows = db.execute(select(Setting).where(Setting.key.in_(keys))).scalars().all()
    kv = {s.key: s.value for s in rows}
    return {
        "name": kv.get(_ORG_KEYS["name"], _ORG_DEFAULTS["name"]),
        "service": kv.get(_ORG_KEYS["service"], _ORG_DEFAULTS["service"]),
        "contact": kv.get(_ORG_KEYS["contact"], _ORG_DEFAULTS["contact"]),
        "timezone": kv.get(_ORG_KEYS["timezone"], _ORG_DEFAULTS["timezone"]),
        "limits": dict(_ORG_LIMITS),
    }


def _upsert_setting(
    db: Session, key: str, value: str, updated_by: str | None
) -> None:
    """Setting 단건 upsert. is_secret=0 (org 필드는 비밀 아님)."""
    existing = db.get(Setting, key)
    now = _now_iso()
    if existing is None:
        db.add(Setting(
            key=key, value=value, is_secret=0,
            updated_by=updated_by, updated_at=now,
        ))
    else:
        existing.value = value
        existing.updated_by = updated_by
        existing.updated_at = now


def _user_to_member(u: User) -> dict:
    """User ORM → web/types/settings.ts Member shape.

    대표 role 은 app.auth.deps.primary_role 을 재사용해 ROLE_PRIORITY 단일
    기준 유지.
    """
    return {
        "id": u.sub,
        "email": u.email,
        "name": u.name or u.email,
        "role": primary_role(u.roles),
        # TODO(soft-delete): User 모델에 active/deleted_at 컬럼 추가 시 교체.
        "active": True,
        "invitedAt": _fmt_kst_date(u.created_at),
    }


# ── Pydantic 요청 body ───────────────────────────────────────────────────────


class OrgPatchBody(BaseModel):
    """PATCH /org 요청 body — 모두 optional."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    service: Optional[str] = Field(default=None, max_length=120)
    contact: Optional[str] = Field(default=None, max_length=120)
    timezone: Optional[str] = None

    @field_validator("timezone")
    @classmethod
    def _valid_tz(cls, v: str | None) -> str | None:
        """알 수 없는 TZ 문자열은 422. 빈 문자열은 None 으로 정규화."""
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        try:
            ZoneInfo(v)
        except ZoneInfoNotFoundError:
            raise ValueError("알 수 없는 timezone 입니다")
        return v


# ── Routes ───────────────────────────────────────────────────────────────────


@router.get("/org")
def get_org(db: Session = Depends(get_db)) -> dict:
    return {"data": _get_org_dict(db)}


@router.patch(
    "/org",
    dependencies=[Depends(verify_csrf)],
    response_model=None,
)
def patch_org(
    body: OrgPatchBody,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    """org 설정 일부 업데이트. 공란 strip 후 name 은 빈 값 금지.

    sync def — FastAPI 가 threadpool 에서 실행. 크로스-스레드 직렬화는
    `_settings_lock` (threading.Lock) 으로 보장.
    """
    with _settings_lock:
        updates = body.model_dump(exclude_none=True)
        normalized: dict[str, str] = {}
        for k, v in updates.items():
            if isinstance(v, str):
                v = v.strip()
            if k == "name" and not v:
                return JSONResponse(
                    {"error": {
                        "code": "validation_failed",
                        "message": "조직명은 비어 있을 수 없습니다",
                        "fields": {"name": "필수"},
                    }},
                    status_code=422,
                )
            normalized[k] = v

        for field, val in normalized.items():
            _upsert_setting(db, _ORG_KEYS[field], val, user.sub)
        db.commit()

    return {"data": _get_org_dict(db)}


@router.get("/members")
def list_members(db: Session = Depends(get_db)) -> dict:
    users = db.execute(select(User).order_by(User.created_at.asc())).scalars().all()
    rows = [_user_to_member(u) for u in users]
    return {"data": rows, "meta": {"total": len(rows)}}


# ── API Keys / Webhooks: 현재 스키마 부재 → 빈 목록 ─────────────────────────
# 백엔드가 기능을 아직 구현하지 않았음을 명확히. 프론트는 meta.featurePending
# 플래그로 "Coming soon" 상태를 표시할 수 있다.


@router.get("/api-keys")
def list_api_keys() -> dict:
    """API 키 관리 — 스키마 미구현. 빈 목록과 featurePending 시그널만 반환."""
    return {
        "data": [],
        "meta": {"total": 0, "featurePending": True},
    }


@router.get("/webhooks")
def list_webhooks() -> dict:
    """아웃바운드 웹훅 구독 — 스키마 미구현. 빈 목록과 featurePending 시그널."""
    return {
        "data": [],
        "meta": {"total": 0, "featurePending": True},
    }
