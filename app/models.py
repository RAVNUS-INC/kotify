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
    # name: Keycloak 'name' claim 원본 (감사/추적용, 로그인한 ID 그대로).
    # display_name: UI 표시용 — format_display_name() 결과. 로그인 시 갱신.
    # 분리 이유는 migration 0010 주석 참조.
    name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # 레거시 — 예전 발송은 청크마다 이 값을 덮어써 마지막 청크의 webReqId 만 남았다.
    # 이제 청크별로 MsghubRequest.web_req_id 에 저장하고 여기엔 쓰지 않는다(0018).
    web_req_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 비용 집계
    total_cost: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rcs_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fallback_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 멱등키 (C1) — 클라이언트가 보낸 Idempotency-Key. 재요청/재시도/동시요청 시
    # 중복 발송·이중 과금을 방지한다. nullable: 기존 레코드 및 키 미전송 요청 허용.
    # UNIQUE 인덱스로 INSERT 시점에 동시성까지 차단(NULL 은 충돌 안 함).
    idempotency_key: Mapped[str | None] = mapped_column(Text, nullable=True)

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
        Index("uq_campaigns_idempotency_key", "idempotency_key", unique=True),
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
    # 예약 발송 응답의 webReqId — msghub 는 요청(청크)마다 따로 발급하고 취소도 이
    # 단위라, 청크마다 저장해야 캠페인 전체를 취소할 수 있다. 즉시 발송·실패 청크는 NULL.
    web_req_id: Mapped[str | None] = mapped_column(Text, nullable=True)

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
    # PENDING | REG | ING | FB_PENDING | DONE | FAILED | CANCELED(예약 취소, 발송 안 됨)
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
        # 회신 담당자 조회(lookup_last_sender): WHERE to_number = ?
        Index("idx_messages_to_number", "to_number"),
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
    # 채널별 등록 파일. 기존 msghub_file_id는 MMS 파일 ID로 유지한다.
    msghub_rcs_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    rcs_file_expires_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    # mms 또는 mms+rcs
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


class MoMedia(Base):
    """고객 회신(MO)에 붙은 파일 1건 — RCS 양방향 contentInfo.fileMessage 와 1:1.

    fileUrl 은 통신사 서버 주소이고 일회성·단기 유효일 수 있어(msghub MMS MO 는 24시간·1회)
    수신 직후 한 번 내려받아 영구 보관한다. 원본 주소는 mo_messages.content_info_lst 에만 둔다.
    상태: PENDING(가져올 차례) → FETCHING(가져오는 중) → FETCHED / FAILED,
    이미지가 아닌 첨부는 UNSUPPORTED(내려받지 않음).
    """

    __tablename__ = "mo_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mo_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mo_messages.id", ondelete="CASCADE"), nullable=False
    )
    # 통신사가 알려 준 형식(fileMIMEType). 실제 응답 형식은 content_type.
    declared_mime: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fetch_status: Mapped[str] = mapped_column(Text, nullable=False)
    fetch_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("mo_id", name="uq_mo_media_mo_id"),
        Index("idx_mo_media_fetch", "fetch_status"),
    )


class NotificationDelivery(Base):
    """고객 회신 알림의 내구성 있는 n8n 전송 대기열."""

    __tablename__ = "notification_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mo_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("mo_messages.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    # PENDING | SENDING | DELIVERED | FAILED
    status: Mapped[str] = mapped_column(Text, nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[str] = mapped_column(Text, nullable=False)
    locked_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    delivered_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("mo_id", name="uq_notification_deliveries_mo_id"),
        Index("idx_notification_deliveries_due", "status", "next_attempt_at"),
    )


class ThreadRead(Base):
    """팀이 실제 관측한 마지막 MO ID. 같은 phone 의 모든 caller 행 중 MAX 를 공유한다.

    caller/read_at 은 기존 데이터·다운그레이드 호환용이다. 새 읽음 판정은 발생 시각이 아닌
    last_read_mo_id 를 사용하므로 조회 이후 도착한 메시지와 지연 웹훅을 읽음으로 삼키지 않는다.
    """

    __tablename__ = "thread_reads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 발신번호(우리 챗봇/대표번호)
    caller: Mapped[str] = mapped_column(Text, nullable=False)
    # 고객 번호
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    # 팀 전체 기준 마지막 읽음 시각 (ISO8601 UTC)
    read_at: Mapped[str] = mapped_column(Text, nullable=False)
    last_read_mo_id: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    __table_args__ = (
        UniqueConstraint("caller", "phone", name="uq_thread_reads_caller_phone"),
        Index("idx_thread_reads_phone", "phone"),
    )


class FaxJob(Base):
    """PBX(VitalPBX) 가상 팩스로 보낸 팩스 1건 — 받는 번호 1개당 1행.

    PBX 발송 API 는 파일 업로드가 아니라 URL 을 받아 PBX 가 내려받는 방식이라,
    PDF 원본을 여기 보관하고 서명된 짧은 수명 URL 로 내준다. 원본은 영구 보관한다.
    """

    __tablename__ = "fax_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_by: Mapped[str] = mapped_column(Text, ForeignKey("users.sub"), nullable=False)
    # 숫자만 저장 (국내 유선·휴대 0으로 시작 9~11자리)
    recipient: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    pdf_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # standard | medium | high
    resolution: Mapped[str] = mapped_column(Text, nullable=False)
    retries: Mapped[int] = mapped_column(Integer, nullable=False)
    retry_time: Mapped[int] = mapped_column(Integer, nullable=False)
    # QUEUED | SUBMITTED | SENT | FAILED | UNKNOWN
    status: Mapped[str] = mapped_column(Text, nullable=False, default="QUEUED")
    # 발송 응답의 PBX 임시 파일 이름(basename) — 팩스 로그와 맞추는 키
    pbx_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    pbx_log_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # PBX 가 알려 준 실패 사유 또는 kotify 판단 사유 (번호·URL 미포함)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetch_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)
    submitted_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("idx_fax_jobs_status", "status"),
        Index("idx_fax_jobs_created_by", "created_by", "id"),
    )


class FaxInbox(Base):
    """PBX 가상 팩스로 받은 팩스 1건 — PBX 팩스 로그 1건과 1:1.

    PDF 는 PBX 에서 읽기 전용 SFTP 로 가져와 영구 보관한다. 수신 실패도 기록해
    누가 보내려다 실패했는지 보여 준다(PDF 없음).
    """

    __tablename__ = "fax_inbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pbx_log_id: Mapped[int] = mapped_column(Integer, nullable=False)
    received_at: Mapped[str] = mapped_column(Text, nullable=False)
    # 숫자만 (PBX sender 의 번호 부분). 모르면 빈 문자열
    sender_number: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # RECEIVED | FAILED
    status: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pbx_file: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # PENDING | FETCHED | FETCH_FAILED | NONE(가져올 PDF 없음)
    fetch_status: Mapped[str] = mapped_column(Text, nullable=False)
    fetch_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    first_viewed_at: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_viewed_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("pbx_log_id", name="uq_fax_inbox_pbx_log_id"),
        Index("idx_fax_inbox_received_at", "received_at"),
        Index("idx_fax_inbox_fetch", "fetch_status"),
    )
