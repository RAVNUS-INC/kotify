"""리포트의 전송 채널/과금 상품 조합 누락으로 기록된 0원 비용 보정.

2026-09-18 실발송으로 확인된 단방향 RCS(RPSSAXX001)의 실제 상품코드는 RSMS다.
기존 RCS/SMS와 같은 단문 요금이지만 단가표에 없어 성공해도 0원으로 기록했다.
msghub는 장문 결과를 ch=MMS, productCode=LMS로 전달할 수 있다(공식 report_v12
예시). 기존 연동 스펙의 ch=SMS, productCode=LMS도 같은 장문 과금 상품이다.
기존 단가표는 두 조합을 몰라 성공해도 0원으로 기록했다. DONE 메시지는 리포트와
재조정이 다시 처리하지 않으므로, 런타임 수정과 별도로 기존 0원 성공 행을 고친다.

확정 성공(DONE/10000), 알려진 세 조합, cost=0만 보정하고 해당 캠페인의 비용 합계를
재계산한다. 실패·미확정·기타 상품·이미 비용이 기록된 행은 보존한다.
단가는 이 수정 시점의 기존 단문 RCS 17원, LMS 27원(VAT 별도)으로 고정한다.

downgrade도 보정된 비용을 보존한다. 이미 정상적으로 기록한 비용과 보정한 비용은
구분할 수 없으므로 역산해 0원으로 만들지 않는다. 재실행해도 변화가 없다.

Revision ID: 0020
Revises: 0019
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

_AFFECTED = """
    status = 'DONE' AND result_code = '10000' AND cost = 0
    AND (
        (product_code = 'LMS' AND channel IN ('SMS', 'MMS'))
        OR (product_code = 'RSMS' AND channel = 'RCS')
    )
"""


def upgrade() -> None:
    connection = op.get_bind()
    campaign_ids = connection.execute(sa.text(
        f"SELECT DISTINCT campaign_id FROM messages WHERE {_AFFECTED}"
    )).scalars().all()
    if not campaign_ids:
        return

    connection.execute(sa.text(f"""
        UPDATE messages SET cost = CASE WHEN product_code = 'RSMS' THEN 17 ELSE 27 END
        WHERE {_AFFECTED}
    """))
    connection.execute(sa.text("""
        UPDATE campaigns
        SET total_cost = (
            SELECT COALESCE(SUM(m.cost), 0) FROM messages m
            WHERE m.campaign_id = campaigns.id
        )
        WHERE id = :campaign_id
    """), [{"campaign_id": campaign_id} for campaign_id in campaign_ids])


def downgrade() -> None:
    # 데이터 보정은 유지한다. 정상 비용을 구분 없이 0원으로 되돌리면 비용을 다시 잃는다.
    pass
