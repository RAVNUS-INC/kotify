"""org 설정 변경 감사 로그 테스트 (#17).

patch_org 가 조직 설정 변경 시 audit_logs 에 SETTINGS_UPDATE 를 기록하는지 검증.
이전엔 patch_provider 만 기록하고 patch_org 는 누락되어 변경 추적이 불완전했다.
"""
from __future__ import annotations

from sqlalchemy import select

from app.models import AuditLog
from app.routes.settings import OrgPatchBody, patch_org
from app.services import audit


def test_patch_org_writes_audit_log(db_session, sample_user):
    patch_org(OrgPatchBody(name="새 조직명"), user=sample_user, db=db_session)

    logs = db_session.execute(
        select(AuditLog).where(
            AuditLog.action == audit.SETTINGS_UPDATE,
            AuditLog.target == "org",
        )
    ).scalars().all()

    assert len(logs) == 1
    assert logs[0].actor_sub == sample_user.sub


def test_patch_org_audit_records_changed_fields(db_session, sample_user):
    patch_org(OrgPatchBody(name="조직"), user=sample_user, db=db_session)

    log = db_session.execute(
        select(AuditLog).where(AuditLog.target == "org")
    ).scalar_one()
    assert "name" in (log.detail or "")  # detail JSON 에 변경 필드 기록
