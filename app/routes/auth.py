"""인증 라우트 — Keycloak OIDC Authorization Code Flow."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.oidc import get_oauth_client, parse_user_from_claims
from app.db import get_db
from app.models import User
from app.security.csrf import verify_csrf
from app.services import audit

router = APIRouter(prefix="/auth")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/login")
async def login(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    """Keycloak 인증 페이지로 리다이렉트."""
    oauth = get_oauth_client(db)
    if oauth is None:
        # 설정 미완료 → setup으로
        return RedirectResponse("/setup", status_code=303)

    keycloak = oauth.create_client("keycloak")
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

    # 첫 admin 승격 — setup.first_admin_email과 일치할 때만 (#9)
    from app.security.settings_store import SettingsStore
    store = SettingsStore(db)
    pending_first_admin = store.get("setup.pending_first_admin", "false") == "true"

    roles = user_info["roles"]
    if pending_first_admin:
        first_admin_email = store.get("setup.first_admin_email", "")
        if first_admin_email and user_info["email"] == first_admin_email:
            # 이메일 일치 → admin 승격
            if "admin" not in roles:
                roles = ["admin"] + roles
            store.set("setup.pending_first_admin", "false", is_secret=False, updated_by=sub)
            db.flush()
        elif first_admin_email:
            # 이메일 불일치 → 기본 역할(viewer)로 로그인 + 감사 로그 경고
            audit.log(
                db,
                actor_sub=sub,
                action=audit.LOGIN,
                detail={
                    "email": user_info["email"],
                    "warning": "first_admin_email 불일치 — admin 승격 거부",
                },
            )
        else:
            # first_admin_email 미설정 → 하위 호환: 첫 로그인 사용자 admin 승격
            if "admin" not in roles:
                roles = ["admin"] + roles
            store.set("setup.pending_first_admin", "false", is_secret=False, updated_by=sub)
            db.flush()

    now = _now_iso()
    # #21: 매 로그인마다 Keycloak 역할로 덮어쓰기 (역할 회수 가능)
    roles_json = json.dumps(sorted(set(roles)), ensure_ascii=False)

    # users 테이블 upsert
    user = db.get(User, sub)
    if user is None:
        user = User(
            sub=sub,
            email=user_info["email"],
            name=user_info["name"],
            roles=roles_json,
            created_at=now,
            last_login_at=now,
        )
        db.add(user)
    else:
        user.email = user_info["email"]
        user.name = user_info["name"]
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

    # 세션 저장 — #29: user_roles를 list로 직접 저장
    request.session["user_sub"] = sub
    request.session["user_email"] = user_info["email"]
    request.session["user_name"] = user_info["name"]
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
