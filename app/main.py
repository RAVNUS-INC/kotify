"""FastAPI 애플리케이션 엔트리포인트 — 순수 JSON API."""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.db import SessionLocal, engine
from app.models import Base
from app.msghub.schemas import MsghubAuthError
from app.security.crypto import load_or_create_master_key

logger = logging.getLogger(__name__)

# ── msghub 클라이언트 싱글턴 ────────────────────────────────────────────────
_msghub_client = None


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
        except Exception:  # noqa: BLE001
            logger.debug("msghub client close error", exc_info=True)
        _msghub_client = None
    logger.info("메시징 시스템 종료")


# ── 앱 생성 ──────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Kotify API",
    version="0.3.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
)

# ── 세션 시크릿 로드 ──────────────────────────────────────────────────────────
from sqlalchemy.exc import OperationalError as _OperationalError

from app.auth.session import add_session_middleware, get_session_secret
from app.auth.session import get_fallback_secret as _get_fallback_secret

try:
    _db_init = SessionLocal()
    try:
        _session_secret = get_session_secret(_db_init)
    finally:
        _db_init.close()
except _OperationalError:
    _session_secret = _get_fallback_secret()
except Exception:  # noqa: BLE001
    _session_secret = _get_fallback_secret()

# ── 라우터 등록 (JSON API 전용) ─────────────────────────────────────────────
from app.routes.auth import router as auth_router
from app.routes.campaigns import router as campaigns_router
from app.routes.dashboard import router as dashboard_router
from app.routes.health import router as health_router
from app.routes.threads import router as threads_router
from app.routes.webhook import router as webhook_router

app.include_router(health_router)
app.include_router(webhook_router)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(campaigns_router)
app.include_router(threads_router)


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


# ── 전역 예외 핸들러 (JSON 반환) ─────────────────────────────────────────────
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """HTTP 예외 — envelope 형식 JSON 반환."""
    return JSONResponse(
        {"error": {"code": f"http_{exc.status_code}", "message": exc.detail}},
        status_code=exc.status_code,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """Pydantic 검증 실패 → envelope 형식 422."""
    fields: dict[str, str] = {}
    for err in exc.errors():
        loc = err.get("loc", ())
        path = ".".join(str(s) for s in loc if s != "body")
        if path:
            fields[path] = err.get("msg", "")
    return JSONResponse(
        {
            "error": {
                "code": "validation_failed",
                "message": "입력값이 올바르지 않습니다",
                "fields": fields,
            }
        },
        status_code=422,
    )


@app.exception_handler(MsghubAuthError)
async def msghub_auth_error_handler(request: Request, exc: MsghubAuthError):
    """msghub 인증 오류 — 503 + 관리자 점검 안내."""
    return JSONResponse(
        {
            "error": {
                "code": "msghub_auth_error",
                "message": "msghub 인증 오류가 발생했습니다. 관리자에게 설정 점검을 요청하세요.",
                "detail": str(exc),
            }
        },
        status_code=503,
    )
