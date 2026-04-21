"""SQLAlchemy ORM 모델 — msghub 메시징 시스템.

모든 날짜/시간은 ISO-8601 텍스트(UTC)로 저장한다.
"""
from __future__ import annotations

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class User(Base):
    """Keycloak 로그인 시 upsert 되는 사용자 레코드."""

    __tablename__ = "users"

    sub: Mapped[str] = mapped_column(Text, primary_key=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    roles: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    last_login_at: Mapped[str] = mapped_column(Text, nullable=False)

    campaigns: Mapped[list[Campaign]] = relationship(
        "Campaign", back_populates="creator", lazy="select"
    )


class Caller(Base):
    """등록된 발신번호 (admin이 관리)."""

    __tablename__ = "callers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    number: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_default: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rcs_enabled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rcs_chatbot_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class Setting(Base):
    """시스템 설정 — env 대체. 시크릿은 Fernet 암호화 후 저장."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    is_secret: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class Campaign(Base):
    """발송 캠페인 — 사용자가 "보내기"를 한 번 누른 단위."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_by: Mapped[str] = mapped_column(
        Text, ForeignKey("users.sub"), nullable=False
    )
    caller_number: Mapped[str] = mapped_column(Text, nullable=False)
    # short | long | image (채널 중립 유형)
    message_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)  # 장문/이미지 전용
    content: Mapped[str] = mapped_column(Text, nullable=False)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False)
    ok_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pending_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # DRAFT | RESERVED | RESERVE_CANCELED | RESERVE_FAILED
    # | DISPATCHING | DISPATCHED | COMPLETED | PARTIAL_FAILED | FAILED
    state: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    completed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 예약 발송. nullable이면 즉시 발송.
    # reserve_time: 'YYYY-MM-DD HH:mm' (KST)
    reserve_time: Mapped[str | None] = mapped_column(Text, nullable=True)
    # msghub RCS 관련
    rcs_messagebase_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 예약발송 시 msghub webReqId (취소/조회용)
    web_req_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 비용 집계
    total_cost: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rcs_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fallback_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    creator: Mapped[User] = relationship("User", back_populates="campaigns")
    msghub_requests: Mapped[list[MsghubRequest]] = relationship(
        "MsghubRequest", back_populates="campaign", lazy="select"
    )
    messages: Mapped[list[Message]] = relationship(
        "Message", back_populates="campaign", lazy="select"
    )
    attachments: Mapped[list[Attachment]] = relationship(
        "Attachment", back_populates="campaign", lazy="select"
    )

    __table_args__ = (
        Index("idx_campaigns_created_by", "created_by"),
        Index("idx_campaigns_created_at", "created_at"),
    )


class MsghubRequest(Base):
    """msghub API 호출 단위 — campaign 1개 = msghub_request N개 (10명 청크)."""

    __tablename__ = "msghub_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("campaigns.id"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    response_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[str] = mapped_column(Text, nullable=False)

    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="msghub_requests")
    messages: Mapped[list[Message]] = relationship(
        "Message", back_populates="msghub_request", lazy="select"
    )

    __table_args__ = (
        UniqueConstraint("campaign_id", "chunk_index", name="uq_msghub_requests_chunk"),
    )


class Message(Base):
    """개별 수신자 메시지 (수신자 단위 결과 추적)."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("campaigns.id"), nullable=False
    )
    msghub_request_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("msghub_requests.id"), nullable=False
    )
    to_number: Mapped[str] = mapped_column(Text, nullable=False)
    to_number_raw: Mapped[str] = mapped_column(Text, nullable=False)
    cli_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    msg_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PENDING | REG | ING | DONE | FAILED
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    result_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_desc: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 실제 발송 채널 (RCS/SMS/LMS/MMS) — 리포트 수신 후 결정
    channel: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 과금 상품코드 (CHAT/SMS/LMS/MMS/ITMPL 등)
    product_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 건당 비용 (원, 실패=0)
    cost: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    telco: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON: fallback 사유 [{"ch":"RCS","fbResultCode":"51004","fbResultDesc":"..."}]
    fb_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_dt: Mapped[str | None] = mapped_column(Text, nullable=True)
    complete_time: Mapped[str | None] = mapped_column(Text, nullable=True)

    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="messages")
    msghub_request: Mapped[MsghubRequest] = relationship(
        "MsghubRequest", back_populates="messages"
    )

    __table_args__ = (
        Index("idx_messages_campaign_id", "campaign_id"),
        Index("idx_messages_status", "status"),
        Index("idx_messages_msghub_request_id", "msghub_request_id"),
        Index("idx_messages_cli_key", "cli_key"),
        Index("idx_messages_msg_key", "msg_key"),
    )


class Contact(Base):
    """주소록 연락처."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    department: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_sent_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sent_channel: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(Text, ForeignKey("users.sub"), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_contacts_phone", "phone"),
        Index("idx_contacts_email", "email"),
        Index("idx_contacts_department", "department"),
        Index("idx_contacts_name", "name"),
        Index("idx_contacts_active", "active"),
    )


class ContactGroup(Base):
    """연락처 그룹."""

    __tablename__ = "contact_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(Text, ForeignKey("users.sub"), nullable=False)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class ContactGroupMember(Base):
    """그룹 멤버십 (N:N)."""

    __tablename__ = "contact_group_members"

    group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contact_groups.id", ondelete="CASCADE"), primary_key=True
    )
    contact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("contacts.id", ondelete="CASCADE"), primary_key=True
    )
    added_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_cgm_contact_id", "contact_id"),
    )


class AuditLog(Base):
    """감사 로그 — 모든 중요 액션을 기록한다."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_sub: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class Attachment(Base):
    """첨부 이미지 — RCS(≤1MB) 또는 MMS(≤300KB JPEG) BLOB 저장."""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("campaigns.id"), nullable=True
    )
    msghub_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    stored_filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    uploaded_by: Mapped[str] = mapped_column(
        Text, ForeignKey("users.sub"), nullable=False
    )
    uploaded_at: Mapped[str] = mapped_column(Text, nullable=False)
    file_expires_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    # mms 또는 rcs
    channel: Mapped[str | None] = mapped_column(Text, nullable=True, default="mms")

    campaign: Mapped[Campaign | None] = relationship(
        "Campaign", back_populates="attachments"
    )

    __table_args__ = (
        Index("idx_attachments_campaign_id", "campaign_id"),
        Index("idx_attachments_uploaded_by", "uploaded_by"),
    )


class MoMessage(Base):
    """RCS 양방향 수신 메시지 (MO) — 고객이 챗봇으로 보낸 답장 및 postback 이벤트."""

    __tablename__ = "mo_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # msghub가 발급한 MO 고유 키 (멱등성 보장, msghub payload의 msgKey)
    mo_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # 답장을 보낸 고객 번호 (msghub payload의 phone)
    mo_number: Mapped[str] = mapped_column(Text, nullable=False)
    # 수신 챗봇(우리) 번호 (msghub payload의 chatbotId)
    mo_callback: Mapped[str | None] = mapped_column(Text, nullable=True)
    # message / postback (msghub payload의 eventType)
    mo_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 양방향 답장 발송 시 /rcs/bi/v1.1 에 넘겨야 하는 replyId
    reply_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 버튼 클릭 등 postback 이벤트의 식별자/데이터
    postback_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    postback_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 레거시 — v11 양방향 페이로드엔 없지만 미래 호환을 위해 유지 (nullable)
    product_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    mo_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 고객이 보낸 텍스트 (contentInfo.textMessage)
    mo_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    telco: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_cnt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # contentInfo 전체 JSON (fileMessage, geolocationPushMessage 등)
    content_info_lst: Mapped[str | None] = mapped_column(Text, nullable=True)
    # msghub가 기록한 수신 일시
    mo_recv_dt: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 원본 페이로드 전체 (감사/스키마 변경 대응)
    raw_payload: Mapped[str] = mapped_column(Text, nullable=False)
    # 우리 서버가 수신한 일시
    received_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_mo_messages_mo_number", "mo_number"),
        Index("idx_mo_messages_received_at", "received_at"),
    )
