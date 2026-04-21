"""msghub 리포트 + MO 웹훅 수신 엔드포인트.

msghub가 발송 결과(리포트)와 고객 답장(MO)을 POST로 전달한다.
- 200: 성공 처리
- 400: 실패 → msghub가 10초 후 재시도
- 양방향 CHAT RCS 실패 시 SMS 수동 fallback 자동 발송

## 보안: URL 경로 토큰

msghub 공식 문서(2.8 메시지 리포트 §3)에 따르면 **웹훅 요청에 어떤
인증 헤더도 첨부하지 않는다** (Content-Type만 포함). 따라서 HMAC 서명
같은 일반적인 웹훅 보안 패턴은 적용 불가능하며, URL 자체를 시크릿으로
쓰는 "URL obscurity" 방식만이 유일한 보호 수단이다.

엔드포인트 형태:
    POST /webhook/msghub/{token}/report
    POST /webhook/msghub/{token}/mo

- token은 `msghub.webhook_token` 설정값과 일치해야 통과
- 토큰 미설정 + dev_mode: 통과 (로컬 테스트 편의)
- 토큰 미설정 + 프로덕션: 거부
- 토큰이 URL 경로에 포함되므로 msghub 콘솔에 전체 URL을 등록하면 끝
"""
from __future__ import annotations

import json
import logging
import secrets as _secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Campaign, Message, MoMessage
from app.msghub.schemas import MoWebhookPayload, RecvInfo, WebhookReport
from app.security.settings_store import SettingsStore
from app.services.report import process_report

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


def _verify_token(token: str, db: Session) -> bool:
    """URL 경로에 포함된 토큰이 저장된 msghub.webhook_token 과 일치하는지 확인.

    msghub는 웹훅에 인증 헤더를 보내지 않으므로(공식 문서 2.8 §3),
    URL 경로에 포함된 시크릿 토큰이 사실상의 유일한 보호 수단이다.
    토큰이 미설정인 경우:
    - dev_mode=True: 통과 (로컬 테스트 편의)
    - dev_mode=False: 거부 (프로덕션 안전)

    저장 값이 손상됐거나 (Fernet 복호화 실패 등) 설정 저장소 자체가
    예외를 던지는 경우 인증 실패로 취급한다. 500으로 번져서 전체 웹훅
    엔드포인트가 다운되는 것을 방지한다.
    """
    store = SettingsStore(db)
    try:
        expected = store.get("msghub.webhook_token")
    except Exception:
        log.exception("msghub.webhook_token 조회 실패 — 인증 거부")
        return False

    if not expected:
        if settings.dev_mode:
            log.warning("msghub.webhook_token 미설정 — 개발 모드이므로 인증 없이 통과")
            return True
        log.error("msghub.webhook_token 미설정 — 프로덕션 환경에서 웹훅 요청 거부")
        return False

    return _secrets.compare_digest(token, expected)


async def _send_sms_fallback(db: Session, messages: list[Message]) -> int:
    """양방향 CHAT RCS 실패 메시지에 대해 SMS fallback을 발송한다.

    각 메시지의 cli_key를 {원본}-fb로 갱신하여 SMS 리포트 매칭에 사용.

    Returns:
        fallback 발송 시도 건수.
    """
    from app.main import get_msghub_client

    client = get_msghub_client()
    if client is None:
        log.error("SMS fallback 실패: msghub 클라이언트 미초기화")
        return 0

    # 캠페인별로 그룹화 (caller_number, content 조회용)
    campaign_cache: dict[int, Campaign] = {}
    for msg in messages:
        if msg.campaign_id not in campaign_cache:
            campaign_cache[msg.campaign_id] = db.get(Campaign, msg.campaign_id)

    sent = 0
    for msg in messages:
        campaign = campaign_cache.get(msg.campaign_id)
        if campaign is None:
            continue

        fb_cli_key = f"{msg.cli_key}-fb"
        msg.cli_key = fb_cli_key
        msg.status = "FB_PENDING"

        try:
            recv = RecvInfo(cli_key=fb_cli_key, phone=msg.to_number)
            await client.send_sms(
                callback=campaign.caller_number,
                msg=campaign.content,
                recv_list=[recv],
            )
            sent += 1
        except Exception:
            log.exception("SMS fallback 발송 실패: msg_id=%s, phone=%s", msg.id, msg.to_number)
            msg.status = "FAILED"
            msg.result_desc = (msg.result_desc or "") + " (SMS fallback 실패)"

    db.flush()
    return sent


@router.post("/msghub/{token}/report")
async def receive_report(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """msghub 발송 결과 웹훅 수신."""
    if not _verify_token(token, db):
        log.warning("웹훅 인증 실패: %s", request.client.host if request.client else "unknown")
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        log.warning("웹훅 JSON 파싱 실패")
        return JSONResponse({"error": "invalid json"}, status_code=400)

    try:
        report = WebhookReport.from_dict(body)
    except Exception:
        log.warning("웹훅 리포트 파싱 실패: %s", body)
        return JSONResponse({"error": "invalid report format"}, status_code=400)

    if not report.items:
        return JSONResponse({"status": "no items"}, status_code=200)

    try:
        processed, fallback_needed = process_report(db, report.items)

        # 양방향 CHAT RCS 실패 → SMS 자동 fallback
        # process_report 결과와 fallback을 단일 트랜잭션으로 커밋.
        # fallback 루프가 실패하면 rollback되어 msghub 재시도 시 멱등하게 재처리.
        fallback_sent = 0
        if fallback_needed:
            fallback_sent = await _send_sms_fallback(db, fallback_needed)
            log.info("SMS fallback 발송: %d/%d건", fallback_sent, len(fallback_needed))

        db.commit()
        log.info("웹훅 리포트 처리: %d/%d건", processed, report.rpt_cnt)
        return JSONResponse(
            {"status": "ok", "processed": processed, "fallback": fallback_sent},
            status_code=200,
        )
    except Exception:
        db.rollback()
        log.exception("웹훅 리포트 처리 실패")
        return JSONResponse({"error": "processing failed"}, status_code=400)


@router.post("/msghub/{token}/mo")
async def receive_mo(
    token: str,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """msghub MO 수신 웹훅 — RCS 양방향(rcsBiLst)와 SMS/MMS(moLst) 양쪽 지원.

    공식 문서 §5.2에 따라 응답은 `{"code": "10000", "message": "success"}`
    형식이어야 msghub가 "수신 성공"으로 큐에서 삭제한다. 실패 시
    `{"code": "20xxx", "message": "..."}` 형태로 돌려주면 재시도.

    msgKey/moKey UNIQUE 제약으로 재시도 중복 저장을 방지한다.
    """
    if not _verify_token(token, db):
        log.warning(
            "MO 웹훅 인증 실패: %s",
            request.client.host if request.client else "unknown",
        )
        return JSONResponse(
            {"code": "20001", "message": "unauthorized"}, status_code=401
        )

    try:
        body = await request.json()
    except Exception:
        log.warning("MO 웹훅 JSON 파싱 실패")
        return JSONResponse(
            {"code": "20002", "message": "invalid json"}, status_code=400
        )

    try:
        payload = MoWebhookPayload.from_dict(body)
    except Exception:
        log.warning("MO 페이로드 파싱 실패: %s", body)
        return JSONResponse(
            {"code": "20003", "message": "invalid mo format"}, status_code=400
        )

    if not payload.items:
        # rcsBiaLst/rcsBirLst만 있는 heartbeat/ack 등에서 정상 경로 — success 반환
        return JSONResponse(
            {"code": "10000", "message": "success"}, status_code=200
        )

    raw = json.dumps(body, ensure_ascii=False)
    now = datetime.now(UTC).isoformat()
    saved = 0
    duplicates = 0

    try:
        for item in payload.items:
            if not item.mo_key:
                log.warning("mo_key 누락 — skip: %s", item)
                continue

            exists = db.execute(
                select(MoMessage.id).where(MoMessage.mo_key == item.mo_key)
            ).scalar_one_or_none()
            if exists is not None:
                duplicates += 1
                continue

            mo = MoMessage(
                mo_key=item.mo_key,
                mo_number=item.number,
                mo_callback=item.callback or None,
                mo_type=item.mo_type or None,
                reply_id=item.reply_id or None,
                postback_id=item.postback_id,
                postback_data=item.postback_data,
                product_code=item.product_code or None,
                mo_title=item.mo_title,
                mo_msg=item.mo_msg,
                telco=item.telco or None,
                content_cnt=item.content_cnt,
                content_info_lst=(
                    json.dumps(item.content_info, ensure_ascii=False)
                    if item.content_info
                    else None
                ),
                mo_recv_dt=item.mo_recv_dt or None,
                raw_payload=raw,
                received_at=now,
            )
            db.add(mo)
            saved += 1

        db.commit()
    except Exception:
        db.rollback()
        log.exception("MO 저장 실패")
        return JSONResponse(
            {"code": "20004", "message": "storage failed"}, status_code=400
        )

    log.warning(  # WARNING — 기본 uvicorn 필터 통과용 (운영 안정화 후 INFO로 강등)
        "MO 수신: 저장 %d건, 중복 %d건, 페이로드 %d건",
        saved,
        duplicates,
        payload.mo_cnt,
    )
    return JSONResponse(
        {"code": "10000", "message": "success"}, status_code=200
    )
