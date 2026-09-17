"""예약 취소 캠페인의 대기(PENDING) 메시지를 CANCELED 로 정리.

예약 취소는 캠페인 state 만 RESERVE_CANCELED 로 바꾸고 메시지는 PENDING 으로 남겨
두었다. 발송되지 않을 메시지가 대화방 말풍선·캠페인 수신자 배지에 대기로 보이고,
재조정(reconcile)이 예약 시각 이후 매 주기 msghub 에 조회했다. 이제 취소 라우트가
같은 커밋에서 메시지도 CANCELED 로 바꾸므로 기존 행을 맞춘다.

campaign.state 만으로는 가리지 않는다. d407661(H6, 2026-05-30) 이전 라우트는 msghub 가
취소를 거부해도(이미 발송) RESERVE_CANCELED 로 커밋했다. 그런 캠페인의 PENDING 은
발송됐지만 리포트를 못 받은 행일 수 있으므로, 취소 감사 로그(CANCEL_RESERVE)가 예약
시각 이전인 캠페인만 옮긴다 — 예약 시각 전의 취소는 msghub 가 아직 실행하기 전이라
받아들여진 것이다. 예약 발송의 msghub_requests.sent_at 은 예약 시각(UTC)이고, 감사 로그
created_at 과 둘 다 datetime.isoformat() 의 UTC 문자열이라 문자열 비교가 시각 순서와
같다. 감사 로그가 없거나 예약 시각 이후인 캠페인은 PENDING 그대로(이전 표시 유지).

- 청크 요청 실패로 기록된 FAILED 행, 리포트를 받은 REG/ING/DONE 행은 그대로 둔다.
- 알려진 한계: 캠페인엔 마지막 청크의 webReqId 만 저장돼, 11명 이상 예약의 앞 청크는
  취소가 닿지 않고 발송됐을 수 있다. 리포트가 오면 DONE 으로 덮이지만
  (report._update_message) 끝내 못 받은 행은 CANCELED 로 남는다 — 취소 라우트와 같은
  기준이며 청크별 취소를 고칠 때 다시 본다.

멱등: 남은 대상이 없으면 변화 없음.

Revision ID: 0017
Revises: 0016
"""
from __future__ import annotations

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE messages SET status = 'CANCELED'
        WHERE status = 'PENDING'
          AND msghub_request_id IN (
            SELECT r.id
            FROM msghub_requests r
            JOIN campaigns c ON c.id = r.campaign_id
            WHERE c.state = 'RESERVE_CANCELED'
              AND EXISTS (
                SELECT 1 FROM audit_logs a
                WHERE a.action = 'CANCEL_RESERVE'
                  AND a.target = 'campaign:' || c.id
                  AND a.created_at < r.sent_at
              )
          )
        """
    )


def downgrade() -> None:
    # CANCELED 는 이 마이그레이션과 취소 라우트가 PENDING 에서만 만든다 — 되돌리면 이전 표현.
    op.execute("UPDATE messages SET status = 'PENDING' WHERE status = 'CANCELED'")
