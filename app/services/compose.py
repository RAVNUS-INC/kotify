"""발송 컴포즈 서비스.

번호 검증, 메시지 검증, 실제 발송(dispatch_campaign)을 담당한다.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Attachment, Caller, Campaign, Message, MsghubRequest
from app.services import audit
from app.util.phone import parse_phone_list
from app.util.text import classify_message_type, measure_bytes

if TYPE_CHECKING:
    from app.msghub.client import MsghubClient


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def validate_phone_list(text: str) -> tuple[list[str], list[str]]:
    """수신자 텍스트를 파싱하여 유효/무효 번호를 분류한다.

    NotImplementedError는 phone.py가 stub인 경우 의도적으로 전파된다.

    Args:
        text: 줄바꿈/콤마/세미콜론으로 구분된 번호 텍스트.

    Returns:
        (valid_normalized, invalid_originals) 튜플.
    """
    return parse_phone_list(text)


def validate_message(
    content: str,
    message_type: str | None = None,
) -> dict:
    """메시지 내용을 검증한다.

    Args:
        content: 메시지 본문.
        message_type: 'SMS' 또는 'LMS'. None이면 자동 판정.

    Returns:
        {byte_len, message_type, ok, error} 딕셔너리.
    """
    try:
        byte_len = measure_bytes(content)
        detected_type = classify_message_type(content)
        final_type = message_type or detected_type
        return {
            "byte_len": byte_len,
            "message_type": final_type,
            "ok": True,
            "error": None,
        }
    except (ValueError, UnicodeEncodeError) as exc:
        return {
            "byte_len": 0,
            "message_type": message_type or "SMS",
            "ok": False,
            "error": str(exc),
        }


# 청크 크기 (NCP 제약: 단일 호출 최대 100건)
CHUNK_SIZE = 100

# 1회 발송 최대 수신자 수 (SPEC §0)
MAX_RECIPIENTS_PER_CAMPAIGN = 1000

# 예약 발송 최소 리드타임 (현재 시각 + 이 값) 이후만 허용.
# NCP 자체 제약은 10분이지만, 클라이언트/서버 시계 드리프트 버퍼 포함.
RESERVE_MIN_LEAD_SECONDS = 10 * 60


def parse_reserve_time(
    reserve_time_local: str, reserve_timezone: str
) -> tuple[str, str]:
    """예약 시각을 검증하고 (NCP 전송용 문자열, 실행 시각의 UTC ISO)를 반환한다.

    Args:
        reserve_time_local: 로컬 시각 문자열.
            허용 형식: 'YYYY-MM-DD HH:mm' 또는 'YYYY-MM-DDTHH:mm'
            (HTML datetime-local 인풋은 'T' 구분자를 쓴다).
        reserve_timezone: 'Asia/Seoul' 같은 IANA 타임존 ID.

    Returns:
        (ncp_reserve_time, reserve_execution_utc_iso) 튜플.
        - ncp_reserve_time: NCP에 전달할 'YYYY-MM-DD HH:mm' 포맷.
        - reserve_execution_utc_iso: 70분 cutoff 기준으로 쓸 UTC isoformat.

    Raises:
        ValueError: 포맷 오류, 알 수 없는 타임존, 과거/너무 가까운 시각.
    """
    try:
        tz = ZoneInfo(reserve_timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"알 수 없는 타임존: {reserve_timezone}") from exc

    raw = reserve_time_local.strip().replace("T", " ")
    try:
        naive = datetime.strptime(raw, "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError(
            f"예약 시각 포맷 오류 (기대: 'YYYY-MM-DD HH:mm'): {reserve_time_local}"
        ) from exc

    local_dt = naive.replace(tzinfo=tz)
    utc_dt = local_dt.astimezone(UTC)

    now_utc = datetime.now(UTC)
    if (utc_dt - now_utc).total_seconds() < RESERVE_MIN_LEAD_SECONDS:
        minutes = RESERVE_MIN_LEAD_SECONDS // 60
        raise ValueError(
            f"예약 시각은 현재로부터 최소 {minutes}분 이후여야 합니다."
        )

    ncp_format = local_dt.strftime("%Y-%m-%d %H:%M")
    return ncp_format, utc_dt.isoformat()


async def dispatch_campaign(
    db: Session,
    ncp_client: NCPClient,
    created_by: str,
    caller_number: str,
    content: str,
    recipients: list[str],
    message_type: str,
    subject: str | None = None,
    reserve_time_local: str | None = None,
    reserve_timezone: str | None = None,
    attachment_id: int | None = None,
) -> Campaign:
    """캠페인을 생성하고 NCP에 발송한다.

    알고리즘:
    1. 발송 전 정책 검증 (번호 유효성, 발신번호 활성 여부)
    2. Campaign INSERT (state=DISPATCHING)
    3. dispatch_campaign이 청크 분할 전담 (CHUNK_SIZE=100)
    4. 각 청크마다 ncp_client.send_sms (단일 호출 = 단일 청크)
    5. 각 청크 직후 list_by_request_id 호출 → messages 테이블 채움
    6. 청크마다 db.commit() (부분 실패 시 성공 청크 영구 보존)
    7. campaign state=DISPATCHED, 카운터 업데이트
    8. 감사 로그 기록

    Args:
        db: SQLAlchemy 세션.
        ncp_client: NCPClient 인스턴스.
        created_by: users.sub.
        caller_number: 발신번호 (숫자만).
        content: 메시지 본문.
        recipients: 정규화된 수신번호 목록 (숫자만).
        message_type: 'SMS' 또는 'LMS'.
        subject: LMS 제목 (선택).

    Returns:
        생성된 Campaign 인스턴스.

    Raises:
        ValueError: 번호 검증 실패 또는 발신번호 미등록.
        NotImplementedError: signature.py stub 미구현 시 전파.
    """
    from app.ncp.client import NCPAuthError, NCPBadRequest, NCPRateLimited, NCPServerError

    # 0. 수신자 수 제한 (SPEC §0: 1회 최대 1,000명)
    if len(recipients) > MAX_RECIPIENTS_PER_CAMPAIGN:
        raise ValueError(f"1회 최대 {MAX_RECIPIENTS_PER_CAMPAIGN}명까지 발송할 수 있습니다.")

    # 0.5 예약 파라미터 검증/변환
    # 예약 경로와 즉시 경로를 한 곳에서 가른다. reserve_time_local 이 있으면 예약.
    is_reserved = reserve_time_local is not None
    ncp_reserve_time: str | None = None
    reserve_execution_utc_iso: str | None = None
    if is_reserved:
        if not reserve_timezone:
            raise ValueError("예약 발송 시 reserve_timezone은 필수입니다.")
        ncp_reserve_time, reserve_execution_utc_iso = parse_reserve_time(
            reserve_time_local, reserve_timezone  # type: ignore[arg-type]
        )

    # 0.7 첨부 파일 검증 (MMS 경로)
    # attachment_id 가 있으면 message_type 은 MMS여야 한다. 권한 체크는
    # 라우트 계층에서 먼저 수행되지만, 여기서 한 번 더 created_by 일치 검증.
    attachment: Attachment | None = None
    file_ids: list[str] | None = None
    if attachment_id is not None:
        if message_type != "MMS":
            raise ValueError("첨부 파일은 MMS 메시지에만 사용할 수 있습니다.")
        attachment = db.get(Attachment, attachment_id)
        if attachment is None:
            raise ValueError(f"첨부 파일 #{attachment_id} 을 찾을 수 없습니다.")
        if attachment.uploaded_by != created_by:
            raise ValueError("이 첨부 파일에 대한 권한이 없습니다.")
        if attachment.campaign_id is not None:
            raise ValueError("이 첨부 파일은 이미 다른 캠페인에 사용되었습니다.")
        if not attachment.ncp_file_id:
            raise ValueError("첨부 파일이 NCP에 업로드되지 않았습니다.")
        file_ids = [attachment.ncp_file_id]
    elif message_type == "MMS":
        raise ValueError("MMS 메시지는 첨부 파일이 필요합니다.")

    # 1. 발신번호 활성 여부 검증 (UI 우회 방지)
    caller = db.execute(
        select(Caller).where(
            Caller.number == caller_number,
            Caller.active == 1,
        )
    ).scalar_one_or_none()
    if caller is None:
        raise ValueError(f"발신번호 '{caller_number}'가 활성 목록에 없습니다.")

    # 2. 수신번호 유효성 검증 (잘못된 번호 1개라도 있으면 차단)
    if not recipients:
        raise ValueError("수신자 목록이 비어 있습니다.")

    now = _now_iso()

    # 3. Campaign 생성
    # 예약이면 RESERVED, 아니면 DISPATCHING.
    initial_state = "RESERVED" if is_reserved else "DISPATCHING"
    campaign = Campaign(
        created_by=created_by,
        caller_number=caller_number,
        message_type=message_type,
        subject=subject,
        content=content,
        total_count=len(recipients),
        ok_count=0,
        fail_count=0,
        pending_count=len(recipients),
        state=initial_state,
        created_at=now,
        completed_at=None,
        reserve_time=ncp_reserve_time if is_reserved else None,
        reserve_timezone=reserve_timezone if is_reserved else None,
    )
    db.add(campaign)
    db.flush()  # campaign.id 확보

    # MMS: 캠페인 생성 직후 attachment 를 이 캠페인에 귀속시킨다.
    # (campaign_id 가 묶이지 않은 attachment 는 orphan 으로 간주됨)
    if attachment is not None:
        attachment.campaign_id = campaign.id
        db.flush()

    db.commit()  # Campaign을 먼저 커밋 (청크 실패 시에도 Campaign 기록 유지)

    # 4. 청크 단위 발송 — dispatch_campaign이 청크 분할 전담 (#2)
    chunks = [recipients[i : i + CHUNK_SIZE] for i in range(0, len(recipients), CHUNK_SIZE)]

    failed_chunks: list[int] = []
    failed_chunk_sizes: list[int] = []

    for chunk_idx, chunk in enumerate(chunks):
        # 예약이면 sent_at = 예약 실행 시각(UTC). 즉시 발송이면 지금.
        # 이래야 poller의 70분 cutoff가 "예약 실행 +70분" 을 의미하여
        # 예약 전 구간에는 자동으로 cutoff 되지 않는다.
        sent_at = reserve_execution_utc_iso if is_reserved else _now_iso()
        try:
            # send_sms는 단일 청크(≤100건)만 처리 (#2)
            send_resp = await ncp_client.send_sms(
                from_number=caller_number,
                content=content,
                to_numbers=chunk,
                message_type=message_type,  # type: ignore[arg-type]
                subject=subject,
                reserve_time=ncp_reserve_time,
                reserve_time_zone=reserve_timezone if is_reserved else None,
                file_ids=file_ids,
            )

            ncp_req = NcpRequest(
                campaign_id=campaign.id,
                chunk_index=chunk_idx,
                request_id=send_resp.request_id if send_resp else None,
                request_time=send_resp.request_time if send_resp else None,
                http_status=202,
                status_code=send_resp.status_code if send_resp else None,
                status_name=send_resp.status_name if send_resp else None,
                error_body=None,
                sent_at=sent_at,
            )
            db.add(ncp_req)
            db.flush()

            # 5. messageId 수집 (발송 직후 1회 list 호출).
            # 예약 경로에서는 스킵 — NCP는 예약 실행 전까지 messages가 비어 있다.
            # Phase B3의 reserve-status 폴링이 DONE을 감지하면 그때 정상 폴링 루프로 진입.
            if is_reserved:
                for to_num in chunk:
                    msg = Message(
                        campaign_id=campaign.id,
                        ncp_request_id=ncp_req.id,
                        to_number=to_num,
                        to_number_raw=to_num,
                        message_id=None,
                        status="PENDING",
                        result_status=None,
                        result_code=None,
                        result_message=None,
                        telco_code=None,
                        complete_time=None,
                        last_polled_at=None,
                        poll_count=0,
                    )
                    db.add(msg)
            elif send_resp and send_resp.request_id:
                try:
                    list_resp = await ncp_client.list_by_request_id(send_resp.request_id)
                    # to_number → (message_id, status) 매핑 (#19: 같은 번호 여러 개 대응)
                    msg_by_to: dict[str, list[tuple[str, str]]] = {}
                    for item in list_resp.messages:
                        msg_by_to.setdefault(item.to, []).append(
                            (item.message_id, item.status)
                        )
                except Exception:
                    msg_by_to = {}

                for to_num in chunk:
                    entries = msg_by_to.get(to_num, [])
                    if entries:
                        message_id, status = entries.pop(0)
                    else:
                        message_id, status = None, "PENDING"
                    msg = Message(
                        campaign_id=campaign.id,
                        ncp_request_id=ncp_req.id,
                        to_number=to_num,
                        to_number_raw=to_num,
                        message_id=message_id,
                        status=status,
                        result_status=None,
                        result_code=None,
                        result_message=None,
                        telco_code=None,
                        complete_time=None,
                        last_polled_at=None,
                        poll_count=0,
                    )
                    db.add(msg)
            else:
                # 발송 응답이 없으면 PENDING으로만 기록
                for to_num in chunk:
                    msg = Message(
                        campaign_id=campaign.id,
                        ncp_request_id=ncp_req.id,
                        to_number=to_num,
                        to_number_raw=to_num,
                        message_id=None,
                        status="PENDING",
                        result_status=None,
                        result_code=None,
                        result_message=None,
                        telco_code=None,
                        complete_time=None,
                        last_polled_at=None,
                        poll_count=0,
                    )
                    db.add(msg)

            db.flush()
            db.commit()  # 청크 단위 커밋 (#4/#12)

        except NCPBadRequest as exc:
            # 400: 요청 오류 — 재시도 불가 (#32)
            ncp_req = NcpRequest(
                campaign_id=campaign.id,
                chunk_index=chunk_idx,
                request_id=None,
                request_time=None,
                http_status=400,
                status_code=None,
                status_name="fail",
                error_body=str(exc),
                sent_at=sent_at,
            )
            db.add(ncp_req)
            db.flush()
            failed_chunks.append(chunk_idx)
            failed_chunk_sizes.append(len(chunk))

            for to_num in chunk:
                msg = Message(
                    campaign_id=campaign.id,
                    ncp_request_id=ncp_req.id,
                    to_number=to_num,
                    to_number_raw=to_num,
                    message_id=None,
                    status="UNKNOWN",
                    result_status=None,
                    result_code=None,
                    result_message=None,
                    telco_code=None,
                    complete_time=None,
                    last_polled_at=None,
                    poll_count=0,
                )
                db.add(msg)
            db.flush()
            db.commit()  # 실패 청크도 즉시 커밋

        except NCPRateLimited:
            # 429: 30초 대기 후 1회 재시도 (#32)
            await asyncio.sleep(30)
            try:
                send_resp = await ncp_client.send_sms(
                    from_number=caller_number,
                    content=content,
                    to_numbers=chunk,
                    message_type=message_type,  # type: ignore[arg-type]
                    subject=subject,
                )
                ncp_req = NcpRequest(
                    campaign_id=campaign.id,
                    chunk_index=chunk_idx,
                    request_id=send_resp.request_id,
                    request_time=send_resp.request_time,
                    http_status=202,
                    status_code=send_resp.status_code,
                    status_name=send_resp.status_name,
                    error_body=None,
                    sent_at=sent_at,
                )
                db.add(ncp_req)
                db.flush()
                for to_num in chunk:
                    msg = Message(
                        campaign_id=campaign.id,
                        ncp_request_id=ncp_req.id,
                        to_number=to_num,
                        to_number_raw=to_num,
                        message_id=None,
                        status="PENDING",
                        result_status=None,
                        result_code=None,
                        result_message=None,
                        telco_code=None,
                        complete_time=None,
                        last_polled_at=None,
                        poll_count=0,
                    )
                    db.add(msg)
                db.flush()
                db.commit()
            except Exception as retry_exc:
                db.rollback()
                _record_failed_chunk(
                    db, campaign.id, chunk_idx, chunk, sent_at, str(retry_exc)
                )
                db.commit()
                failed_chunks.append(chunk_idx)
                failed_chunk_sizes.append(len(chunk))

        except NCPServerError as exc:
            # 5xx: 즉시 다음 청크로 (#32)
            db.rollback()
            _record_failed_chunk(db, campaign.id, chunk_idx, chunk, sent_at, str(exc))
            db.commit()
            failed_chunks.append(chunk_idx)
            failed_chunk_sizes.append(len(chunk))

        except Exception as exc:
            # 기타 실패: error_body에 기록, messages는 UNKNOWN
            db.rollback()
            _record_failed_chunk(db, campaign.id, chunk_idx, chunk, sent_at, str(exc))
            db.commit()
            failed_chunks.append(chunk_idx)
            failed_chunk_sizes.append(len(chunk))

            # NCPAuthError는 전파
            from app.ncp.client import NCPAuthError
            if isinstance(exc, NCPAuthError):
                raise

    # 6. Campaign state 업데이트
    # 예약 경로: 모두 성공했으면 RESERVED 유지, 일부/전체 실패는 기존과 동일 분류.
    # (예약 등록 실패 = NCP 쪽 4xx/5xx; "예약됨" 상태로 남기면 안 됨)
    total_chunks = len(chunks)
    if len(failed_chunks) == 0:
        campaign.state = "RESERVED" if is_reserved else "DISPATCHED"
    elif len(failed_chunks) == total_chunks:
        campaign.state = "RESERVE_FAILED" if is_reserved else "FAILED"
    else:
        # 부분 실패 — 예약이어도 일부는 NCP에 등록됐으니 PARTIAL_FAILED 그대로.
        campaign.state = "PARTIAL_FAILED"

    # #13: pending_count는 실패 청크의 실제 건수 기반으로 계산
    failed_recipients = sum(failed_chunk_sizes)
    campaign.pending_count = len(recipients) - failed_recipients
    if campaign.pending_count < 0:
        campaign.pending_count = 0

    db.flush()

    # 7. 감사 로그
    audit.log(
        db,
        actor_sub=created_by,
        action=audit.SEND,
        target=f"campaign:{campaign.id}",
        detail={
            "total": len(recipients),
            "chunks": total_chunks,
            "failed_chunks": failed_chunks,
            "message_type": message_type,
        },
    )

    db.commit()
    return campaign


def resolve_recipients(
    db: Session,
    source: str,
    recipients_text: str | None,
    group_ids: list[int] | None,
    contact_ids: list[int] | None,
) -> tuple[list[str], list[str], list[int]]:
    """수신자 출처를 펼쳐서 (valid_phones, invalid_originals, contact_ids_for_marking) 반환.

    Args:
        db: SQLAlchemy 세션.
        source: 'manual' | 'groups' | 'contacts'
        recipients_text: manual 모드일 때 수신자 텍스트.
        group_ids: groups 모드일 때 그룹 ID 목록.
        contact_ids: contacts 모드일 때 연락처 ID 목록.

    Returns:
        (valid_phones, invalid_originals, contact_ids_for_marking) 튜플.
    """
    from app.services.groups import expand_groups_to_contacts

    if source == "groups":
        contacts = expand_groups_to_contacts(db, group_ids or [])
        phones = [c.phone for c in contacts if c.phone]
        marking_ids = [c.id for c in contacts if c.phone]
        return phones, [], marking_ids

    if source == "contacts":
        from sqlalchemy import select as _select

        from app.models import Contact as _Contact
        ids = contact_ids or []
        if not ids:
            return [], [], []
        rows = list(
            db.execute(_select(_Contact).where(_Contact.id.in_(ids))).scalars().all()
        )
        phones = [c.phone for c in rows if c.phone]
        marking_ids = [c.id for c in rows if c.phone]
        return phones, [], marking_ids

    # manual (default)
    valid, invalid = parse_phone_list(recipients_text or "")
    return valid, invalid, []


def _record_failed_chunk(
    db: Session,
    campaign_id: int,
    chunk_idx: int,
    chunk: list[str],
    sent_at: str,
    error_body: str,
) -> None:
    """실패 청크의 NcpRequest + Message 레코드를 기록한다."""
    ncp_req = NcpRequest(
        campaign_id=campaign_id,
        chunk_index=chunk_idx,
        request_id=None,
        request_time=None,
        http_status=None,
        status_code=None,
        status_name="fail",
        error_body=error_body,
        sent_at=sent_at,
    )
    db.add(ncp_req)
    db.flush()

    for to_num in chunk:
        msg = Message(
            campaign_id=campaign_id,
            ncp_request_id=ncp_req.id,
            to_number=to_num,
            to_number_raw=to_num,
            message_id=None,
            status="UNKNOWN",
            result_status=None,
            result_code=None,
            result_message=None,
            telco_code=None,
            complete_time=None,
            last_polled_at=None,
            poll_count=0,
        )
        db.add(msg)
    db.flush()
