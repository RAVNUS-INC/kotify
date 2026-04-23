"""users 에 display_name 컬럼 추가

기존에는 users.name 에 Keycloak 의 `name` claim 을 그대로 저장했는데,
LDAP 연동 시 보통 "given_name family_name" 서구식이라 한국어 환경에서
"길동 홍" 처럼 이름+성 순서로 표시되는 문제.

display_name 을 별도 컬럼으로 분리해 `format_display_name()` 결과(성+이름
한글 붙여쓰기 → CN → name → email 우선순위) 를 저장한다. 원본 `name` 은
감사/추적용으로 그대로 유지.

기존 레코드는 초기값으로 name 을 복사 — 해당 사용자가 재로그인하면
auth flow 에서 정확한 display_name 으로 덮어씀.

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-23
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"


def upgrade() -> None:
    # 1) nullable 로 컬럼 추가 (SQLite 호환 위해 batch).
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("display_name", sa.Text, nullable=True))

    # 2) 기존 row 백필 — name 을 그대로 복사. 사용자가 다음 로그인할 때
    #    auth.py 의 upsert 가 format_display_name 결과로 덮어씀.
    op.execute("UPDATE users SET display_name = name WHERE display_name IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("display_name")
