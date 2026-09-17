"""msghub_requests.web_req_id — 예약 webReqId 를 청크(요청)마다 저장.

msghub 는 예약 발송 요청마다 webReqId 를 따로 발급하고 취소(sendCancel)도 webReqId 하나씩
받는다. 발송은 수신자 10명 청크마다 요청하는데 루프가 청크마다 campaigns.web_req_id 를
덮어써 마지막 청크 것만 남았다. 그래서 11명 이상 예약은 취소가 마지막 청크에만 닿고, 앞
청크는 화면에 취소로 보이면서도 예약 시각에 발송될 수 있었다. 이제 청크마다 저장한다.

기존 행:
- 요청이 1개뿐인 캠페인(10명 이하)은 campaigns.web_req_id 가 곧 그 요청의 것이라 옮긴다.
- 요청이 여럿인 캠페인은 옮기지 않는다. 저장된 값은 "마지막으로 커밋된 예약 청크" 의
  것인데, 빈 webReqId 응답·실패 청크·즉시 발송된 대체 청크가 섞이면 어느 청크인지 확정할
  수 없다. 취소 라우트가 이런 캠페인은 앱에서 취소하지 않고 msghub 콘솔 취소를 안내한다
  (예약은 최대 30일 뒤라 곧 사라지는 경로). campaigns.web_req_id 는 그 식별용으로 남긴다.

downgrade: 컬럼을 지우기 전에 campaigns.web_req_id 가 빈(이 변경 뒤 발송한) 캠페인에 가장
큰 chunk_index 요청의 webReqId 를 채워 이전 코드의 표현(마지막 청크 ID)을 되살린다. 나머지
청크 ID 는 담을 곳이 없어 사라지므로, 다시 upgrade 하면 그 여러 청크 캠페인은 레거시로 남는다.

Revision ID: 0018
Revises: 0017
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("msghub_requests") as batch:
        batch.add_column(sa.Column("web_req_id", sa.Text, nullable=True))

    op.execute(
        """
        UPDATE msghub_requests
        SET web_req_id = (
            SELECT c.web_req_id FROM campaigns c WHERE c.id = msghub_requests.campaign_id
        )
        WHERE web_req_id IS NULL
          AND campaign_id IN (
            SELECT r.campaign_id
            FROM msghub_requests r
            JOIN campaigns c ON c.id = r.campaign_id
            WHERE c.web_req_id IS NOT NULL
            GROUP BY r.campaign_id
            HAVING COUNT(*) = 1
          )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE campaigns
        SET web_req_id = (
            SELECT r.web_req_id FROM msghub_requests r
            WHERE r.campaign_id = campaigns.id AND r.web_req_id IS NOT NULL
            ORDER BY r.chunk_index DESC
            LIMIT 1
        )
        WHERE web_req_id IS NULL
          AND EXISTS (
            SELECT 1 FROM msghub_requests r
            WHERE r.campaign_id = campaigns.id AND r.web_req_id IS NOT NULL
          )
        """
    )

    with op.batch_alter_table("msghub_requests") as batch:
        batch.drop_column("web_req_id")
