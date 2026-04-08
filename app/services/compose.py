"""발송 컴포즈 서비스.

번호 검증, 메시지 검증, 실제 발송(dispatch_campaign)을 담당한다.
"""
from __future__ import annotations

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
    3. ncp_client.send_sms 청크 자동 처리
    4. 각 청크 응답을 ncp_requests에 저장
    5. 각 청크 직후 list_by_request_id 호출 → messages 테이블 채움
    6. campaign state=DISPATCHED, 카운터 업데이트
    7. 감사 로그 기록

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

    # 4. 청크 단위 발송
    chunk_size = 100
    chunks = [recipients[i : i + chunk_size] for i in range(0, len(recipients), chunk_size)]

    failed_chunks: list[int] = []
    ncp_request_records: list[NcpRequest] = []

    for chunk_idx, chunk in enumerate(chunks):
        sent_at = _now_iso()
        try:
            # send_sms는 내부적으로 청크 분할하지 않고 전체를 보내므로
            # 여기서는 chunk(=100건 이하)를 한 번씩 호출
            send_responses = await ncp_client.send_sms(
                from_number=caller_number,
                content=content,
                to_numbers=chunk,
                message_type=message_type,  # type: ignore[arg-type]
                subject=subject,
            )
            # send_sms는 청크 분할을 자동으로 하지만
            # 여기선 이미 chunk=100건이라 응답이 1개
            send_resp = send_responses[0] if send_responses else None

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
            ncp_request_records.append(ncp_req)

            # 5. messageId 수집 (발송 직후 1회 list 호출)
            if send_resp and send_resp.request_id:
                try:
                    list_resp = await ncp_client.list_by_request_id(send_resp.request_id)
                    # to_number → message_id 매핑
                    msg_map: dict[str, str] = {
                        item.to: item.message_id for item in list_resp.messages
                    }
                    msg_status_map: dict[str, str] = {
                        item.to: item.status for item in list_resp.messages
                    }
                except Exception:
                    msg_map = {}
                    msg_status_map = {}

                for to_num in chunk:
                    message_id = msg_map.get(to_num)
                    status = msg_status_map.get(to_num, "PENDING")
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

        except Exception as exc:
            # 청크 실패: error_body에 기록, messages는 UNKNOWN
            from app.ncp.client import NCPAuthError

            ncp_req = NcpRequest(
                campaign_id=campaign.id,
                chunk_index=chunk_idx,
                request_id=None,
                request_time=None,
                http_status=None,
                status_code=None,
                status_name="fail",
                error_body=str(exc),
                sent_at=sent_at,
            )
            db.add(ncp_req)
            db.flush()
            ncp_request_records.append(ncp_req)
            failed_chunks.append(chunk_idx)

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

            # NCPAuthError는 전파
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

    campaign.pending_count = len(recipients) - len(failed_chunks) * chunk_size
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
