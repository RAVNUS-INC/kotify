"""발송 컴포즈 서비스.

번호 검증, 메시지 검증, 실제 발송(dispatch_campaign)을 담당한다.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Caller, Campaign, Message, NcpRequest
from app.services import audit
from app.util.phone import parse_phone_list
from app.util.text import classify_message_type, measure_bytes

if TYPE_CHECKING:
    from app.ncp.client import NCPClient


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


async def dispatch_campaign(
    db: Session,
    ncp_client: "NCPClient",
    created_by: str,
    caller_number: str,
    content: str,
    recipients: list[str],
    message_type: str,
    subject: str | None = None,
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

    # 3. Campaign 생성 (DISPATCHING)
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
        state="DISPATCHING",
        created_at=now,
        completed_at=None,
    )
    db.add(campaign)
    db.flush()  # campaign.id 확보
    db.commit()  # Campaign을 먼저 커밋 (청크 실패 시에도 Campaign 기록 유지)

    # 4. 청크 단위 발송 — dispatch_campaign이 청크 분할 전담 (#2)
    chunks = [recipients[i : i + CHUNK_SIZE] for i in range(0, len(recipients), CHUNK_SIZE)]

    failed_chunks: list[int] = []
    failed_chunk_sizes: list[int] = []

    for chunk_idx, chunk in enumerate(chunks):
        sent_at = _now_iso()
        try:
            # send_sms는 단일 청크(≤100건)만 처리 (#2)
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

            # 5. messageId 수집 (발송 직후 1회 list 호출)
            if send_resp and send_resp.request_id:
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

        except NCPRateLimited as exc:
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
    total_chunks = len(chunks)
    if len(failed_chunks) == 0:
        campaign.state = "DISPATCHED"
    elif len(failed_chunks) == total_chunks:
        campaign.state = "FAILED"
    else:
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
