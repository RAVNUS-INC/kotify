"""FastAPI 애플리케이션 엔트리포인트."""
from __future__ import annotations

import json as _json
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select as _sa_select
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.db import SessionLocal, engine
from app.models import Base, User
from app.msghub.schemas import MsghubAuthError
from app.security.crypto import load_or_create_master_key
from app.web import templates

logger = logging.getLogger(__name__)

# ── msghub 클라이언트 싱글턴 ────────────────────────────────────────────────
_msghub_client = None

# ── setup_gate 부트스트랩 캐시 (매 요청 DB hit 방지) ──────────────────────────
_bootstrap_cached: bool = False


def _make_msghub_client():
    """현재 DB settings에서 msghub 클라이언트를 생성한다."""
    from app.msghub.client import MsghubClient
    from app.security.settings_store import SettingsStore

    db = SessionLocal()
    try:
        store = SettingsStore(db)
        api_key = store.get("msghub.api_key")
        api_pwd = store.get("msghub.api_pwd")
        env = store.get("msghub.env") or "production"
        if not (api_key and api_pwd):
            return None
        brand_id = store.get("msghub.brand_id") or ""
        chatbot_id = store.get("msghub.chatbot_id") or ""
        return MsghubClient(
            env=env,
            api_key=api_key,
            api_pwd=api_pwd,
            brand_id=brand_id,
            chatbot_id=chatbot_id,
        )
    finally:
        db.close()


def get_msghub_client():
    """싱글턴 msghub 클라이언트를 반환한다. 없으면 생성한다."""
    global _msghub_client
    if _msghub_client is None:
        _msghub_client = _make_msghub_client()
    return _msghub_client


def reset_msghub_client():
    """msghub 설정 변경 시 클라이언트를 재생성한다."""
    global _msghub_client
    _msghub_client = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """앱 생명주기 — 시작/종료 처리."""
    global _msghub_client

    # DB 테이블 생성 — dev_mode에서만 create_all 사용
    # 운영 환경: systemd ExecStartPre=/opt/sms/.venv/bin/alembic upgrade head
    if settings.dev_mode:
        Base.metadata.create_all(bind=engine)

    # 마스터 키 로드 (없으면 자동 생성)
    load_or_create_master_key(settings.master_key_path)

    # 세션 시크릿 적용
    db = SessionLocal()
    try:
        from app.auth.session import get_session_secret
        get_session_secret(db)
    finally:
        db.close()

    # msghub 클라이언트 초기화
    _msghub_client = _make_msghub_client()

    logger.info("메시징 시스템 시작 (dev_mode=%s)", settings.dev_mode)

    yield

    # 종료
    if _msghub_client is not None:
        try:
            await _msghub_client.aclose()
        except Exception:
            pass
        _msghub_client = None
    logger.info("메시징 시스템 종료")


# ── 앱 생성 ──────────────────────────────────────────────────────────────────
app = FastAPI(
    title="사내 메시징 시스템",
    version="0.2.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

# ── 세션 시크릿 로드 ──────────────────────────────────────────────────────────
from sqlalchemy.exc import OperationalError as _OperationalError

from app.auth.session import add_session_middleware, get_session_secret
from app.auth.session import get_fallback_secret as _get_fallback_secret

try:
    if settings.dev_mode:
        Base.metadata.create_all(bind=engine)
    _db_init = SessionLocal()
    try:
        _session_secret = get_session_secret(_db_init)
    finally:
        _db_init.close()
except _OperationalError:
    _session_secret = _get_fallback_secret()
except Exception:  # noqa: BLE001
    _session_secret = _get_fallback_secret()

# ── 라우터 등록 ───────────────────────────────────────────────────────────────
from app.routes.admin import router as admin_router
from app.routes.auth import router as auth_router
from app.routes.campaigns import router as campaigns_router
from app.routes.chat import router as chat_router
from app.routes.compose import router as compose_router
from app.routes.contacts import router as contacts_router
from app.routes.dashboard import router as dashboard_router
from app.routes.groups import router as groups_router
from app.routes.health import router as health_router
from app.routes.pages import router as pages_router
from app.routes.setup import router as setup_router
from app.routes.webhook import router as webhook_router

app.include_router(health_router)
app.include_router(webhook_router)
app.include_router(setup_router)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(compose_router)
app.include_router(campaigns_router)
app.include_router(chat_router)
app.include_router(admin_router)
app.include_router(contacts_router)
app.include_router(groups_router)
app.include_router(pages_router)

# ── 정적 파일 마운트 (DashForge 자산) ─────────────────────────────────────────
from pathlib import Path as _Path
_static_dir = _Path(__file__).resolve().parent / "static"
if _static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# ── 미들웨어: setup gate — 부트스트랩 미완료 시 /setup 으로 ──────────────────
_ALLOWED_DURING_SETUP = (
    "/setup",
    "/healthz",
    "/static",
    "/auth/login",
    "/auth/callback",
    "/auth/logout",
    "/webhook",
)


@app.middleware("http")
async def setup_gate(request: Request, call_next):
    """부트스트랩이 완료되지 않으면 /setup 으로 리다이렉트한다."""
    global _bootstrap_cached

    path = request.url.path
    if any(path.startswith(p) for p in _ALLOWED_DURING_SETUP):
        return await call_next(request)

    if _bootstrap_cached:
        return await call_next(request)

    try:
        with SessionLocal() as db:
            from app.security.settings_store import SettingsStore
            store = SettingsStore(db)
            if store.is_bootstrap_completed():
                _bootstrap_cached = True
            else:
                return RedirectResponse("/setup", status_code=303)
    except Exception:
        pass

    return await call_next(request)


# ── 미들웨어: 사용자 컨텍스트 주입 ───────────────────────────────────────────
@app.middleware("http")
async def inject_user_context(request: Request, call_next):
    """모든 응답에 현재 사용자 정보를 request.state에 주입한다."""
    if "session" in request.scope:
        sub = request.session.get("user_sub")
    else:
        sub = None
    request.state.user_sub = sub
    response = await call_next(request)
    return response


# ── 세션 미들웨어 등록 (반드시 마지막 — outermost 보장) ───────────────────────
add_session_middleware(app, _session_secret)


# ── 전역 예외 핸들러 ─────────────────────────────────────────────────────────
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """HTTP 예외 처리 — 303 리다이렉트는 그대로 전달."""
    if exc.status_code == 303:
        location = exc.headers.get("Location", "/") if exc.headers else "/"
        return RedirectResponse(url=location, status_code=303)

    try:
        sub = request.session.get("user_sub") if hasattr(request, "session") else None
        user_name = request.session.get("user_name", "") if hasattr(request, "session") else ""
        raw = request.session.get("user_roles", []) if hasattr(request, "session") else []
        if isinstance(raw, list):
            user_roles = raw
        else:
            import json
            try:
                user_roles = json.loads(raw)
            except Exception:
                user_roles = []

        first_admin_email = None
        if exc.status_code == 403:
            try:
                with SessionLocal() as _db:
                    all_users = list(_db.execute(_sa_select(User)).scalars().all())
                    for _u in all_users:
                        try:
                            _roles = _json.loads(_u.roles)
                        except Exception:
                            _roles = []
                        if "admin" in _roles:
                            first_admin_email = _u.email
                            break
            except Exception:
                pass

        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "status_code": exc.status_code,
                "detail": exc.detail,
                "user_sub": sub,
                "user_name": user_name,
                "user_roles": user_roles,
                "first_admin_email": first_admin_email,
            },
            status_code=exc.status_code,
        )
    except Exception:
        return JSONResponse(
            {"error": exc.detail},
            status_code=exc.status_code,
        )


@app.exception_handler(MsghubAuthError)
async def msghub_auth_error_handler(request: Request, exc: MsghubAuthError):
    """MsghubAuthError — 503 + 관리자 설정 점검 요청."""
    try:
        user_name = request.session.get("user_name", "") if hasattr(request, "session") else ""
        raw = request.session.get("user_roles", []) if hasattr(request, "session") else []
        if isinstance(raw, list):
            user_roles = raw
        else:
            import json
            try:
                user_roles = json.loads(raw)
            except Exception:
                user_roles = []

        return templates.TemplateResponse(
            request,
            "error.html",
            {
                "status_code": 503,
                "detail": "msghub 인증 오류가 발생했습니다. 관리자에게 설정 점검을 요청하세요.",
                "is_auth_error": True,
                "user_name": user_name,
                "user_roles": user_roles,
            },
            status_code=503,
        )
    except Exception:
        return JSONResponse(
            {"error": "msghub_auth_error", "detail": str(exc)},
            status_code=503,
        )
