"""NCP → msghub 마이그레이션: 모델 변경

- ncp_requests → msghub_requests (테이블 rename + 컬럼 변경)
- messages: NCP 필드 제거, msghub 필드 추가 (cli_key, msg_key, channel, product_code, cost, fb_reason, report_dt)
- campaigns: message_type 확장, rcs/비용 필드 추가
- callers: rcs_enabled, rcs_chatbot_id 추가
- attachments: ncp_file_id → msghub_file_id, ncp_expires_at → file_expires_at, channel 추가
- settings: ncp.* 키 백업 후 삭제

SQLite은 ALTER TABLE 제약이 있어 batch mode 사용.

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-17
"""
import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"


def upgrade() -> None:
    # ── ncp_requests → msghub_requests ─────────────────────────────��──────
    op.rename_table("ncp_requests", "msghub_requests")

    with op.batch_alter_table("msghub_requests") as batch_op:
        # 신규 ���럼 추가
        batch_op.add_column(sa.Column("response_code", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("response_message", sa.Text(), nullable=True))

    # 기존 데이터 복사
    op.execute("UPDATE msghub_requests SET response_code = status_code WHERE status_code IS NOT NULL")
    op.execute("UPDATE msghub_requests SET response_message = status_name WHERE status_name IS NOT NULL")

    with op.batch_alter_table("msghub_requests") as batch_op:
        # 기존 인��스 삭제
        batch_op.drop_index("idx_ncp_requests_request_id")
        # 기존 컬럼 삭��
        batch_op.drop_column("request_id")
        batch_op.drop_column("request_time")
        batch_op.drop_column("http_status")
        batch_op.drop_column("status_code")
        batch_op.drop_column("status_name")
        # 제약조건 업데이트
        batch_op.drop_constraint("uq_ncp_requests_chunk", type_="unique")
        batch_op.create_unique_constraint("uq_msghub_requests_chunk", ["campaign_id", "chunk_index"])

    # ── messages ──────────────────────────────────────────────────────────
    with op.batch_alter_table("messages") as batch_op:
        # 기존 NCP 인덱스 삭제
        batch_op.drop_index("idx_messages_message_id")
        batch_op.drop_index("idx_messages_ncp_request_id")
        # NCP 전용 필드 제거
        batch_op.drop_column("message_id")
        batch_op.drop_column("result_status")
        batch_op.drop_column("result_message")
        batch_op.drop_column("telco_code")
        batch_op.drop_column("last_polled_at")
        batch_op.drop_column("poll_count")
        # FK 교체: ncp_request_id → msghub_request_id
        batch_op.add_column(sa.Column("msghub_request_id", sa.Integer(), nullable=True))

        # msghub 신규 필드
        batch_op.add_column(sa.Column("cli_key", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("msg_key", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("result_desc", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("channel", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("product_code", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("cost", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("telco", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("fb_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("report_dt", sa.Text(), nullable=True))

    # 기존 FK 데이터 복사
    op.execute("UPDATE messages SET msghub_request_id = ncp_request_id")

    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_column("ncp_request_id")
        # FK + NOT NULL 적용
        batch_op.alter_column("msghub_request_id", nullable=False)
        batch_op.create_foreign_key(
            "fk_messages_msghub_request_id",
            "msghub_requests", ["msghub_request_id"], ["id"],
        )
        # 신규 인덱스
        batch_op.create_index("idx_messages_msghub_request_id", ["msghub_request_id"])
        batch_op.create_index("idx_messages_cli_key", ["cli_key"])
        batch_op.create_index("idx_messages_msg_key", ["msg_key"])

    # ── campaigns ────────────────���────────────────────────────────────────
    with op.batch_alter_table("campaigns") as batch_op:
        batch_op.add_column(sa.Column("rcs_messagebase_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("web_req_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("total_cost", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("rcs_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("fallback_count", sa.Integer(), nullable=False, server_default="0"))
        batch_op.drop_column("reserve_timezone")

    # ── callers ───────────────────────────────────────────────────────────
    with op.batch_alter_table("callers") as batch_op:
        batch_op.add_column(sa.Column("rcs_enabled", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("rcs_chatbot_id", sa.Text(), nullable=True))

    # ── attachments ───────────────────���───────────────────────────────────
    with op.batch_alter_table("attachments") as batch_op:
        batch_op.add_column(sa.Column("msghub_file_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("file_expires_at", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("channel", sa.Text(), nullable=True, server_default="mms"))

    op.execute("UPDATE attachments SET msghub_file_id = ncp_file_id WHERE ncp_file_id IS NOT NULL")
    op.execute("UPDATE attachments SET file_expires_at = ncp_expires_at WHERE ncp_expires_at IS NOT NULL")

    with op.batch_alter_table("attachments") as batch_op:
        batch_op.drop_column("ncp_file_id")
        batch_op.drop_column("ncp_expires_at")

    # ── settings: NCP 키 백업 후 삭제 ─────────────────────────────────────
    op.execute("CREATE TABLE IF NOT EXISTS _backup_ncp_settings AS SELECT * FROM settings WHERE key LIKE 'ncp.%'")
    op.execute("DELETE FROM settings WHERE key LIKE 'ncp.%'")


def downgrade() -> None:
    raise NotImplementedError("NCP로의 역방향 마이그레이션은 지원하지 않습니다")
