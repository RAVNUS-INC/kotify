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

# 메시지 유형 → RCS messagebaseId (v11 통합 RCS 기준)
# 참조: claudedocs/msghub-api-guide.md §6, 공식 스펙 "2.3.2 통합 RCS 메시지"
#
# short (양방향 CHAT): RPCSAXX001 — 8원, fbInfoLst 미지원 → webhook에서 수동 SMS fallback
# short (예약/단방향):  RPSSAXX001 — 9원, fbInfoLst 자동 fallback
# long:                 RPLSAXX001 — 27원, fbInfoLst(SMS→LMS) 자동 fallback
# image:                RPMSMMX001 — 40원 (MMS M형), fbInfoLst(MMS) 자동 fallback
#
# 주의: 기존 migration-spec의 SCL00000/SL000000/OMHIMV0001은 통합 RCS 이전
# 사양이라 v11 엔드포인트에선 29003 NOT_FOUND로 거부됨.
_MESSAGEBASE_MAP = {
    "long": "RPLSAXX001",    # 통합 RCS LMS형 (단방향)
    "image": "RPMSMMX001",   # 통합 RCS MMS M형 (이미지 중심)
}

# 양방향 CHAT 동시 발송 수 (API 호출 1건 = 수신자 1명)
_CHAT_CONCURRENCY = 10


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
    """RCS fallback 정보 생성.

    msghub의 fbInfoLst.ch는 "SMS" 또는 "MMS"만 허용한다. 각 채널의
    msg 길이 제한이 엄격하게 검증되므로 content 바이트 수에 따라 분기:
    - 이미지: MMS (파일 포함) — title/body 허용
    - 장문(90B 초과): MMS (파일 없음, LMS 대용으로 동작) — title 필수
    - 단문(90B 이하): SMS — title 불가

    주의: migration-spec의 "90B 초과 SMS msg는 msghub가 LMS 자동 처리"
    가정은 실제와 다름. 실제로는 "메시지 길이 초과" 에러 발생.
    """
    if msg_type == "image":
        fb = FbInfo(ch="MMS", msg=content, title=subject or "알림")
        if mms_file_id:
            fb.file_id_lst = [mms_file_id]
        return [fb]

    if measure_bytes(content) <= 90:
        return [FbInfo(ch="SMS", msg=content)]

    # 장문: MMS 채널로 title+body 전송 (파일 없음 = LMS 동작)
    # title 없으면 content 앞부분에서 추출하거나 기본값 사용
    fallback_title = subject or (content[:20].strip() or "알림")
    return [FbInfo(ch="MMS", msg=content, title=fallback_title)]


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


async def _dispatch_chat_messages(
    db: Session,
    client: MsghubClient,
    campaign: Campaign,
    callback: str,
    content: str,
    recipients: list[str],
) -> int:
    """양방향 CHAT 발송 (단문 전용, 1건씩 동시 발송).

    RCS 양방향이 콘솔 설정 문제(29003 등)로 실패하면 즉시 SMS로 전환해
    고객에게 메시지가 반드시 도달하도록 한다. 전환된 메시지는 channel=SMS,
    cost=9로 기록되며 사용자가 과금 차이를 확인할 수 있다.

    Returns:
        API 호출 실패 수신자 수 (RCS + SMS 모두 실패한 건수).
    """
    semaphore = asyncio.Semaphore(_CHAT_CONCURRENCY)
    sent_at = _now_iso()

    async def _send_one(
        idx: int, phone: str
    ) -> tuple[int, str, str, SendResponse | None, str | None, str]:
        """returns: (idx, phone, cli_key, resp, err, path)
        path: 'RCS_CHAT' | 'SMS_FALLBACK' | 'FAILED'
        """
        cli_key = _make_cli_key(campaign.id, 0, idx)
        async with semaphore:
            # 1차: RCS 양방향 CHAT (8원)
            try:
                resp = await client.send_rcs_chat(
                    description=content,
                    phone=phone,
                    cli_key=cli_key,
                )
                return idx, phone, cli_key, resp, None, "RCS_CHAT"
            except MsghubBadRequest as exc:
                log.warning(
                    "RCS 양방향 실패 → SMS 전환: cli_key=%s, err=%s",
                    cli_key, exc,
                )
            except (MsghubRateLimited, MsghubServerError) as exc:
                return idx, phone, cli_key, None, str(exc), "FAILED"
            except Exception as exc:
                return idx, phone, cli_key, None, str(exc), "FAILED"

            # 2차: SMS 직접 발송 (9원, -fb cli_key로 중복 방지)
            fb_cli_key = f"{cli_key}-fb"
            try:
                recv = RecvInfo(cli_key=fb_cli_key, phone=phone)
                resp = await client.send_sms(
                    callback=callback, msg=content, recv_list=[recv],
                )
                return idx, phone, fb_cli_key, resp, None, "SMS_FALLBACK"
            except Exception as sms_exc:
                return (
                    idx, phone, cli_key, None,
                    f"RCS+SMS 모두 실패 (SMS: {sms_exc})",
                    "FAILED",
                )

    results = await asyncio.gather(
        *[_send_one(i, p) for i, p in enumerate(recipients)]
    )

    # MsghubRequest + Message 레코드 생성 (가상 청크 단위)
    failed_count = 0
    batch: list[tuple] = list(results)
    chunk_groups = [batch[i : i + CHUNK_SIZE] for i in range(0, len(batch), CHUNK_SIZE)]

    for chunk_idx, group in enumerate(chunk_groups):
        msghub_req = MsghubRequest(
            campaign_id=campaign.id,
            chunk_index=chunk_idx,
            response_code="10000",
            response_message="chat",
            error_body=None,
            sent_at=sent_at,
        )
        db.add(msghub_req)
        db.flush()

        for idx, phone, cli_key, resp, err, path in group:
            # 응답에서 msg_key 추출 (SendResponse.items[0].msg_key)
            msg_key = None
            if resp is not None and hasattr(resp, "items") and resp.items:
                msg_key = resp.items[0].msg_key or None

            if err or path == "FAILED":
                msg = Message(
                    campaign_id=campaign.id,
                    msghub_request_id=msghub_req.id,
                    to_number=phone,
                    to_number_raw=phone,
                    cli_key=cli_key,
                    status="FAILED",
                    result_desc=err or "알 수 없는 실패",
                )
                failed_count += 1
            elif path == "SMS_FALLBACK":
                # RCS 실패 후 SMS로 전환됨. 리포트 웹훅 오면 확정되지만
                # UI에서 즉시 "SMS로 전환" 상태가 보이도록 미리 기록.
                msg = Message(
                    campaign_id=campaign.id,
                    msghub_request_id=msghub_req.id,
                    to_number=phone,
                    to_number_raw=phone,
                    cli_key=cli_key,
                    msg_key=msg_key,
                    status="REG",
                    channel="SMS",
                    product_code="SMS",
                    result_desc="RCS 양방향 실패 → SMS 자동 전환",
                )
            else:
                msg = Message(
                    campaign_id=campaign.id,
                    msghub_request_id=msghub_req.id,
                    to_number=phone,
                    to_number_raw=phone,
                    cli_key=cli_key,
                    msg_key=msg_key,
                    status="REG",
                )
            db.add(msg)

        db.flush()
        db.commit()

    return failed_count


async def _dispatch_rcs_chunks(
    db: Session,
    client: MsghubClient,
    campaign: Campaign,
    callback: str,
    content: str,
    subject: str | None,
    recipients: list[str],
    msg_type: str,
    messagebase_id: str,
    mms_file_id: str | None,
    rcs_file_id: str | None,
    is_reserved: bool,
    reserve_utc_iso: str | None,
    msghub_reserve_time: str | None,
) -> tuple[list[int], list[int]]:
    """단방향 RCS + fbInfoLst 청크 발송 (장문/이미지).

    Returns:
        (failed_chunk_indices, failed_chunk_sizes)
    """
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

            resp = await client.send_rcs(
                messagebase_id=messagebase_id,
                callback=callback,
                recv_list=recv_list,
                fb_info_lst=fb_info_lst,
                resv_yn="Y" if is_reserved else None,
                resv_req_dt=msghub_reserve_time,
            )

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

            _create_messages_from_response(
                db, campaign.id, msghub_req.id, resp, chunk, chunk_idx
            )
            db.flush()
            db.commit()

        except MsghubRateLimited:
            db.rollback()
            await asyncio.sleep(30)
            sent_at = _now_iso()
            try:
                resp = await _send_chunk_direct(
                    client, campaign, callback, content,
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
            # RCS 설정 문제(29003 등)로 즉시 실패 → 직접 SMS/LMS/MMS로 전환
            log.warning(
                "RCS 단방향 실패 → %s 직접 발송 전환: chunk=%d, err=%s",
                msg_type.upper(), chunk_idx, exc,
            )
            db.rollback()
            sent_at = _now_iso()
            try:
                resp = await _send_chunk_direct(
                    client, campaign, callback, content,
                    subject, chunk, chunk_idx, msg_type, mms_file_id,
                )
                msghub_req = MsghubRequest(
                    campaign_id=campaign.id,
                    chunk_index=chunk_idx,
                    response_code=resp.code,
                    response_message=f"RCS 실패 → 직접 발송: {resp.message}",
                    error_body=None,
                    sent_at=sent_at,
                )
                db.add(msghub_req)
                db.flush()
                _create_messages_from_response(
                    db, campaign.id, msghub_req.id, resp, chunk, chunk_idx,
                )
                db.flush()
                db.commit()
            except Exception as retry_exc:
                db.rollback()
                _record_failed_chunk(
                    db, campaign.id, chunk_idx, chunk, sent_at,
                    f"RCS: {exc} / 직접 발송: {retry_exc}",
                )
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

    return failed_chunks, failed_chunk_sizes


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

    단문(short): RCS 양방향 CHAT (8원) — fbInfoLst 미지원이므로
    RCS 실패 시 report.py/webhook.py에서 SMS 수동 fallback.
    장문/이미지: RCS 단방향 + fbInfoLst (자동 fallback, 동일 단가).
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
    # 단문: 양방향 CHAT (8원). 단, 예약 발송은 양방향 미지원이므로 단방향 fallback.
    is_chat = msg_type == "short" and not is_reserved
    messagebase_id = "RPCSAXX001" if is_chat else (_MESSAGEBASE_MAP.get(msg_type) or "RPSSAXX001")

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

    # 4. 발송
    if is_chat:
        # 양방향 CHAT (단문 8원) — 1건씩 동시 발송, fallback은 webhook에서 처리
        failed_recipients = await _dispatch_chat_messages(
            db, msghub_client, campaign, caller_number, content, recipients,
        )
        failed_chunks: list[int] = []
        failed_chunk_sizes: list[int] = [failed_recipients] if failed_recipients else []
        chunks = [recipients]  # 가상 청크 1개 (audit 로그용)
    else:
        # 단방향 RCS + fbInfoLst (장문/이미지)
        failed_chunks, failed_chunk_sizes = await _dispatch_rcs_chunks(
            db, msghub_client, campaign, caller_number, content, subject,
            recipients, msg_type, messagebase_id, mms_file_id, rcs_file_id,
            is_reserved, reserve_utc_iso, msghub_reserve_time,
        )
        chunks = [recipients[i : i + CHUNK_SIZE] for i in range(0, len(recipients), CHUNK_SIZE)]

    # 5. Campaign state + counters 업데이트
    # CHAT 경로는 failed_chunks가 항상 빈 리스트(가상 청크 1개)라서 청크 기반
    # 판정을 쓰면 부분/전원 실패도 DISPATCHED로 잘못 들어간다. 수신자 수 기반으로 판정.
    total_chunks = len(chunks)
    failed_recipients = sum(failed_chunk_sizes)
    total_recipients = len(recipients)

    if failed_recipients == 0:
        campaign.state = "RESERVED" if is_reserved else "DISPATCHED"
    elif failed_recipients == total_recipients:
        campaign.state = "RESERVE_FAILED" if is_reserved else "FAILED"
    else:
        campaign.state = "PARTIAL_FAILED"

    campaign.fail_count = failed_recipients
    campaign.pending_count = max(0, total_recipients - failed_recipients)

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
    """RCS 실패 시 직접 SMS/LMS/MMS 발송 (재시도 fallback).

    cliKey 10분 중복 금지 규칙을 피하기 위해 원본 키에 -fb 접미사를 붙인다.
    """
    recv_list = [
        RecvInfo(
            cli_key=f"{_make_cli_key(campaign.id, chunk_idx, i)}-fb",
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
