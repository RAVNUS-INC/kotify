"""발송 컴포즈 서비스.

번호 검증, 메시지 검증, 실제 발송(dispatch_campaign)을 담당한다.
msghub RCS 우선 발송 + SMS/LMS/MMS fallback (fbInfoLst).
"""
from __future__ import annotations

import asyncio
import logging
import secrets
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
from app.services.report import _refresh_campaign_counters, awaiting_record
from app.util.phone import normalize_phone, parse_phone_list
from app.util.text import classify_message_type, measure_bytes
from app.util.time import parse_mixed_ts

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

# 청크를 보내는 중인 캠페인 id. 캠페인은 첫 청크 전에 RESERVED 로 커밋돼 목록에서 취소할 수
# 있는데, 그때 취소가 끼면 이미 접수된 청크 행만 보고 전체 취소로 마무리해 뒤 청크가 예약
# 시각에 발송된다. 단일 uvicorn 워커 전제(deploy/kotify.service --workers 1, events·reconcile 과
# 같음)라 프로세스 메모리로 충분하다 — 재시작하면 진행 중이던 발송도 함께 끝났다.
_dispatching: set[int] = set()


def is_dispatching(campaign_id: int) -> bool:
    """이 캠페인의 청크 발송(예약 접수)이 아직 진행 중인가."""
    return campaign_id in _dispatching


def dedupe_recipients(recipients: list[str]) -> list[str]:
    """수신자 중복 제거 — 순서 보존 (C2).

    동일 번호가 여러 번 입력돼도(엑셀 복붙 등) 1건만 발송하여
    중복 발송·이중 과금을 방지한다. dict.fromkeys 로 첫 등장 순서를 유지한다.

    주의: 문자열 동일성 기준이다. "010-1234-5678" 과 "01012345678" 은
    서로 다른 문자열이라 별개로 취급된다. 저장 시 to_number 는
    _norm_to_number 로 숫자만 통일하지만(대화방 그룹핑 키), dedupe 는 사용자
    입력 원본 기준이라 여기선 정규화하지 않는다.
    """
    return list(dict.fromkeys(recipients))


def _norm_to_number(phone: str) -> str:
    """messages.to_number(그룹핑·매칭 키)용 정규화 — 숫자만 남긴다.

    대화방은 (caller, phone) 이 아니라 phone 단위로 묶이며, MO.mo_number 는
    webhook 에서 숫자만 저장된다. 발송(MT) to_number 도 숫자만으로 통일해야
    같은 고객의 발송·회신이 한 대화방으로 병합된다(하이픈 유무로 갈리지 않게).
    휴대폰 패턴이 아니면 normalize_phone 이 None 이라, 숫자만 추출로 fallback.
    to_number_raw 에는 원본을 그대로 보존한다(감사·표시 원본).
    """
    return normalize_phone(phone) or "".join(c for c in (phone or "") if c.isdigit())

# 예약 발송 최소 리드타임 (10분)
RESERVE_MIN_LEAD_SECONDS = 10 * 60
RESERVE_MAX_AHEAD = 30 * 24 * 60 * 60

# 메시지 유형 → 채널 중립 유형
_MSG_TYPE_MAP = {"SMS": "short", "LMS": "long", "MMS": "image"}

# 메시지 유형 → RCS messagebaseId (v11 통합 RCS, 모두 단방향 엔드포인트)
# 참조: claudedocs/msghub-api-guide.md §6, 공식 스펙 "2.3.2 통합 RCS 메시지 §1"
#
# 단가는 webhook 리포트의 (channel, productCode) 로 calculate_cost 가 결정한다.
# short: RPSSAXX001 — 통합 RCS SMS형, RCS 도달 17원 / SMS fallback 9원
# long:  RPLSAXX001 — 통합 RCS LMS형, 27원 (RCS=LMS fallback 동일)
# image: RPMSMMX001 — 통합 RCS MMS형, productCode=MMS=85원 / MMS fallback 85원
#
# 주의: RPCSAXX001(양방향 CHAT, 8원)은 /rcs/bi/v1.1 엔드포인트 전용으로
# msghub 문서 §2("RCS 양방향 응답메시지를 발송합니다")에 따르면 고객의
# MO 수신에 대한 응답 발송에만 사용 가능. outbound 브로드캐스트에 사용
# 시 replyId(사전등록 응답 템플릿 ID)가 없어 29003/404로 거부된다.
# outbound 단문은 단방향 SMS형(RPSSAXX001, RCS 도달 시 17원)을 사용해야 한다.
_MESSAGEBASE_MAP = {
    "short": "RPSSAXX001",   # 통합 RCS SMS형 (단방향)
    "long": "RPLSAXX001",    # 통합 RCS LMS형 (단방향)
    "image": "RPMSMMX001",   # 통합 RCS MMS M형 (이미지 중심)
}


def _classify_msg_type(content: str, has_attachment: bool) -> str:
    """메시지 내용과 첨부 여부로 채널 중립 유형 결정."""
    # 이미지가 있어도 본문 인코딩·길이 제한은 동일하다.
    legacy = classify_message_type(content)
    if has_attachment:
        return "image"
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
    if (utc_dt - now_utc).total_seconds() > RESERVE_MAX_AHEAD:
        raise ValueError("예약 시각은 현재로부터 최대 30일 이내여야 합니다.")

    msghub_format = local_dt.strftime("%Y-%m-%d %H:%M")
    return msghub_format, utc_dt.isoformat()


def _make_cli_key(campaign_id: int, chunk_idx: int, recipient_idx: int) -> str:
    """cliKey 생성. 패턴: c{campaign_id}-{chunk}-{idx}"""
    return f"c{campaign_id}-{chunk_idx}-{recipient_idx}"


def _reservation_id(resp: SendResponse | ReserveResponse | None) -> str | None:
    """예약 접수 응답의 webReqId. 즉시 발송 응답이거나 값이 비었으면 None."""
    if isinstance(resp, ReserveResponse) and resp.web_req_id:
        return resp.web_req_id
    return None


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
) -> tuple[list[int], list[int], int]:
    """단방향 RCS + fbInfoLst 청크 발송 (장문/이미지).

    Returns:
        (failed_chunk_indices, failed_chunk_sizes, item_failed)
        item_failed 는 청크 전송은 성공(HTTP 200)했으나 응답 내 item 단위로
        실패한 수신자 수 — 청크 전체 실패(failed_chunk_sizes)와 서로소다 (H1).
    """
    chunks = [recipients[i : i + CHUNK_SIZE] for i in range(0, len(recipients), CHUNK_SIZE)]
    failed_chunks: list[int] = []
    failed_chunk_sizes: list[int] = []
    item_failed = 0

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
                web_req_id=_reservation_id(resp),
            )
            db.add(msghub_req)
            db.flush()

            _, n_failed = _create_messages_from_response(
                db, campaign.id, msghub_req.id, resp, chunk, chunk_idx
            )
            item_failed += n_failed
            db.flush()
            db.commit()

        except MsghubRateLimited:
            # 29002(CPS 초과)는 요청 단위 레이트리밋이다 — CPS=Calls Per Second 는
            # 수신자가 아닌 API 호출 단위 한도. 공식 스펙상 29002 는 HTTP 400 최상위
            # code 로, _raise_for_response 가 body["code"](요청 결과)만 보고 raise 한다.
            # 즉 요청 전체가 ingress 에서 거부돼 접수된 수신자가 0이므로, 아래 -fb 직접
            # 재발송이 이미 접수된 수신자에게 중복 발송할 일이 없다(부분수락은 HTTP 200 +
            # data[].code 경로 — 여기와 무관). 검증: claudedocs/review/c3-verification.md
            db.rollback()
            await asyncio.sleep(30)
            sent_at = reserve_utc_iso if is_reserved else _now_iso()
            try:
                resp = await _send_chunk_direct(
                    client, campaign, callback, content,
                    subject, chunk, chunk_idx, msg_type, mms_file_id,
                    is_reserved, msghub_reserve_time,
                )
                msghub_req = MsghubRequest(
                    campaign_id=campaign.id,
                    chunk_index=chunk_idx,
                    response_code=resp.code,
                    response_message=resp.message,
                    error_body=None,
                    sent_at=sent_at,
                    web_req_id=_reservation_id(resp),
                )
                db.add(msghub_req)
                db.flush()
                _, n_failed = _create_messages_from_response(
                    db, campaign.id, msghub_req.id, resp, chunk, chunk_idx, fallback=True,
                )
                item_failed += n_failed
                db.flush()
                db.commit()
            except Exception as retry_exc:
                db.rollback()
                _record_failed_chunk(
                    db, campaign.id, chunk_idx, chunk, sent_at, str(retry_exc), cli_key_suffix="-fb",
                    rejection_code=_explicit_rejection_code(retry_exc),
                )
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
            sent_at = reserve_utc_iso if is_reserved else _now_iso()
            try:
                resp = await _send_chunk_direct(
                    client, campaign, callback, content,
                    subject, chunk, chunk_idx, msg_type, mms_file_id,
                    is_reserved, msghub_reserve_time,
                )
                msghub_req = MsghubRequest(
                    campaign_id=campaign.id,
                    chunk_index=chunk_idx,
                    response_code=resp.code,
                    response_message=f"RCS 실패 → 직접 발송: {resp.message}",
                    error_body=None,
                    sent_at=sent_at,
                    web_req_id=_reservation_id(resp),
                )
                db.add(msghub_req)
                db.flush()
                _, n_failed = _create_messages_from_response(
                    db, campaign.id, msghub_req.id, resp, chunk, chunk_idx, fallback=True,
                )
                item_failed += n_failed
                db.flush()
                db.commit()
            except Exception as retry_exc:
                db.rollback()
                _record_failed_chunk(
                    db, campaign.id, chunk_idx, chunk, sent_at,
                    f"RCS: {exc} / 직접 발송: {retry_exc}", cli_key_suffix="-fb",
                    rejection_code=_explicit_rejection_code(retry_exc),
                )
                db.commit()
                failed_chunks.append(chunk_idx)
                failed_chunk_sizes.append(len(chunk))

        except MsghubAuthError as exc:
            db.rollback()
            _record_failed_chunk(
                db, campaign.id, chunk_idx, chunk, sent_at, "인증 오류",
                rejection_code=_explicit_rejection_code(exc),
            )
            db.commit()
            raise

        except (MsghubServerError, MsghubError, Exception) as exc:
            db.rollback()
            _record_failed_chunk(
                db, campaign.id, chunk_idx, chunk, sent_at, str(exc),
                rejection_code=_explicit_rejection_code(exc),
            )
            db.commit()
            failed_chunks.append(chunk_idx)
            failed_chunk_sizes.append(len(chunk))

    return failed_chunks, failed_chunk_sizes, item_failed


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
    idempotency_key: str | None = None,
    send_channel: str = "rcs",
) -> Campaign:
    """캠페인을 생성하고 msghub를 통해 발송한다.

    send_channel 로 전송 방식을 선택한다 (하위 유형은 content/첨부로 자동 분류):
    - "rcs" (기본): 통합 RCS 단방향(/rcs/v1.1) + fbInfoLst 자동 fallback.
        short RPSSAXX001(RCS 17 / SMS fallback 9), long RPLSAXX001(27),
        image RPMSMMX001(MMS 85).
    - "sms" (일반): RCS 미사용, 직접 SMS/LMS/MMS 발송.
        short SMS(9), long LMS(27), image MMS(85).

    단가는 webhook 리포트의 (channel, productCode) 로 calculate_cost 가 확정한다.
    """
    # 0. 수신자 중복 제거 (C2) — 한도 판정 전에 수행해 실제 발송 건수 기준으로 검증.
    original_count = len(recipients)
    recipients = dedupe_recipients(recipients)
    deduped_count = original_count - len(recipients)

    # 0.1 수신자 수 제한 (중복 제거 후 기준)
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
        # 공급자 컨텐츠는 채널별 fileId가 다르다. 구버전 첨부는 MMS ID만
        # 있으므로 RCS 발송을 거부해 잘못된 채널 ID를 보내지 않는다.
        rcs_file_id = attachment.msghub_rcs_file_id
        mms_file_id = attachment.msghub_file_id
        if send_channel != "sms" and not rcs_file_id:
            raise ValueError("RCS용 첨부 파일이 등록되지 않았습니다. 이미지를 다시 업로드해주세요.")
        use_at = parse_mixed_ts(reserve_utc_iso) if reserve_utc_iso else datetime.now(UTC)
        expiries = [("MMS", attachment.file_expires_at)]
        if send_channel != "sms":
            expiries.append(("RCS", attachment.rcs_file_expires_at))
        for channel_name, expiry in expiries:
            expires_at = parse_mixed_ts(expiry)
            if expiry and expires_at is None:
                raise ValueError(f"{channel_name} 첨부 파일 만료 시각을 확인할 수 없습니다. 다시 업로드해주세요.")
            if expires_at is not None and use_at is not None and expires_at <= use_at:
                raise ValueError(
                    f"{channel_name} 첨부 파일이 발송 시각 전에 만료됩니다. 이미지를 다시 업로드해주세요."
                )

    # 1. 발신번호 검증
    caller = db.execute(
        select(Caller).where(Caller.number == caller_number, Caller.active == 1)
    ).scalar_one_or_none()
    if caller is None:
        raise ValueError(f"발신번호 '{caller_number}'가 활성 목록에 없습니다.")

    # 2. messagebaseId 결정 — RCS 모드만. 일반(sms) 모드는 RCS 미사용이라 None.
    is_rcs = send_channel != "sms"
    messagebase_id = (_MESSAGEBASE_MAP.get(msg_type) or "RPSSAXX001") if is_rcs else None

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
        idempotency_key=idempotency_key,
    )
    db.add(campaign)
    db.flush()

    if attachment is not None:
        attachment.campaign_id = campaign.id
        db.flush()

    db.commit()

    # 4. 발송 — RCS 우선(+fallback) 또는 일반 직접(SMS/LMS/MMS).
    # 청크를 보내는 동안은 진행 중으로 표시한다(취소 라우트가 기다리게). 5·6 단계엔 await 가
    # 없어 표시를 푼 뒤 마지막 커밋 전에 다른 요청이 끼어들지 않는다.
    # 청크 응답을 받아 행을 기록하기 전에 온 리포트는 msghub 재전송으로 받는다 (report.awaiting_record).
    _dispatching.add(campaign.id)
    try:
        with awaiting_record([campaign.id]):
            if is_rcs:
                failed_chunks, failed_chunk_sizes, item_failed = await _dispatch_rcs_chunks(
                    db, msghub_client, campaign, caller_number, content, subject,
                    recipients, msg_type, messagebase_id, mms_file_id, rcs_file_id,
                    is_reserved, reserve_utc_iso, msghub_reserve_time,
                )
            else:
                failed_chunks, failed_chunk_sizes, item_failed = await _dispatch_direct_chunks(
                    db, msghub_client, campaign, caller_number, content, subject,
                    recipients, msg_type, mms_file_id,
                    is_reserved, reserve_utc_iso, msghub_reserve_time,
                )
    finally:
        _dispatching.discard(campaign.id)
    chunks = [recipients[i : i + CHUNK_SIZE] for i in range(0, len(recipients), CHUNK_SIZE)]

    # 5. Campaign state + counters 업데이트 — 수신자 수 기반 판정.
    # 청크 전체 실패(failed_chunk_sizes)뿐 아니라 HTTP 200 응답 내 item 단위
    # 실패(item_failed)도 합산해야 웹훅 도착 전에도 fail_count 가 정확하다 (H1).
    total_chunks = len(chunks)
    failed_recipients = sum(failed_chunk_sizes) + item_failed
    total_recipients = len(recipients)

    if failed_recipients == 0:
        campaign.state = "RESERVED" if is_reserved else "DISPATCHED"
    elif failed_recipients == total_recipients:
        campaign.state = "RESERVE_FAILED" if is_reserved else "FAILED"
    else:
        campaign.state = "PARTIAL_FAILED"

    campaign.fail_count = failed_recipients
    campaign.pending_count = max(0, total_recipients - failed_recipients)
    if campaign.pending_count == 0:
        # 전건 실패로 결과가 정해진 시각. 뒤에 리포트로 state 가 바뀌어도 유지된다 — 알림센터의
        # 정렬·읽음 기준이라 그때 처음 찍으면 읽은 알림이 다시 뜬다 (report._refresh_campaign_counters).
        campaign.completed_at = _now_iso()

    db.flush()

    # 요청 예외로 실패 기록한 청크도 msghub 가 실제로 접수했다면 리포트가 오고, 그 행에 매칭되면 state 는
    # 리포트 집계를 따른다. 뒤 청크를 보내는 사이 이미 처리된 앞 청크 리포트는 위 판정(발송 결과만 셈)이
    # 덮었으므로 다시 집계한다 — 뒤이어 올 리포트가 없으면 덮인 채로 남는다. 응답을 기다리는 동안(행을
    # 기록하기 전) 온 리포트는 msghub 재전송으로 받고(4단계), 재전송마저 오지 않으면 재조정이 그 행을 msghub 에
    # 조회해 확정한다 (services.reconcile).
    has_report = db.execute(
        select(Message.id).where(Message.campaign_id == campaign.id, Message.status == "DONE").limit(1)
    ).first()
    if has_report is not None:
        _refresh_campaign_counters(db, campaign.id)

    # 6. 감사 로그
    audit.log(
        db,
        actor_sub=created_by,
        action=audit.SEND,
        target=f"campaign:{campaign.id}",
        detail={
            "total": len(recipients),
            "deduped": deduped_count,
            "chunks": total_chunks,
            "failed_chunks": failed_chunks,
            "message_type": msg_type,
            "rcs_messagebase_id": messagebase_id,
        },
    )

    db.commit()
    return campaign


class ChatReplyRejected(Exception):
    """양방향 답장이 명시적으로 접수 거부됨. 단방향 대체를 시도해도 중복되지 않는다."""


class ReplySendFailed(Exception):
    """답장 접수 실패. 미확정 요청은 저장된 campaign_id 로 결과를 추적한다."""

    def __init__(self, campaign_id: int, *, uncertain: bool = False) -> None:
        self.campaign_id = campaign_id
        self.uncertain = uncertain
        self.code = "send_status_unknown" if uncertain else "send_failed"
        message = (
            "접수 여부를 확인 중입니다. 재발송 전에 대화방의 전송 결과를 확인해 주세요."
            if uncertain else
            "답장이 접수되지 않았습니다. 전송 결과를 확인한 뒤 다시 시도해 주세요."
        )
        super().__init__(message)


def _make_chat_reply_cli_key(campaign_id: int) -> str:
    """양방향 답장 cliKey. 패턴: c{campaign_id}-0-0-{시도 토큰 hex 6자}

    답장 캠페인은 커밋하지 않고 보낸 뒤 명시 거부되면 롤백한다(dispatch_chat_reply). SQLite 는 롤백된 id 를 다음 캠페인에
    다시 준다 — campaigns.id 에 AUTOINCREMENT 가 없고(alembic 0001), 있어도 sqlite_sequence 갱신이 함께 롤백된다.
    거부된 시도와 그 id 를 받은 단방향 fallback(chat.send_reply)의 키가 겹치지 않도록 시도 토큰을 붙인다.
    응답 타임아웃 등 접수 여부가 불명확한 시도는 실제 cliKey 를 기록하고 즉시 대체하지 않는다.

    양방향 cliKey 는 최대 20자(공식 문서 2.3.2 §2 — 단방향·xMS 는 30자)라 캠페인 id 8자리까지 들어간다. 대체 SMS 는
    -fb 를 붙인다(report.send_sms_fallback).
    """
    return f"{_make_cli_key(campaign_id, 0, 0)}-{secrets.token_hex(3)}"


async def dispatch_chat_reply(
    db: Session,
    msghub_client: MsghubClient,
    created_by: str,
    caller_number: str,
    content: str,
    phone: str,
    reply_id: str,
) -> Campaign:
    """RCS 양방향(CHAT, 8원) 단건 응답 발송 — 고객 MO 에 대한 답장 전용.

    reply_id 는 고객 MO 의 응답 템플릿 ID(MoMessage.reply_id). 양방향은 단건이라
    청크가 없다. 명시적 요청·수신자 거부는 미커밋 Campaign 을 rollback 으로 폐기하고
    ChatReplyRejected 를 던져 호출자가 단방향으로 대체한다. 타임아웃·서버 오류처럼 접수
    여부를 모르면 실제 cliKey 를 FAILED/result_code=None 으로 보존해 리포트·재조정으로
    확인한다. 즉시 대체하면 이미 접수된 답장이 중복 전달될 수 있다.

    주의: 양방향 응답 data 에는 phone 이 없어(cliKey/msgKey/replyId 만) Message 는
    아는 phone 으로 직접 만든다 — _create_messages_from_response(item.phone 의존) 미사용.
    """
    caller = db.execute(
        select(Caller).where(Caller.number == caller_number, Caller.active == 1)
    ).scalar_one_or_none()
    if caller is None:
        raise ValueError(f"발신번호 '{caller_number}'가 활성 목록에 없습니다.")

    now = _now_iso()
    campaign = Campaign(
        created_by=created_by,
        caller_number=caller_number,
        message_type="short",
        subject=None,
        content=content,
        total_count=1,
        ok_count=0,
        fail_count=0,
        pending_count=1,
        state="DISPATCHING",
        created_at=now,
        completed_at=None,
        reserve_time=None,
        rcs_messagebase_id="RPCSAXX001",  # 양방향 CHAT (8원)
        web_req_id=None,
        total_cost=0,
        rcs_count=0,
        fallback_count=0,
        idempotency_key=None,
    )
    db.add(campaign)
    db.flush()  # id 할당 (명시 거부일 때만 rollback 으로 폐기)

    cli_key = _make_chat_reply_cli_key(campaign.id)
    # 답장 행을 커밋하기 전에 온 리포트는 msghub 재전송으로 받는다 (report.awaiting_record).
    with awaiting_record([campaign.id]):
        try:
            resp = await msghub_client.send_rcs_chat(
                description=content, phone=phone, cli_key=cli_key, reply_id=reply_id,
            )
            item = resp.items[0] if resp.items else None
            code = item.code if item else resp.code
            if not code or (item is not None and item.cli_key != cli_key):
                raise MsghubServerError("양방향 접수 응답을 확인할 수 없습니다", code="PARSE_ERROR")
        except Exception as exc:
            response_rejected = _explicit_rejection_code(exc) or (
                isinstance(exc, (MsghubBadRequest, MsghubAuthError, MsghubRateLimited))
                and exc.status_code == 200
                and exc.code
                and exc.code != SUCCESS_CODE
            )
            if response_rejected or (
                isinstance(exc, MsghubError) and exc.code == "CONFIG_ERROR"
            ):
                # HTTP 200 에도 최상위 결과 코드가 거부면 클라이언트가 위 예외를
                # 던진다. 서버·파싱 오류와 구분하며 예약 청크의 판정은 바꾸지 않는다.
                # CONFIG_ERROR 는 클라이언트가 HTTP 요청 전에 거부한 경우다.
                db.rollback()
                raise ChatReplyRejected(str(exc)) from exc

            # 네트워크·서버·파싱 오류는 공급자가 접수했을 수 있다. 실제 시도 키를
            # 보존해 웹훅과 재조정이 같은 단일 메시지를 확정하게 한다.
            _record_failed_chunk(
                db, campaign.id, 0, [phone], now, str(exc),
                cli_key_suffix=cli_key.removeprefix(_make_cli_key(campaign.id, 0, 0)),
            )
            campaign.fail_count = 1
            campaign.pending_count = 0
            campaign.state = "FAILED"
            campaign.completed_at = _now_iso()
            audit.log(
                db, actor_sub=created_by, action=audit.SEND, target=f"campaign:{campaign.id}",
                detail={"total": 1, "channel": "chat", "acceptance": "unknown"},
            )
            db.commit()
            raise ReplySendFailed(campaign.id, uncertain=True) from exc

        if code != SUCCESS_CODE:
            # 최상위 10000 도 수신자별 접수를 보장하지 않는다. 명시 거부는
            # 커밋 전에 폐기해야 같은 답장에 실패/대체 말풍선이 두 개 남지 않는다.
            db.rollback()
            raise ChatReplyRejected(f"[{code}] {item.message if item else resp.message}")

        msghub_req = MsghubRequest(
            campaign_id=campaign.id,
            chunk_index=0,
            response_code=resp.code,
            response_message=resp.message,
            error_body=None,
            sent_at=now,
        )
        db.add(msghub_req)
        db.flush()

        db.add(Message(
            campaign_id=campaign.id,
            msghub_request_id=msghub_req.id,
            to_number=_norm_to_number(phone),
            to_number_raw=phone,
            cli_key=cli_key,
            msg_key=item.msg_key if item else None,
            status="REG",
            result_code=code,
            result_desc=item.message if item else resp.message,
        ))
        campaign.fail_count = 0
        campaign.pending_count = 1
        campaign.state = "DISPATCHED"
        db.flush()

        audit.log(
            db,
            actor_sub=created_by,
            action=audit.SEND,
            target=f"campaign:{campaign.id}",
            detail={"total": 1, "channel": "chat", "reply_id": reply_id},
        )
        db.commit()
    return campaign


def _fallback_cli_key(campaign_id: int, chunk_idx: int, recipient_idx: int) -> str:
    """RCS 요청이 거부돼 직접 발송하는 청크의 cliKey — 원본 키 10분 중복 금지를 피한다."""
    return f"{_make_cli_key(campaign_id, chunk_idx, recipient_idx)}-fb"


async def _send_chunk_direct(
    client: MsghubClient,
    campaign: Campaign,
    callback: str,
    content: str,
    subject: str | None,
    chunk: list[str],
    chunk_idx: int,
    msg_type: str,
    mms_file_id: str | None,
    is_reserved: bool,
    msghub_reserve_time: str | None,
) -> SendResponse | ReserveResponse:
    """RCS 실패 시 직접 SMS/LMS/MMS 발송 (재시도 fallback).

    cliKey 만 -fb 키로 바꾸고 발송은 _send_direct 에 맡긴다. 예전엔 따로 호출해 예약
    파라미터가 빠져, 예약 캠페인의 이 청크만 예약 시각을 무시하고 즉시 발송됐다.
    """
    recv_list = [
        RecvInfo(cli_key=_fallback_cli_key(campaign.id, chunk_idx, i), phone=phone)
        for i, phone in enumerate(chunk)
    ]
    return await _send_direct(
        client, callback, content, subject, recv_list,
        msg_type, mms_file_id, is_reserved, msghub_reserve_time,
    )


async def _send_direct(
    client: MsghubClient,
    callback: str,
    content: str,
    subject: str | None,
    recv_list: list[RecvInfo],
    msg_type: str,
    mms_file_id: str | None,
    is_reserved: bool,
    msghub_reserve_time: str | None,
) -> SendResponse | ReserveResponse:
    """직접 발송 — short→SMS, long→LMS, image→MMS (예약 지원).

    전달받은 recv_list 의 cliKey 를 그대로 쓴다. 일반 모드 1차 발송은 정상 키로, RCS
    fallback(_send_chunk_direct)은 -fb 키로 만들어 넘긴다.
    """
    resv_yn = "Y" if is_reserved else None
    if msg_type == "short":
        return await client.send_sms(
            callback=callback,
            msg=content,
            recv_list=recv_list,
            resv_yn=resv_yn,
            resv_req_dt=msghub_reserve_time,
        )
    # long → LMS(파일 없음), image → MMS(파일 있음)
    return await client.send_mms(
        callback=callback,
        title=subject or "",
        msg=content,
        recv_list=recv_list,
        file_id_lst=[mms_file_id] if mms_file_id else None,
        resv_yn=resv_yn,
        resv_req_dt=msghub_reserve_time,
    )


async def _dispatch_direct_chunks(
    db: Session,
    client: MsghubClient,
    campaign: Campaign,
    callback: str,
    content: str,
    subject: str | None,
    recipients: list[str],
    msg_type: str,
    mms_file_id: str | None,
    is_reserved: bool,
    reserve_utc_iso: str | None,
    msghub_reserve_time: str | None,
) -> tuple[list[int], list[int], int]:
    """일반 직접(SMS/LMS/MMS) 청크 발송 — RCS 미사용.

    RCS→직접 전환 fallback 이 없어 _dispatch_rcs_chunks 보다 단순하다(성공 +
    단일 실패 기록). 반환 계약은 동일: (failed_chunk_indices, failed_chunk_sizes,
    item_failed). item_failed 는 HTTP 200 응답 내 item 단위 실패(H1).
    """
    chunks = [recipients[i : i + CHUNK_SIZE] for i in range(0, len(recipients), CHUNK_SIZE)]
    failed_chunks: list[int] = []
    failed_chunk_sizes: list[int] = []
    item_failed = 0

    for chunk_idx, chunk in enumerate(chunks):
        sent_at = reserve_utc_iso if is_reserved else _now_iso()
        try:
            recv_list = [
                RecvInfo(cli_key=_make_cli_key(campaign.id, chunk_idx, i), phone=phone)
                for i, phone in enumerate(chunk)
            ]
            resp = await _send_direct(
                client, callback, content, subject, recv_list,
                msg_type, mms_file_id, is_reserved, msghub_reserve_time,
            )
            msghub_req = MsghubRequest(
                campaign_id=campaign.id,
                chunk_index=chunk_idx,
                response_code=resp.code if resp else None,
                response_message=resp.message if resp else None,
                error_body=None,
                sent_at=sent_at,
                web_req_id=_reservation_id(resp),
            )
            db.add(msghub_req)
            db.flush()

            _, n_failed = _create_messages_from_response(
                db, campaign.id, msghub_req.id, resp, chunk, chunk_idx
            )
            item_failed += n_failed
            db.flush()
            db.commit()

        except MsghubAuthError as exc:
            db.rollback()
            _record_failed_chunk(
                db, campaign.id, chunk_idx, chunk, sent_at, "인증 오류",
                rejection_code=_explicit_rejection_code(exc),
            )
            db.commit()
            raise

        except Exception as exc:
            db.rollback()
            _record_failed_chunk(
                db, campaign.id, chunk_idx, chunk, sent_at, str(exc),
                rejection_code=_explicit_rejection_code(exc),
            )
            db.commit()
            failed_chunks.append(chunk_idx)
            failed_chunk_sizes.append(len(chunk))

    return failed_chunks, failed_chunk_sizes, item_failed


def _create_messages_from_response(
    db: Session,
    campaign_id: int,
    msghub_request_id: int,
    resp: SendResponse | ReserveResponse,
    chunk: list[str],
    chunk_idx: int,
    *,
    fallback: bool = False,
) -> tuple[int, int]:
    """발송 응답에서 Message 레코드 생성.

    예약 응답엔 수신자별 item 이 없어 cliKey 를 다시 만든다. 이때 보낸 키와 같아야 리포트가
    매칭되므로, -fb 키로 보낸 대체 발송 청크는 fallback=True 로 같은 키를 만든다.

    Returns:
        (accepted, failed) — accepted 는 접수(REG)·예약(PENDING) 건수, failed 는
        HTTP 200 응답 내 item 단위 실패(item.code != SUCCESS_CODE)로 즉시 FAILED
        처리된 건수. dispatch 가 웹훅 도착 전에도 fail_count/pending_count 를
        정확히 반영하기 위해 호출자가 사용한다 (H1).
    """
    make_cli_key = _fallback_cli_key if fallback else _make_cli_key
    accepted = 0
    failed = 0
    if isinstance(resp, SendResponse) and resp.items:
        for item in resp.items:
            is_ok = item.code == SUCCESS_CODE
            msg = Message(
                campaign_id=campaign_id,
                msghub_request_id=msghub_request_id,
                to_number=_norm_to_number(item.phone),
                to_number_raw=item.phone,
                cli_key=item.cli_key,
                msg_key=item.msg_key,
                status="REG" if is_ok else "FAILED",
                result_code=item.code,
                result_desc=item.message,
            )
            db.add(msg)
            if is_ok:
                accepted += 1
            else:
                failed += 1
    else:
        for i, phone in enumerate(chunk):
            msg = Message(
                campaign_id=campaign_id,
                msghub_request_id=msghub_request_id,
                to_number=_norm_to_number(phone),
                to_number_raw=phone,
                cli_key=make_cli_key(campaign_id, chunk_idx, i),
                msg_key=None,
                status="PENDING",
            )
            db.add(msg)
            accepted += 1
    return accepted, failed


def _explicit_rejection_code(exc: Exception) -> str | None:
    """접수되지 않은 명시적 4xx 거부만 확정한다. 타임아웃·5xx·파싱 오류는 불확실하다."""
    if (
        isinstance(exc, (MsghubBadRequest, MsghubAuthError, MsghubRateLimited))
        and exc.status_code in (400, 401, 403, 429)
        and exc.code
        and exc.code != SUCCESS_CODE
    ):
        return exc.code
    return None


def _record_failed_chunk(
    db: Session,
    campaign_id: int,
    chunk_idx: int,
    chunk: list[str],
    sent_at: str,
    error_body: str,
    cli_key_suffix: str = "",
    *,
    rejection_code: str | None = None,
) -> None:
    """실패 청크의 MsghubRequest + Message 레코드를 기록한다.

    cliKey 는 실패한 요청에 쓴 키와 같아야 한다 — 직접 재발송(_send_chunk_direct)이면 -fb.
    요청 예외여도 msghub 가 실제로 접수했으면 리포트가 그 키로 오는데, 키가 다르면 FAILED 행은
    phone 보조매칭 대상도 아니라 리포트가 어디에도 붙지 않는다. 재조정(services.reconcile)도 이
    키로 조회한다 — 응답 코드 없는 요청(response_code NULL)과 result_code 없는 FAILED 행이 그 대상이다.
    명시적 요청 거부는 응답 코드를 보존해, 예약 취소가 타임아웃과 구분하고 재조정도 제외한다.
    """
    msghub_req = MsghubRequest(
        campaign_id=campaign_id,
        chunk_index=chunk_idx,
        response_code=rejection_code,
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
            to_number=_norm_to_number(to_num),
            to_number_raw=to_num,
            cli_key=f"{_make_cli_key(campaign_id, chunk_idx, i)}{cli_key_suffix}",
            msg_key=None,
            status="FAILED",
            result_code=rejection_code,
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
