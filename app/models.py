"""SQLAlchemy ORM 모델 — SPEC §4 데이터 모델 구현.

모든 날짜/시간은 ISO-8601 텍스트(UTC)로 저장한다.
"""
from __future__ import annotations

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
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
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class Setting(Base):
    """시스템 설정 — env 대체. 시크릿은 Fernet 암호화 후 저장."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    is_secret: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # FK 없음 — "setup", user.sub, 또는 None 등 다양한 출처를 허용하는 메타데이터 컬럼
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
    message_type: Mapped[str] = mapped_column(Text, nullable=False)  # SMS | LMS | MMS
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)  # LMS/MMS 전용
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
    # 예약 발송 (NCP SENS v2). nullable이면 즉시 발송 캠페인.
    # reserve_time: 로컬 'YYYY-MM-DD HH:mm' (NCP 요청 포맷)
    # reserve_timezone: 'Asia/Seoul' 등 (NCP 기본값)
    reserve_time: Mapped[str | None] = mapped_column(Text, nullable=True)
    reserve_timezone: Mapped[str | None] = mapped_column(Text, nullable=True)

    creator: Mapped[User] = relationship("User", back_populates="campaigns")
    ncp_requests: Mapped[list[NcpRequest]] = relationship(
        "NcpRequest", back_populates="campaign", lazy="select"
    )
    messages: Mapped[list[Message]] = relationship(
        "Message", back_populates="campaign", lazy="select"
    )

    __table_args__ = (
        Index("idx_campaigns_created_by", "created_by"),
        Index("idx_campaigns_created_at", "created_at"),
    )


class NcpRequest(Base):
    """NCP API 호출 단위 — campaign 1개 = ncp_request N개 (청크)."""

    __tablename__ = "ncp_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("campaigns.id"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_time: Mapped[str | None] = mapped_column(Text, nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    status_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[str] = mapped_column(Text, nullable=False)

    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="ncp_requests")
    messages: Mapped[list[Message]] = relationship(
        "Message", back_populates="ncp_request", lazy="select"
    )

    __table_args__ = (
        UniqueConstraint("campaign_id", "chunk_index", name="uq_ncp_requests_chunk"),
        Index("idx_ncp_requests_request_id", "request_id"),
    )


class Message(Base):
    """개별 수신자 메시지 (수신자 단위 결과 추적)."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("campaigns.id"), nullable=False
    )
    ncp_request_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("ncp_requests.id"), nullable=False
    )
    to_number: Mapped[str] = mapped_column(Text, nullable=False)  # 정규화 후 숫자만
    to_number_raw: Mapped[str] = mapped_column(Text, nullable=False)  # 사용자 원본
    message_id: Mapped[str | None] = mapped_column(Text, nullable=True)  # NCP messageId
    # PENDING | READY | PROCESSING | COMPLETED | UNKNOWN
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    result_status: Mapped[str | None] = mapped_column(Text, nullable=True)   # success | fail
    result_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    telco_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    complete_time: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_polled_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    poll_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    campaign: Mapped[Campaign] = relationship("Campaign", back_populates="messages")
    ncp_request: Mapped[NcpRequest] = relationship(
        "NcpRequest", back_populates="messages"
    )

    __table_args__ = (
        Index("idx_messages_campaign_id", "campaign_id"),
        Index("idx_messages_status", "status"),
        Index("idx_messages_message_id", "message_id"),
        Index("idx_messages_ncp_request_id", "ncp_request_id"),
    )


class Contact(Base):
    """주소록 연락처."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    phone: Mapped[str | None] = mapped_column(Text, nullable=True)  # 정규화된 형태
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
    department: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_sent_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_sent_channel: Mapped[str | None] = mapped_column(Text, nullable=True)  # sms, email
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
    added_by: Mapped[str | None] = mapped_column(Text, nullable=True)  # FK 없음 (system 액션 등 허용)
    added_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        Index("idx_cgm_contact_id", "contact_id"),
    )


class AuditLog(Base):
    """감사 로그 — 모든 중요 액션을 기록한다."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_sub: Mapped[str | None] = mapped_column(Text, nullable=True)
    # LOGIN | SEND | CALLER_CREATE | CALLER_DELETE | SETTING_CHANGE | ...
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    ip: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
