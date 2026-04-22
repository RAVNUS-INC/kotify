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
from app.security.settings_store import SettingsStore
from app.services import audit

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


# ── Provider 설정 (msghub / Keycloak / app) ─────────────────────────────────
# 기존 HTMX /admin/settings 에서 처리하던 민감 설정을 JSON API 로 재구성.
# 시크릿(비밀번호/클라이언트시크릿/세션키)은 쓰기 전용 — GET 에서 "설정됨/비어
# 있음" 만 반환하고 평문은 절대 응답에 포함하지 않는다. 빈 값 PATCH 는 기존
# 값을 보존(삭제 아님).

_PROVIDER_PUBLIC_KEYS: dict[str, str] = {
    # TS 필드 → Setting key 매핑
    "keycloakIssuer": "keycloak.issuer",
    "keycloakClientId": "keycloak.client_id",
    "appPublicUrl": "app.public_url",
    "msghubEnv": "msghub.env",
    "msghubBrandId": "msghub.brand_id",
    "msghubChatbotId": "msghub.chatbot_id",
}
_PROVIDER_SECRET_KEYS: dict[str, str] = {
    "keycloakClientSecret": "keycloak.client_secret",
    "msghubApiKey": "msghub.api_key",
    "msghubApiPwd": "msghub.api_pwd",
    "sessionSecret": "session.secret",
}


class ProviderPatchBody(BaseModel):
    """PATCH /settings/provider — 모두 optional. 빈 문자열은 None 과 동일하게 취급."""

    # 공개 (평문 저장)
    keycloakIssuer: Optional[str] = None
    keycloakClientId: Optional[str] = None
    appPublicUrl: Optional[str] = None
    msghubEnv: Optional[str] = None  # production | staging | sandbox 등
    msghubBrandId: Optional[str] = None
    msghubChatbotId: Optional[str] = None
    # 시크릿 (Fernet 암호화 저장) — 빈 값/미제공 시 기존 값 보존
    keycloakClientSecret: Optional[str] = None
    msghubApiKey: Optional[str] = None
    msghubApiPwd: Optional[str] = None
    sessionSecret: Optional[str] = None


@router.get("/settings/provider")
def get_provider_settings(db: Session = Depends(get_db)) -> dict:
    """Provider 설정 현재값 — 시크릿은 마스킹 또는 '설정됨/비어있음' 플래그만."""
    store = SettingsStore(db)
    public: dict[str, str] = {}
    for ts_key, skey in _PROVIDER_PUBLIC_KEYS.items():
        public[ts_key] = store.get(skey, "") or ""
    secrets_info: dict[str, dict] = {}
    for ts_key, skey in _PROVIDER_SECRET_KEYS.items():
        value = store.get(skey, "") or ""
        secrets_info[ts_key] = {
            "configured": bool(value),
            # UI 표시용 마스킹 — 값 자체는 절대 내려주지 않음.
            "masked": SettingsStore.mask(value) if value else "",
        }
    return {"data": {"public": public, "secrets": secrets_info}}


@router.patch(
    "/settings/provider",
    dependencies=[Depends(verify_csrf)],
    response_model=None,
)
async def patch_provider_settings(
    body: ProviderPatchBody,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> dict:
    """Provider 설정 일부 업데이트.

    - 공개 필드는 비어있어도 저장하지 않음(= 삭제 방지). 값이 있을 때만 upsert.
    - 시크릿은 값이 있을 때만 재암호화/재저장. 비어있으면 기존 값 유지.
    - msghub.* 가 바뀌면 in-memory msghub 클라이언트 리셋 → 다음 요청부터
      새 자격증명으로 재인증.

    async def 로 둔 이유: reset_msghub_client 가 coroutine 이라 await 필요.
    threading.Lock 은 여전히 cross-thread 직렬화를 보장하며 async 핸들러
    내부에서도 안전하게 쓰인다 (짧게 잡히는 lock 이라 event loop 영향 미미).
    """
    with _settings_lock:
        store = SettingsStore(db)
        updates = body.model_dump(exclude_none=True)

        # 공개 필드 저장 — 빈 문자열은 skip.
        for ts_key, skey in _PROVIDER_PUBLIC_KEYS.items():
            val = updates.get(ts_key)
            if isinstance(val, str):
                val = val.strip()
                if val:
                    store.set(skey, val, is_secret=False, updated_by=user.sub)

        # 시크릿 저장 — 빈 문자열도 skip (기존 값 보존).
        msghub_creds_changed = False
        for ts_key, skey in _PROVIDER_SECRET_KEYS.items():
            val = updates.get(ts_key)
            if isinstance(val, str) and val.strip():
                store.set(skey, val.strip(), is_secret=True, updated_by=user.sub)
                if skey.startswith("msghub."):
                    msghub_creds_changed = True

        # msghub.env 같은 공개 필드도 클라이언트 재초기화 필요.
        if any(
            isinstance(updates.get(k), str) and updates[k].strip()
            for k in ("msghubEnv", "msghubBrandId", "msghubChatbotId")
        ):
            msghub_creds_changed = True

        audit.log(db, actor_sub=user.sub, action=audit.SETTINGS_UPDATE)
        db.commit()

    # msghub 재초기화는 락 밖에서 — 다른 요청의 settings GET 을 블록하지 않도록.
    if msghub_creds_changed:
        try:
            from app.main import reset_msghub_client
            await reset_msghub_client()
        except ImportError:
            # dev/test 환경에서 app.main 미로드 — 무시.
            pass

    return get_provider_settings(db=db)


@router.post(
    "/settings/test-msghub",
    dependencies=[Depends(verify_csrf)],
    response_model=None,
)
async def test_msghub_auth(
    db: Session = Depends(get_db),
) -> dict | JSONResponse:
    """현재 저장된 msghub 자격증명으로 인증 테스트.

    성공 시 `{data: {ok: true, message: ...}}`, 실패 시 422 envelope.
    네트워크 오류와 인증 오류를 구분해 프론트에 표시할 수 있게.
    """
    store = SettingsStore(db)
    api_key = store.get("msghub.api_key")
    api_pwd = store.get("msghub.api_pwd")
    env = store.get("msghub.env") or "production"

    if not (api_key and api_pwd):
        return JSONResponse(
            {"error": {
                "code": "not_configured",
                "message": "msghub API key/password 가 설정되지 않았습니다",
            }},
            status_code=422,
        )

    try:
        from app.msghub.auth import AuthError
        from app.msghub.client import MsghubClient
    except ImportError:
        return JSONResponse(
            {"error": {
                "code": "msghub_unavailable",
                "message": "msghub 모듈을 로드할 수 없습니다",
            }},
            status_code=503,
        )

    client = MsghubClient(env=env, api_key=api_key, api_pwd=api_pwd)
    try:
        await client.test_auth()
        return {"data": {"ok": True, "message": "msghub 인증 성공", "env": env}}
    except AuthError as exc:
        return JSONResponse(
            {"error": {"code": "auth_failed", "message": f"인증 실패: {exc}"}},
            status_code=422,
        )
    except Exception as exc:  # 네트워크/타임아웃 등
        return JSONResponse(
            {"error": {"code": "connect_failed", "message": f"연결 실패: {exc}"}},
            status_code=502,
        )
    finally:
        try:
            await client.aclose()
        except Exception:
            pass
