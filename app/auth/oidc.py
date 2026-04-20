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


def _is_hangul(ch: str) -> bool:
    """문자가 한글 음절/자모 범위에 속하는지 판정."""
    if not ch:
        return False
    code = ord(ch)
    # Hangul Syllables, Jamo, Compatibility Jamo
    return (
        0xAC00 <= code <= 0xD7A3
        or 0x1100 <= code <= 0x11FF
        or 0x3130 <= code <= 0x318F
    )


def format_display_name(claims: dict) -> str:
    """표시용 이름을 생성한다.

    우선순위:
      1. family_name + given_name (성+이름) — 한글이면 붙여쓰기, 아니면 공백
      2. preferred_username — LDAP 연동 시 cn이 들어옴
      3. name — 원본 클레임
      4. email의 @앞부분

    Args:
        claims: OIDC 클레임 dict.

    Returns:
        사람이 읽기 좋은 표시명. 클레임이 전부 비어 있으면 빈 문자열.
    """
    family = (claims.get("family_name") or "").strip()
    given = (claims.get("given_name") or "").strip()
    if family and given:
        combined = family + given
        if all(_is_hangul(c) for c in combined):
            return combined
        return f"{family} {given}"
    if family or given:
        return family or given

    preferred = (claims.get("preferred_username") or "").strip()
    if preferred and "@" not in preferred:
        return preferred

    name = (claims.get("name") or "").strip()
    if name:
        return name

    email = claims.get("email") or ""
    return email.split("@")[0] if email else ""


def parse_user_from_claims(claims: dict) -> dict:
    """ID 토큰 클레임에서 사용자 정보를 추출한다.

    realm_access.roles와 resource_access.<client_id>.roles를 모두 읽는다 (#20).

    Args:
        claims: Keycloak ID 토큰 클레임 딕셔너리.

    Returns:
        sub, email, name, display_name, roles 포함 딕셔너리.
    """
    sub: str = claims.get("sub", "")
    email: str = claims.get("email", "")
    name: str = claims.get("name", claims.get("preferred_username", ""))
    display_name: str = format_display_name(claims) or name or email

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
        "display_name": display_name,
        "roles": filtered_roles,
    }
