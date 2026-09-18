"""기존 RCS·장문 0원 성공 행만 보정하고 다른 비용은 보존하는 0020 회귀 테스트."""
from __future__ import annotations

from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from app.models import Campaign, Message, MsghubRequest

_ROOT = Path(__file__).resolve().parents[1]


def _campaign(db, sub, rows, *, total_cost):
    campaign = Campaign(
        created_by=sub, caller_number="0212345678", message_type="long", content="테스트",
        total_count=len(rows), state="COMPLETED", created_at="2026-09-18T00:00:00+00:00",
        total_cost=total_cost,
    )
    db.add(campaign)
    db.flush()
    request = MsghubRequest(campaign_id=campaign.id, chunk_index=0, sent_at=campaign.created_at)
    db.add(request)
    db.flush()
    messages = []
    for channel, product, status, result, cost in rows:
        message = Message(
            campaign_id=campaign.id, msghub_request_id=request.id,
            to_number="01012345678", to_number_raw="01012345678",
            channel=channel, product_code=product, status=status, result_code=result, cost=cost,
        )
        db.add(message)
        messages.append(message)
    db.commit()
    return campaign, messages


def _run(db, action):
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "alembic"))
    migration = ScriptDirectory.from_config(cfg).get_revision("0020").module
    with Operations.context(MigrationContext.configure(db.connection())):
        getattr(migration, action)()
    db.expire_all()


def test_migration_repairs_only_known_zero_cost_successes(db_session, sample_user):
    campaign, messages = _campaign(db_session, sample_user.sub, [
        ("RCS", "RSMS", "DONE", "10000", 0),
        ("MMS", "LMS", "DONE", "10000", 0),
        ("SMS", "LMS", "DONE", "10000", 0),
        ("MMS", "LMS", "DONE", "10000", 27),
        ("MMS", "LMS", "DONE", "10000", 31),  # 이미 기록된 비용은 보존
        ("MMS", "MMS", "DONE", "10000", 85),
        ("RCS", "LMS", "DONE", "10000", 0),  # 별도 원인일 수 있는 0원
        ("MMS", "LMS", "DONE", "59999", 0),
        ("MMS", "LMS", "FAILED", "10000", 0),
        ("MMS", "LMS", "REG", "10000", 0),
        ("MMS", "LMS", "DONE", None, 0),
        ("MMS", "UNKNOWN", "DONE", "10000", 0),
        ("RCS", "RSMS", "DONE", "59999", 0),
        ("RCS", "RSMS", "REG", "10000", 0),
        ("SMS", "RSMS", "DONE", "10000", 0),
        ("RCS", "RLMS", "DONE", "10000", 0),
    ], total_cost=143)
    untouched, other = _campaign(db_session, sample_user.sub, [
        ("MMS", "LMS", "DONE", "10000", 27),
    ], total_cost=99)  # 보정 대상이 없는 캠페인의 별도 집계값은 건드리지 않는다

    _run(db_session, "upgrade")

    assert [m.cost for m in messages] == [17, 27, 27, 27, 31, 85, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]
    assert campaign.total_cost == 214
    assert (untouched.total_cost, other[0].cost) == (99, 27)


@pytest.mark.parametrize("channel,product,cost", [("MMS", "LMS", 27), ("RCS", "RSMS", 17)])
def test_migration_roundtrip_preserves_corrected_cost(db_session, sample_user, channel, product, cost):
    campaign, messages = _campaign(db_session, sample_user.sub, [
        (channel, product, "DONE", "10000", 0),
    ], total_cost=0)

    for action in ("upgrade", "upgrade", "downgrade", "upgrade"):
        _run(db_session, action)
        assert (messages[0].cost, campaign.total_cost) == (cost, cost)
