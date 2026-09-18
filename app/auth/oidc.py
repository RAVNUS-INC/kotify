"""OIDC 클라이언트 — Authlib 기반 Keycloak 연동.

lazy 초기화: setup wizard 완료 전엔 DB에 설정이 없을 수 있음.
get_oauth_client()가 매번 DB에서 읽어 동적 구성한다.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from authlib.integrations.starlette_client import OAuth

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

SYSTEM_ROLES = frozenset({"viewer", "sender", "admin"})


def _diagnostic_type(value: object) -> str:
    """임의 클레임 값/클래스명을 노출하지 않는 고정 타입 이름."""
    if value is None:
        return "null"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "other"


def role_diagnostic_summary(roles: object) -> dict:
    """진단 전용: 지원 역할만 노출하고 나머지 값은 개수로만 기록한다."""
    values = roles if isinstance(roles, list) else []
    known = [r for r in values if isinstance(r, str) and r in SYSTEM_ROLES]
    return {
        "type": _diagnostic_type(roles),
        "known_roles": sorted(set(known)),
        "unknown_role_count": len(values) - len(known),
    }


def _access_diagnostics(access: object, *, present: bool) -> dict:
    roles_present = isinstance(access, Mapping) and "roles" in access
    roles = access.get("roles") if isinstance(access, Mapping) else None
    return {
        "present": present,
        "type": _diagnostic_type(access) if present else "missing",
        "roles_present": roles_present,
        "roles": role_diagnostic_summary(roles),
    }


def diagnose_role_claims(claims: Mapping, configured_client_id: str | None) -> dict:
    """인증된 클레임의 역할 위치/형태를 요약한다. 권한 판정에는 사용하지 않는다.

    client id, azp, 프로필, 토큰, 미지원 역할 이름은 반환하지 않는다.
    실제 파서가 읽는 azp 클라이언트와 설정된 클라이언트를 따로 확인한다.
    """
    realm_access = claims.get("realm_access")
    resource_access = claims.get("resource_access")
    resources = resource_access if isinstance(resource_access, Mapping) else {}
    azp = claims.get("azp", "")
    azp_key = azp if isinstance(azp, str) else None
    realm = _access_diagnostics(realm_access, present="realm_access" in claims)
    azp_client = _access_diagnostics(
        resources.get(azp_key), present=azp_key in resources,
    )
    configured_client = _access_diagnostics(
        resources.get(configured_client_id), present=configured_client_id in resources,
    )
    other_clients = [
        access for client, access in resources.items()
        if client not in (azp_key, configured_client_id)
    ]
    other_known_roles = {
        role
        for access in other_clients
        for role in _access_diagnostics(access, present=True)["roles"]["known_roles"]
    }
    return {
        "realm_access": realm,
        "resource_access_present": "resource_access" in claims,
        "resource_access_type": _diagnostic_type(resource_access),
        "azp_present": "azp" in claims,
        "azp_type": _diagnostic_type(claims.get("azp")),
        "configured_client_present": bool(configured_client_id),
        "configured_client_matches_azp": bool(configured_client_id)
        and configured_client_id == azp,
        "azp_client": azp_client,
        "configured_client": configured_client,
        "other_client_count": len(other_clients),
        "other_client_known_roles": sorted(other_known_roles),
        "viewer_fallback_used": not (
            realm["roles"]["known_roles"] or azp_client["roles"]["known_roles"]
        ),
    }


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
    filtered_roles = [r for r in all_roles if r in SYSTEM_ROLES]

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
