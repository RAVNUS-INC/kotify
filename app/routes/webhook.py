"""msghub 리포트 + MO 웹훅 수신 엔드포인트.

msghub가 발송 결과(리포트)와 고객 답장(MO)을 POST로 전달한다.
- 200: 성공 처리
- 400: 실패 → msghub가 10초 후 재시도
- 보안: 웹훅 시크릿 토큰 헤더 검증 (미설정 시 경고 로그 + 통과)
- 양방향 CHAT RCS 실패 시 SMS 수동 fallback 자동 발송
"""
from __future__ import annotations

import hmac
import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Campaign, Message, MoMessage
from app.msghub.schemas import MoWebhookPayload, RecvInfo, WebhookReport
from app.security.settings_store import SettingsStore
from app.services.report import process_report

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


def _verify_webhook(request: Request, db: Session) -> bool:
    """웹훅 요청의 유효성을 검증한다.

    msghub 콘솔에서 등록한 웹훅 시크릿이 있으면 헤더로 검증.
    없으면 경고 로그 후 통과 (콘솔에서 URL 등록 자체가 신뢰 기반).
    """
    store = SettingsStore(db)
    secret = store.get("msghub.webhook_secret")

    if not secret:
        log.warning("msghub.webhook_secret 미설정 — 웹훅 인증 없이 통과")
        return True

    sig = request.headers.get("X-Msghub-Signature", "")
    return hmac.compare_digest(sig, secret)


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


@router.post("/msghub/report")
async def receive_report(
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """msghub 발송 결과 웹훅 수신."""
    if not _verify_webhook(request, db):
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
        db.commit()

        # 양방향 CHAT RCS 실패 → SMS 자동 fallback
        fallback_sent = 0
        if fallback_needed:
            fallback_sent = await _send_sms_fallback(db, fallback_needed)
            db.commit()
            log.info("SMS fallback 발송: %d/%d건", fallback_sent, len(fallback_needed))

        log.info("웹훅 리포트 처리: %d/%d건", processed, report.rpt_cnt)
        return JSONResponse(
            {"status": "ok", "processed": processed, "fallback": fallback_sent},
            status_code=200,
        )
    except Exception:
        db.rollback()
        log.exception("웹훅 리포트 처리 실패")
        return JSONResponse({"error": "processing failed"}, status_code=400)


@router.post("/msghub/mo")
async def receive_mo(
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """msghub RCS 양방향 MO 수신 웹훅.

    고객이 챗봇으로 보낸 답장과 자동응답 과금 데이터를 저장한다.
    moKey UNIQUE로 재시도 중복 저장을 방지한다.
    """
    if not _verify_webhook(request, db):
        log.warning(
            "MO 웹훅 인증 실패: %s",
            request.client.host if request.client else "unknown",
        )
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        log.warning("MO 웹훅 JSON 파싱 실패")
        return JSONResponse({"error": "invalid json"}, status_code=400)

    try:
        payload = MoWebhookPayload.from_dict(body)
    except Exception:
        log.warning("MO 페이로드 파싱 실패: %s", body)
        return JSONResponse({"error": "invalid mo format"}, status_code=400)

    if not payload.items:
        return JSONResponse({"status": "no items"}, status_code=200)

    raw = json.dumps(body, ensure_ascii=False)
    now = datetime.now(UTC).isoformat()
    saved = 0
    duplicates = 0

    try:
        for item in payload.items:
            if not item.mo_key:
                log.warning("moKey 누락 — skip: %s", item)
                continue

            exists = db.execute(
                select(MoMessage.id).where(MoMessage.mo_key == item.mo_key)
            ).scalar_one_or_none()
            if exists is not None:
                duplicates += 1
                continue

            mo = MoMessage(
                mo_key=item.mo_key,
                mo_number=item.mo_number,
                mo_callback=item.mo_callback or None,
                mo_type=item.mo_type or None,
                product_code=item.product_code or None,
                mo_title=item.mo_title,
                mo_msg=item.mo_msg,
                telco=item.telco or None,
                content_cnt=item.content_cnt,
                content_info_lst=(
                    json.dumps(item.content_info_lst, ensure_ascii=False)
                    if item.content_info_lst
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
        return JSONResponse({"error": "storage failed"}, status_code=400)

    log.info(
        "MO 수신: 저장 %d건, 중복 %d건, 페이로드 %d건",
        saved,
        duplicates,
        payload.mo_cnt,
    )
    return JSONResponse(
        {"status": "ok", "saved": saved, "duplicates": duplicates},
        status_code=200,
    )
