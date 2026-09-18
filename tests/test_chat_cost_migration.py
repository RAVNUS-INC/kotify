"""0022는 기존 CHAT 비용에만 세션 상한을 적용한다."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from app.models import Campaign, Message, MsghubRequest

_ROOT = Path(__file__).resolve().parents[1]


def _row(db, user_sub: str, *, created_at: datetime, phone: str, product="CHAT", cost=8):
    stamp = created_at.isoformat()
    campaign = Campaign(
        created_by=user_sub,
        caller_number="0212345678",
        message_type="short",
        content="답장",
        total_count=1,
        ok_count=1,
        pending_count=0,
        state="COMPLETED",
        created_at=stamp,
        total_cost=cost,
        rcs_messagebase_id="RPCSAXX001",
    )
    db.add(campaign)
    db.flush()
    request = MsghubRequest(campaign_id=campaign.id, chunk_index=0, sent_at=stamp)
    db.add(request)
    db.flush()
    message = Message(
        campaign_id=campaign.id,
        msghub_request_id=request.id,
        to_number=phone,
        to_number_raw=phone,
        status="DONE",
        result_code="10000",
        channel="RCS",
        product_code=product,
        cost=cost,
    )
    db.add(message)
    db.flush()
    return campaign, message


def _run(db, action: str):
    cfg = Config(str(_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_ROOT / "alembic"))
    migration = ScriptDirectory.from_config(cfg).get_revision("0022").module
    with Operations.context(MigrationContext.configure(db.connection())):
        getattr(migration, action)()
    db.expire_all()


def test_migration_caps_existing_chat_and_preserves_other_products(db_session, sample_user):
    start = datetime(2026, 9, 18, tzinfo=UTC)
    rows = [
        _row(
            db_session,
            sample_user.sub,
            created_at=start + timedelta(minutes=index),
            phone="01012345678",
        )
        for index in range(11)
    ]
    other_phone = _row(
        db_session, sample_user.sub, created_at=start, phone="01099999999"
    )
    next_session = _row(
        db_session,
        sample_user.sub,
        created_at=start + timedelta(hours=24),
        phone="01012345678",
    )
    non_chat = _row(
        db_session,
        sample_user.sub,
        created_at=start + timedelta(minutes=12),
        phone="01012345678",
        product="RSMS",
        cost=17,
    )
    # 메시지 배분은 이미 맞지만 캠페인 합계만 과다한 경우도 migration이 고친다.
    rows[-1][1].cost = 0
    rows[-1][0].total_cost = 8
    db_session.commit()

    for action in ("upgrade", "upgrade", "downgrade", "upgrade"):
        _run(db_session, action)
        assert [message.cost for _, message in rows] == [8] * 10 + [0]
        assert [campaign.total_cost for campaign, _ in rows] == [8] * 10 + [0]
        assert other_phone[1].cost == other_phone[0].total_cost == 8
        assert next_session[1].cost == next_session[0].total_cost == 8
        assert non_chat[1].cost == non_chat[0].total_cost == 17
