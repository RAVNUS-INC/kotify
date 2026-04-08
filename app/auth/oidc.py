"""OIDC 클라이언트 — Authlib 기반 Keycloak 연동.

lazy 초기화: setup wizard 완료 전엔 DB에 설정이 없을 수 있음.
get_oauth_client()가 매번 DB에서 읽어 동적 구성한다.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from authlib.integrations.starlette_client import OAuth

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def get_oauth_client(db: Session) -> OAuth | None:
    """DB settings에서 Keycloak 설정을 읽어 OAuth 클라이언트를 반환한다.

    설정이 아직 없으면 None 반환 (setup wizard 완료 전).

    Args:
        db: SQLAlchemy 세션.

    Returns:
        초기화된 OAuth 인스턴스, 또는 None.
    """
    from app.security.settings_store import SettingsStore

    store = SettingsStore(db)
    issuer = store.get("keycloak.issuer")
    client_id = store.get("keycloak.client_id")
    client_secret = store.get("keycloak.client_secret")

    if not (issuer and client_id and client_secret):
        return None

    oauth = OAuth()
    oauth.register(
        name="keycloak",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url=f"{issuer.rstrip('/')}/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid profile email",
            "code_challenge_method": "S256",
        },
    )
    return oauth


def parse_user_from_claims(claims: dict) -> dict:
    """ID 토큰 클레임에서 사용자 정보를 추출한다.

    realm_access.roles와 resource_access.<client_id>.roles를 모두 읽는다 (#20).

    Args:
        claims: Keycloak ID 토큰 클레임 딕셔너리.

    Returns:
        sub, email, name, roles 포함 딕셔너리.
    """
    sub: str = claims.get("sub", "")
    email: str = claims.get("email", "")
    name: str = claims.get("name", claims.get("preferred_username", ""))

    # Keycloak realm_access.roles 에서 역할 추출
    realm_roles: list[str] = claims.get("realm_access", {}).get("roles", [])

    # resource_access.<client_id>.roles 도 읽기 (#20)
    client_id = claims.get("azp", "")
    client_roles: list[str] = (
        claims.get("resource_access", {}).get(client_id, {}).get("roles", [])
    )

    # 합집합 후 정렬
    all_roles = sorted(set(realm_roles + client_roles))

    # 관심 역할만 필터 (시스템 정의 역할)
    system_roles = {"viewer", "sender", "admin"}
    filtered_roles = [r for r in all_roles if r in system_roles]

    # 역할이 없으면 기본값 viewer
    if not filtered_roles:
        filtered_roles = ["viewer"]

    return {
        "sub": sub,
        "email": email,
        "name": name,
        "roles": filtered_roles,
    }
