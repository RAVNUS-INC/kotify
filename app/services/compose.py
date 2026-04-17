"""발송 컴포즈 서비스.

번호 검증, 메시지 검증, 실제 발송(dispatch_campaign)을 담당한다.
msghub RCS 우선 발송 + SMS/LMS/MMS fallback (fbInfoLst).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Attachment, Caller, Campaign, Message, MsghubRequest
from app.msghub.client import CHUNK_SIZE
from app.msghub.codes import SUCCESS_CODE
from app.msghub.schemas import (
    FbInfo,
    MsghubAuthError,
    MsghubBadRequest,
    MsghubError,
    MsghubRateLimited,
    MsghubServerError,
    RecvInfo,
    ReserveResponse,
    SendResponse,
)
from app.services import audit
from app.util.phone import parse_phone_list
from app.util.text import classify_message_type, measure_bytes

if TYPE_CHECKING:
    from app.msghub.client import MsghubClient

log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def validate_phone_list(text: str) -> tuple[list[str], list[str]]:
    """수신자 텍스트를 파싱하여 유효/무효 번호를 분류한다."""
    return parse_phone_list(text)


def validate_message(
    content: str,
    message_type: str | None = None,
) -> dict:
    """메시지 내용을 검증한다.

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


# 1회 발송 최대 수신자 수
MAX_RECIPIENTS_PER_CAMPAIGN = 1000

# 예약 발송 최소 리드타임 (10분)
RESERVE_MIN_LEAD_SECONDS = 10 * 60

# 메시지 유형 → 채널 중립 유형
_MSG_TYPE_MAP = {"SMS": "short", "LMS": "long", "MMS": "image"}

# 메시지 유형 → RCS messagebaseId (모두 단방향 — fbInfoLst fallback 보장)
_MESSAGEBASE_MAP = {
    "short": "SS000000",     # RCS SMS형 (단방향, fbInfoLst 지원)
    "long": "SL000000",      # RCS LMS형
    "image": "OMHIMV0001",   # RCS 이미지 강조형
}


def _classify_msg_type(content: str, has_attachment: bool) -> str:
    """메시지 내용과 첨부 여부로 채널 중립 유형 결정."""
    if has_attachment:
        return "image"
    legacy = classify_message_type(content)
    return _MSG_TYPE_MAP.get(legacy, "short")


def parse_reserve_time(reserve_time_local: str) -> tuple[str, str]:
    """예약 시각을 검증하고 (msghub 전송용 문자열, UTC ISO) 반환.

    msghub는 타임존 파라미터가 없으므로 KST 고정.
    """
    from zoneinfo import ZoneInfo

    kst = ZoneInfo("Asia/Seoul")
    raw = reserve_time_local.strip().replace("T", " ")
    try:
        naive = datetime.strptime(raw, "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError(
            f"예약 시각 포맷 오류 (기대: 'YYYY-MM-DD HH:mm'): {reserve_time_local}"
        ) from exc

    local_dt = naive.replace(tzinfo=kst)
    utc_dt = local_dt.astimezone(UTC)

    now_utc = datetime.now(UTC)
    if (utc_dt - now_utc).total_seconds() < RESERVE_MIN_LEAD_SECONDS:
        minutes = RESERVE_MIN_LEAD_SECONDS // 60
        raise ValueError(f"예약 시각은 현재로부터 최소 {minutes}분 이후여야 합니다.")

    msghub_format = local_dt.strftime("%Y-%m-%d %H:%M")
    return msghub_format, utc_dt.isoformat()


def _make_cli_key(campaign_id: int, chunk_idx: int, recipient_idx: int) -> str:
    """cliKey 생성. 패턴: c{campaign_id}-{chunk}-{idx}"""
    return f"c{campaign_id}-{chunk_idx}-{recipient_idx}"


def _build_fallback(
    msg_type: str,
    content: str,
    subject: str | None,
    mms_file_id: str | None,
) -> list[FbInfo]:
    """RCS fallback 정보 생성."""
    if msg_type == "image":
        fb = FbInfo(ch="MMS", msg=content, title=subject or "")
        if mms_file_id:
            fb.file_id_lst = [mms_file_id]
        return [fb]
    # short/long → SMS fallback (90B 초과 시 msghub가 자동 LMS 처리)
    return [FbInfo(ch="SMS", msg=content)]


def _build_merge_data(
    msg_type: str,
    content: str,
    subject: str | None,
    rcs_file_id: str | None,
) -> dict[str, str]:
    """RCS mergeData 생성."""
    data: dict[str, str] = {"description": content}
    if subject:
        data["title"] = subject
    if rcs_file_id and msg_type == "image":
        data["media"] = f"maapfile://{rcs_file_id}"
    return data


async def dispatch_campaign(
    db: Session,
    msghub_client: MsghubClient,
    created_by: str,
    caller_number: str,
    content: str,
    recipients: list[str],
    message_type: str,
    subject: str | None = None,
    reserve_time_local: str | None = None,
    attachment_id: int | None = None,
) -> Campaign:
    """캠페인을 생성하고 msghub를 통해 RCS 우선 발송한다.

    모든 메시지 유형은 RCS 단방향 + fbInfoLst로 발송하여
    msghub가 RCS 미지원 단말에 자동으로 SMS/LMS/MMS fallback.
    """
    # 0. 수신자 수 제한
    if len(recipients) > MAX_RECIPIENTS_PER_CAMPAIGN:
        raise ValueError(f"1회 최대 {MAX_RECIPIENTS_PER_CAMPAIGN}명까지 발송할 수 있습니다.")
    if not recipients:
        raise ValueError("수신자 목록이 비어 있습니다.")

    # 0.5 예약 파라미터 검증
    is_reserved = reserve_time_local is not None
    msghub_reserve_time: str | None = None
    reserve_utc_iso: str | None = None
    if is_reserved:
        msghub_reserve_time, reserve_utc_iso = parse_reserve_time(reserve_time_local)  # type: ignore[arg-type]

    # 0.7 메시지 유형 결정 (채널 중립)
    has_attachment = attachment_id is not None
    msg_type = _classify_msg_type(content, has_attachment)

    # 0.8 첨부 파일 검증
    attachment: Attachment | None = None
    rcs_file_id: str | None = None
    mms_file_id: str | None = None
    if attachment_id is not None:
        attachment = db.get(Attachment, attachment_id)
        if attachment is None:
            raise ValueError(f"첨부 파일 #{attachment_id}을 찾을 수 없습니다.")
        if attachment.uploaded_by != created_by:
            raise ValueError("이 첨부 파일에 대한 권한이 없습니다.")
        if attachment.campaign_id is not None:
            raise ValueError("이 첨부 파일은 이미 다른 캠페인에 사용되었습니다.")
        if not attachment.msghub_file_id:
            raise ValueError("첨부 파일이 msghub에 업로드되지 않았습니다.")
        rcs_file_id = attachment.msghub_file_id
        mms_file_id = attachment.msghub_file_id

    # 1. 발신번호 검증
    caller = db.execute(
        select(Caller).where(Caller.number == caller_number, Caller.active == 1)
    ).scalar_one_or_none()
    if caller is None:
        raise ValueError(f"발신번호 '{caller_number}'가 활성 목록에 없습니다.")

    # 2. messagebaseId 결정
    messagebase_id = _MESSAGEBASE_MAP[msg_type]

    now = _now_iso()

    # 3. Campaign 생성
    initial_state = "RESERVED" if is_reserved else "DISPATCHING"
    campaign = Campaign(
        created_by=created_by,
        caller_number=caller_number,
        message_type=msg_type,
        subject=subject,
        content=content,
        total_count=len(recipients),
        ok_count=0,
        fail_count=0,
        pending_count=len(recipients),
        state=initial_state,
        created_at=now,
        completed_at=None,
        reserve_time=msghub_reserve_time if is_reserved else None,
        rcs_messagebase_id=messagebase_id,
        web_req_id=None,
        total_cost=0,
        rcs_count=0,
        fallback_count=0,
    )
    db.add(campaign)
    db.flush()

    if attachment is not None:
        attachment.campaign_id = campaign.id
        db.flush()

    db.commit()

    # 4. 청크 단위 발송 — RCS 단방향 + fbInfoLst (자동 fallback)
    chunks = [recipients[i : i + CHUNK_SIZE] for i in range(0, len(recipients), CHUNK_SIZE)]
    failed_chunks: list[int] = []
    failed_chunk_sizes: list[int] = []

    fb_info_lst = _build_fallback(msg_type, content, subject, mms_file_id)

    for chunk_idx, chunk in enumerate(chunks):
        sent_at = reserve_utc_iso if is_reserved else _now_iso()

        try:
            recv_list = [
                RecvInfo(
                    cli_key=_make_cli_key(campaign.id, chunk_idx, i),
                    phone=phone,
                    merge_data=_build_merge_data(msg_type, content, subject, rcs_file_id),
                )
                for i, phone in enumerate(chunk)
            ]

            resp = await msghub_client.send_rcs(
                messagebase_id=messagebase_id,
                callback=caller_number,
                recv_list=recv_list,
                fb_info_lst=fb_info_lst,
                resv_yn="Y" if is_reserved else None,
                resv_req_dt=msghub_reserve_time,
            )

            # 응답 기록
            msghub_req = MsghubRequest(
                campaign_id=campaign.id,
                chunk_index=chunk_idx,
                response_code=resp.code if resp else None,
                response_message=resp.message if resp else None,
                error_body=None,
                sent_at=sent_at,
            )
            db.add(msghub_req)
            db.flush()

            if isinstance(resp, ReserveResponse) and resp.web_req_id:
                campaign.web_req_id = resp.web_req_id

            # Message 레코드 생성
            _create_messages_from_response(
                db, campaign.id, msghub_req.id, resp, chunk, chunk_idx
            )
            db.flush()
            db.commit()

        except MsghubRateLimited:
            # CPS 초과: rollback + 30초 대기 후 1회 재시도
            db.rollback()
            await asyncio.sleep(30)
            sent_at = _now_iso()  # 재시도 시점으로 갱신
            try:
                resp = await _send_chunk_direct(
                    msghub_client, campaign, caller_number, content,
                    subject, chunk, chunk_idx, msg_type, mms_file_id,
                )
                msghub_req = MsghubRequest(
                    campaign_id=campaign.id,
                    chunk_index=chunk_idx,
                    response_code=resp.code,
                    response_message=resp.message,
                    error_body=None,
                    sent_at=sent_at,
                )
                db.add(msghub_req)
                db.flush()
                _create_messages_from_response(
                    db, campaign.id, msghub_req.id, resp, chunk, chunk_idx
                )
                db.flush()
                db.commit()
            except Exception as retry_exc:
                db.rollback()
                _record_failed_chunk(db, campaign.id, chunk_idx, chunk, sent_at, str(retry_exc))
                db.commit()
                failed_chunks.append(chunk_idx)
                failed_chunk_sizes.append(len(chunk))

        except MsghubBadRequest as exc:
            db.rollback()
            _record_failed_chunk(db, campaign.id, chunk_idx, chunk, sent_at, str(exc))
            db.commit()
            failed_chunks.append(chunk_idx)
            failed_chunk_sizes.append(len(chunk))

        except MsghubAuthError:
            db.rollback()
            _record_failed_chunk(db, campaign.id, chunk_idx, chunk, sent_at, "인증 오류")
            db.commit()
            raise

        except (MsghubServerError, MsghubError, Exception) as exc:
            db.rollback()
            _record_failed_chunk(db, campaign.id, chunk_idx, chunk, sent_at, str(exc))
            db.commit()
            failed_chunks.append(chunk_idx)
            failed_chunk_sizes.append(len(chunk))

    # 5. Campaign state + counters 업데이트
    total_chunks = len(chunks)
    failed_recipients = sum(failed_chunk_sizes)

    if len(failed_chunks) == 0:
        campaign.state = "RESERVED" if is_reserved else "DISPATCHED"
    elif len(failed_chunks) == total_chunks:
        campaign.state = "RESERVE_FAILED" if is_reserved else "FAILED"
    else:
        campaign.state = "PARTIAL_FAILED"

    campaign.fail_count = failed_recipients
    campaign.pending_count = max(0, len(recipients) - failed_recipients)

    db.flush()

    # 6. 감사 로그
    audit.log(
        db,
        actor_sub=created_by,
        action=audit.SEND,
        target=f"campaign:{campaign.id}",
        detail={
            "total": len(recipients),
            "chunks": total_chunks,
            "failed_chunks": failed_chunks,
            "message_type": msg_type,
            "rcs_messagebase_id": messagebase_id,
        },
    )

    db.commit()
    return campaign


async def _send_chunk_direct(
    client: MsghubClient,
    campaign: Campaign,
    callback: str,
    content: str,
    subject: str | None,
    chunk: list[str],
    chunk_idx: int,
    msg_type: str,
    mms_file_id: str | None = None,
) -> SendResponse | ReserveResponse:
    """RCS 실패 시 직접 SMS/LMS/MMS 발송 (재시도 fallback)."""
    recv_list = [
        RecvInfo(
            cli_key=_make_cli_key(campaign.id, chunk_idx, i),
            phone=phone,
        )
        for i, phone in enumerate(chunk)
    ]

    if msg_type == "short":
        return await client.send_sms(
            callback=callback, msg=content, recv_list=recv_list,
        )
    else:
        return await client.send_mms(
            callback=callback,
            title=subject or "",
            msg=content,
            recv_list=recv_list,
            file_id_lst=[mms_file_id] if mms_file_id else None,
        )


def _create_messages_from_response(
    db: Session,
    campaign_id: int,
    msghub_request_id: int,
    resp: SendResponse | ReserveResponse,
    chunk: list[str],
    chunk_idx: int,
) -> None:
    """발송 응답에서 Message 레코드 생성."""
    if isinstance(resp, SendResponse) and resp.items:
        for item in resp.items:
            msg = Message(
                campaign_id=campaign_id,
                msghub_request_id=msghub_request_id,
                to_number=item.phone,
                to_number_raw=item.phone,
                cli_key=item.cli_key,
                msg_key=item.msg_key,
                status="REG" if item.code == SUCCESS_CODE else "FAILED",
                result_code=item.code,
                result_desc=item.message,
            )
            db.add(msg)
    else:
        for i, phone in enumerate(chunk):
            msg = Message(
                campaign_id=campaign_id,
                msghub_request_id=msghub_request_id,
                to_number=phone,
                to_number_raw=phone,
                cli_key=_make_cli_key(campaign_id, chunk_idx, i),
                msg_key=None,
                status="PENDING",
            )
            db.add(msg)


def _record_failed_chunk(
    db: Session,
    campaign_id: int,
    chunk_idx: int,
    chunk: list[str],
    sent_at: str,
    error_body: str,
) -> None:
    """실패 청크의 MsghubRequest + Message 레코드를 기록한다."""
    msghub_req = MsghubRequest(
        campaign_id=campaign_id,
        chunk_index=chunk_idx,
        response_code=None,
        response_message="fail",
        error_body=error_body,
        sent_at=sent_at,
    )
    db.add(msghub_req)
    db.flush()

    for i, to_num in enumerate(chunk):
        msg = Message(
            campaign_id=campaign_id,
            msghub_request_id=msghub_req.id,
            to_number=to_num,
            to_number_raw=to_num,
            cli_key=_make_cli_key(campaign_id, chunk_idx, i),
            msg_key=None,
            status="FAILED",
            result_code=None,
            result_desc=error_body,
        )
        db.add(msg)
    db.flush()


def resolve_recipients(
    db: Session,
    source: str,
    recipients_text: str | None,
    group_ids: list[int] | None,
    contact_ids: list[int] | None,
) -> tuple[list[str], list[str], list[int]]:
    """수신자 출처를 펼쳐서 (valid_phones, invalid_originals, contact_ids_for_marking) 반환."""
    from app.services.groups import expand_groups_to_contacts

    if source == "groups":
        contacts = expand_groups_to_contacts(db, group_ids or [])
        phones = [c.phone for c in contacts if c.phone]
        marking_ids = [c.id for c in contacts if c.phone]
        return phones, [], marking_ids

    if source == "contacts":
        from app.models import Contact as _Contact
        ids = contact_ids or []
        if not ids:
            return [], [], []
        rows = list(
            db.execute(select(_Contact).where(_Contact.id.in_(ids))).scalars().all()
        )
        phones = [c.phone for c in rows if c.phone]
        marking_ids = [c.id for c in rows if c.phone]
        return phones, [], marking_ids

    # manual (default)
    valid, invalid = parse_phone_list(recipients_text or "")
    return valid, invalid, []
