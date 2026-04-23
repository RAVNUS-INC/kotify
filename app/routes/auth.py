"""인증 라우트 — Keycloak OIDC Authorization Code Flow."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth.oidc import get_oauth_client, parse_user_from_claims
from app.db import get_db
from app.models import User
from app.security.csrf import get_csrf_token, verify_csrf
from app.services import audit

router = APIRouter(prefix="/auth")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@router.get("/me")
async def me(request: Request) -> JSONResponse:
    """현재 로그인한 사용자 정보 + CSRF 토큰을 envelope 형식으로 반환한다.

    Next.js 클라이언트가 POST/PATCH 시 이 토큰을 X-CSRF-Token 헤더로 돌려보내
    verify_csrf 를 통과한다. 세션에 csrf_token 이 없으면 여기서 새로 생성해
    저장한다 (double-submit 패턴).
    """
    sub = request.session.get("user_sub") if "session" in request.scope else None
    if not sub:
        return JSONResponse(
            {
                "error": {
                    "code": "unauthenticated",
                    "message": "로그인이 필요합니다.",
                }
            },
            status_code=401,
        )

    roles_raw = request.session.get("user_roles", [])
    if isinstance(roles_raw, list):
        roles = [str(r) for r in roles_raw]
    else:
        try:
            parsed = json.loads(roles_raw)
            roles = [str(r) for r in parsed] if isinstance(parsed, list) else []
        except (TypeError, ValueError, json.JSONDecodeError):
            roles = []

    # CSRF 토큰: 로그인 후 첫 /me 호출에서 발급되어 세션에 저장된다.
    csrf_token = get_csrf_token(request)

    return JSONResponse(
        {
            "data": {
                "user": {
                    "sub": sub,
                    "email": request.session.get("user_email", ""),
                    "name": request.session.get("user_name", ""),
                    "display": request.session.get("user_display", "")
                    or request.session.get("user_name", ""),
                    "roles": roles,
                },
                "csrfToken": csrf_token,
            }
        }
    )


@router.get("/login")
async def login(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    """Keycloak 인증 페이지로 리다이렉트.

    Next.js 가 앞단에 있는 구조에서는 FastAPI 가 보는 `request.url` 이 내부
    주소(127.0.0.1:8080)라 `request.url_for` 로 redirect_uri 를 만들면 Keycloak
    의 Valid Redirect URIs 와 불일치. `app.public_url` 설정값 + 고정 경로
    `/api/auth/callback` (Next.js rewrites 가 FastAPI `/auth/callback` 으로 프록시)
    로 퍼블릭 URL 을 만든다.
    """
    oauth = get_oauth_client(db)
    if oauth is None:
        # 설정 미완료 → setup으로
        return RedirectResponse("/setup", status_code=303)

    keycloak = oauth.create_client("keycloak")

    from app.security.settings_store import SettingsStore
    store = SettingsStore(db)
    public_url = store.get("app.public_url", "").rstrip("/")
    if public_url:
        # /api 접두는 Next.js rewrites 를 통과시키기 위함. FastAPI 실제 경로는 /auth/callback.
        redirect_uri = f"{public_url}/api/auth/callback"
    else:
        # 설정 누락 시 fallback — dev 환경에서 FastAPI 가 직접 외부 대면하는 케이스.
        redirect_uri = str(request.url_for("auth_callback"))

    return await keycloak.authorize_redirect(request, redirect_uri)


@router.get("/callback", name="auth_callback")
async def callback(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    """OIDC 콜백 — code 교환, ID 토큰 검증, 세션 저장."""
    oauth = get_oauth_client(db)
    if oauth is None:
        return RedirectResponse("/setup", status_code=303)

    keycloak = oauth.create_client("keycloak")
    try:
        token = await keycloak.authorize_access_token(request)
    except Exception:
        return RedirectResponse("/auth/login?error=callback_failed", status_code=303)

    # ID 토큰에서 사용자 정보 추출
    claims = token.get("userinfo") or token.get("id_token") or {}
    if not claims:
        try:
            claims = await keycloak.userinfo(token=token)
        except Exception:
            claims = {}

    user_info = parse_user_from_claims(claims)
    sub = user_info["sub"]

    if not sub:
        return RedirectResponse("/auth/login?error=no_sub", status_code=303)

    # admin 부여 정책 (#9 + bugfix):
    # 1) setup.first_admin_email과 일치하면 영구 admin anchor (매 로그인마다 자동 부여)
    #    - 이전 버그: pending_first_admin=false 후 두 번째 로그인 시 viewer로 강등됨
    #    - 수정: first_admin_email은 일회성이 아닌 영구 anchor
    # 2) first_admin_email 미설정 + pending_first_admin=true → 첫 로그인 사용자 admin
    #    - 하위 호환 (wizard에서 이메일 안 입력한 케이스)
    from app.security.settings_store import SettingsStore
    store = SettingsStore(db)
    first_admin_email = store.get("setup.first_admin_email", "")
    pending_first_admin = store.get("setup.pending_first_admin", "false") == "true"

    roles = list(user_info["roles"])
    if first_admin_email and user_info["email"] == first_admin_email:
        # 영구 admin anchor — 매 로그인마다 admin 보장
        if "admin" not in roles:
            roles = ["admin"] + roles
        if pending_first_admin:
            store.set("setup.pending_first_admin", "false", is_secret=False, updated_by=sub)
            db.flush()
    elif first_admin_email:
        # 이메일 불일치 — admin 부여 거부 + 경고 로그
        if pending_first_admin:
            audit.log(
                db,
                actor_sub=sub,
                action=audit.LOGIN,
                detail={
                    "email": user_info["email"],
                    "warning": "first_admin_email 불일치 — admin 승격 거부",
                },
            )
    elif pending_first_admin:
        # first_admin_email 미설정 + 첫 로그인 → 하위 호환 admin 승격
        if "admin" not in roles:
            roles = ["admin"] + roles
        store.set("setup.pending_first_admin", "false", is_secret=False, updated_by=sub)
        db.flush()

    now = _now_iso()
    # #21: 매 로그인마다 Keycloak 역할로 덮어쓰기 (역할 회수 가능)
    roles_json = json.dumps(sorted(set(roles)), ensure_ascii=False)

    # users 테이블 upsert.
    # display_name 은 format_display_name() 결과 (성+이름/CN/email 우선순위).
    # 매 로그인마다 갱신 — 사용자가 Keycloak 프로필 이름 바꾸면 다음 로그인에
    # 즉시 반영. fallback: name 또는 email.
    display_name = (
        user_info.get("display_name") or user_info.get("name") or user_info.get("email") or sub
    )
    user = db.get(User, sub)
    if user is None:
        user = User(
            sub=sub,
            email=user_info["email"],
            name=user_info["name"],
            display_name=display_name,
            roles=roles_json,
            created_at=now,
            last_login_at=now,
        )
        db.add(user)
    else:
        user.email = user_info["email"]
        user.name = user_info["name"]
        user.display_name = display_name
        # #21: 역할을 Keycloak에서 받은 것으로 덮어쓰기 (병합 아님)
        user.roles = roles_json
        user.last_login_at = now

    db.flush()

    # 감사 로그
    ip = request.client.host if request.client else None
    audit.log(
        db,
        actor_sub=sub,
        action=audit.LOGIN,
        detail={"email": user_info["email"]},
        ip=ip,
    )
    db.commit()

    # 세션 고정 공격 방어: 로그인 전 세션 id 를 무효화하고 새로 발급.
    # Starlette SessionMiddleware 는 서명된 쿠키 기반이라 서버 측 세션 id 교체는
    # 없지만, 로그인 이전에 주입된 임의 값(csrf_token 포함)을 전부 폐기한다.
    request.session.clear()

    # 세션 저장 — #29: user_roles를 list로 직접 저장
    request.session["user_sub"] = sub
    request.session["user_email"] = user_info["email"]
    request.session["user_name"] = user_info["name"]
    request.session["user_display"] = user_info.get("display_name") or user_info["name"]
    request.session["user_roles"] = sorted(set(roles))  # list 직접 저장
    # I8: id_token 저장 — logout 시 end_session id_token_hint로 사용
    id_token = token.get("id_token")
    if id_token:
        request.session["id_token"] = id_token

    return RedirectResponse("/", status_code=303)


@router.post("/logout")
async def logout(
    request: Request,
    db: Session = Depends(get_db),
    _csrf: None = Depends(verify_csrf),
) -> RedirectResponse:
    """세션 클리어 + Keycloak end_session으로 리다이렉트."""
    sub = request.session.get("user_sub")
    # I8: id_token 읽기 (session.clear() 전에)
    id_token = request.session.get("id_token")

    if sub:
        ip = request.client.host if request.client else None
        audit.log(db, actor_sub=sub, action=audit.LOGOUT, ip=ip)
        db.commit()

    request.session.clear()

    # Keycloak end_session (I8: id_token_hint + client_id 포함)

    oauth = get_oauth_client(db)
    if oauth:
        try:
            keycloak = oauth.create_client("keycloak")
            meta = await keycloak.load_server_metadata()
            end_session_url = meta.get("end_session_endpoint", "")
            if end_session_url:
                from app.security.settings_store import SettingsStore
                store = SettingsStore(db)
                public_url = store.get("app.public_url", "")
                post_logout_uri = f"{public_url}/" if public_url else "/"
                client_id = store.get("keycloak.client_id", "sms-sys")
                params: dict = {
                    "post_logout_redirect_uri": post_logout_uri,
                    "client_id": client_id,
                }
                if id_token:
                    params["id_token_hint"] = id_token
                return RedirectResponse(
                    f"{end_session_url}?{urlencode(params)}",
                    status_code=303,
                )
        except Exception:
            pass

    return RedirectResponse("/auth/login", status_code=303)
