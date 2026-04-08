"""FastAPI 애플리케이션 엔트리포인트."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.db import SessionLocal, engine
from app.models import Base
from app.ncp.client import NCPAuthError
from app.security.csrf import get_csrf_token
from app.security.crypto import load_or_create_master_key
from app.services.poller import Poller

logger = logging.getLogger(__name__)

# ── 폴러 싱글턴 (campaigns.py에서 import) ────────────────────────────────────
poller: Poller

# ── NCP 클라이언트 싱글턴 (#27/#28) ──────────────────────────────────────────
_ncp_client = None


def _make_ncp_client():
    """현재 DB settings에서 NCP 클라이언트를 생성한다."""
    from app.ncp.client import NCPClient
    from app.security.settings_store import SettingsStore

    db = SessionLocal()
    try:
        store = SettingsStore(db)
        access_key = store.get("ncp.access_key")
        secret_key = store.get("ncp.secret_key")
        service_id = store.get("ncp.service_id")
        if not (access_key and secret_key and service_id):
            return None
        return NCPClient(access_key=access_key, secret_key=secret_key, service_id=service_id)
    finally:
        db.close()


def get_ncp_client():
    """싱글턴 NCP 클라이언트를 반환한다. 없으면 생성한다 (#27/#28)."""
    global _ncp_client
    if _ncp_client is None:
        _ncp_client = _make_ncp_client()
    return _ncp_client


def reset_ncp_client():
    """NCP 설정 변경 시 클라이언트를 재생성한다 (#28)."""
    global _ncp_client
    _ncp_client = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """앱 생명주기 — 시작/종료 처리."""
    global poller, _ncp_client

    # DB 테이블 생성 — dev_mode에서만 create_all 사용 (#16/#17)
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

    # NCP 클라이언트 초기화 (#27)
    _ncp_client = _make_ncp_client()

    # 폴러 생성 + 시작
    poller = Poller(
        db_factory=SessionLocal,
        ncp_client_factory=get_ncp_client,
    )
    await poller.start()

    logger.info("SMS 발송 시스템 시작 (dev_mode=%s)", settings.dev_mode)

    yield

    # 종료
    await poller.stop()
    # NCP 클라이언트 연결 닫기 (#27)
    if _ncp_client is not None:
        try:
            await _ncp_client.aclose()
        except Exception:
            pass
        _ncp_client = None
    logger.info("SMS 발송 시스템 종료")


# ── 앱 생성 ──────────────────────────────────────────────────────────────────
app = FastAPI(
    title="사내 SMS 발송 시스템",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,  # 운영에서는 API 문서 비활성
    redoc_url=None,
)

# ── 세션 미들웨어 ─────────────────────────────────────────────────────────────
# DB 테이블이 아직 없을 수 있으므로 try/except로 보호.
# 설정이 없으면 임시 키(fallback) 사용.
from app.auth.session import get_session_secret, add_session_middleware, _FALLBACK_SECRET

try:
    # 테이블이 이미 존재하면 DB에서 읽음
    Base.metadata.create_all(bind=engine)
    _db_init = SessionLocal()
    try:
        _session_secret = get_session_secret(_db_init)
    finally:
        _db_init.close()
except Exception:  # noqa: BLE001 — OperationalError or similar on first boot
    from sqlalchemy.exc import OperationalError as _OE  # noqa: F401
    _session_secret = _FALLBACK_SECRET

add_session_middleware(app, _session_secret)

# ── 라우터 등록 ───────────────────────────────────────────────────────────────
from app.routes.health import router as health_router
from app.routes.setup import router as setup_router
from app.routes.auth import router as auth_router
from app.routes.dashboard import router as dashboard_router
from app.routes.compose import router as compose_router
from app.routes.campaigns import router as campaigns_router
from app.routes.admin import router as admin_router

app.include_router(health_router)
app.include_router(setup_router)
app.include_router(auth_router)
app.include_router(dashboard_router)
app.include_router(compose_router)
app.include_router(campaigns_router)
app.include_router(admin_router)

# ── Jinja2 Templates (전역) ───────────────────────────────────────────────────
templates = Jinja2Templates(directory="app/templates")

# csrf_token을 모든 템플릿에서 {{ csrf_token(request) }} 로 사용 가능하게 등록
templates.env.globals["csrf_token"] = get_csrf_token


# ── 미들웨어: setup gate — 부트스트랩 미완료 시 /setup 으로 (#5) ──────────────
@app.middleware("http")
async def setup_gate(request: Request, call_next):
    """부트스트랩이 완료되지 않으면 /setup 으로 리다이렉트한다.

    통과 허용 경로:
    - /setup* — setup wizard 자체
    - /auth/* — OIDC 콜백 포함
    - /healthz — 헬스체크
    - /static/* — 정적 파일
    """
    path = request.url.path
    if (
        path.startswith("/setup")
        or path.startswith("/auth")
        or path.startswith("/healthz")
        or path.startswith("/static")
    ):
        return await call_next(request)

    try:
        with SessionLocal() as db:
            from app.security.settings_store import SettingsStore
            store = SettingsStore(db)
            if not store.is_bootstrap_completed():
                return RedirectResponse("/setup", status_code=303)
    except Exception:
        pass  # DB 없으면 통과 (첫 기동)

    return await call_next(request)


# ── 미들웨어: 사용자 컨텍스트 주입 ───────────────────────────────────────────
@app.middleware("http")
async def inject_user_context(request: Request, call_next):
    """모든 응답에 현재 사용자 정보를 request.state에 주입한다."""
    sub = request.session.get("user_sub") if hasattr(request, "session") else None
    request.state.user_sub = sub
    response = await call_next(request)
    return response


# ── 전역 예외 핸들러 ─────────────────────────────────────────────────────────
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """HTTP 예외 처리 — 303 리다이렉트는 그대로 전달."""
    if exc.status_code == 303:
        location = exc.headers.get("Location", "/") if exc.headers else "/"
        return RedirectResponse(url=location, status_code=303)

    # 그 외 에러는 에러 페이지 렌더링
    try:
        sub = request.session.get("user_sub") if hasattr(request, "session") else None
        user_name = request.session.get("user_name", "") if hasattr(request, "session") else ""
        # #29: user_roles를 list로 직접 저장 — isinstance로 타입 안전 처리
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
            "error.html",
            {
                "request": request,
                "status_code": exc.status_code,
                "detail": exc.detail,
                "user_sub": sub,
                "user_name": user_name,
                "user_roles": user_roles,
            },
            status_code=exc.status_code,
        )
    except Exception:
        return JSONResponse(
            {"error": exc.detail},
            status_code=exc.status_code,
        )


@app.exception_handler(NotImplementedError)
async def not_implemented_handler(request: Request, exc: NotImplementedError):
    """NotImplementedError — stub 미구현 안내 페이지."""
    import inspect
    try:
        frame = inspect.trace()[-1]
        location = f"{frame[1]}:{frame[2]}"
    except Exception:
        location = "알 수 없는 위치"

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
            "error.html",
            {
                "request": request,
                "status_code": 501,
                "detail": f"아직 구현되지 않은 기능입니다: {exc}\n위치: {location}",
                "is_stub_error": True,
                "stub_message": str(exc),
                "stub_location": location,
                "user_name": user_name,
                "user_roles": user_roles,
            },
            status_code=501,
        )
    except Exception:
        return JSONResponse(
            {"error": "stub_not_implemented", "detail": str(exc)},
            status_code=501,
        )


@app.exception_handler(NCPAuthError)
async def ncp_auth_error_handler(request: Request, exc: NCPAuthError):
    """NCPAuthError — 503 + 관리자 설정 점검 요청."""
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
            "error.html",
            {
                "request": request,
                "status_code": 503,
                "detail": "NCP 인증 오류가 발생했습니다. 관리자에게 설정 점검을 요청하세요.",
                "is_ncp_auth_error": True,
                "user_name": user_name,
                "user_roles": user_roles,
            },
            status_code=503,
        )
    except Exception:
        return JSONResponse(
            {"error": "ncp_auth_error", "detail": str(exc)},
            status_code=503,
        )
