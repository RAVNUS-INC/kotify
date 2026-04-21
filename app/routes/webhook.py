"""msghub 리포트 + MO 웹훅 수신 엔드포인트.

msghub가 발송 결과(리포트)와 고객 답장(MO)을 POST로 전달한다.
- 200: 성공 처리 (msghub가 다시 보내지 않도록 명시적 ack)
- 400: 페이로드 포맷 오류 (재시도해도 동일 실패 — client error)
- 401: 서명 검증 실패 (위조 시도)
- 500: 서버 내부 오류 (msghub가 일정 시간 뒤 재시도 허용)

보안:
- HMAC-SHA256 서명 검증: `X-Msghub-Signature` = hex(HMAC(request_body, secret))
- `msghub.webhook_secret` 미설정 시 fail-closed (401) — dev 에만 SMS_DEV_MODE 로 우회
- 서명 검증 → 페이로드 파싱 순서 엄수 (위조 페이로드로 파서 버그 트리거 방지)

CRITICAL 수정 이력:
- 이전 `hmac.compare_digest(sig, secret)` 는 HMAC 가 아니라 단순 bearer 토큰 비교였음.
  body 무결성 보장 불가 + 시크릿 유출 시 임의 페이로드 주입 가능.
- HMAC(body, secret) 으로 변경 + 시크릿 미설정 시 fail-closed.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
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


async def _verify_webhook(request: Request, raw_body: bytes, db: Session) -> bool:
    """HMAC-SHA256 로 웹훅 페이로드 무결성을 검증한다.

    알고리즘:
        expected_sig = hex(HMAC-SHA256(body, secret))
        if compare_digest(header_sig, expected_sig): pass

    시크릿이 설정되지 않은 경우:
    - 운영(`SMS_DEV_MODE=false`): fail-closed → 401 반환
    - 개발(`SMS_DEV_MODE=true`): 경고 로그 후 통과 (로컬 테스트 편의)

    Args:
        request: Starlette Request.
        raw_body: 이미 읽은 raw body bytes (json 파싱 전).
        db: SQLAlchemy 세션.

    Returns:
        True — 검증 통과 / False — 차단.
    """
    store = SettingsStore(db)
    secret = store.get("msghub.webhook_secret")

    if not secret:
        if os.getenv("SMS_DEV_MODE") == "true":
            log.warning("msghub.webhook_secret 미설정 — dev 모드에서만 통과")
            return True
        log.error("msghub.webhook_secret 미설정 — 웹훅 차단 (fail-closed)")
        return False

    sig_header = request.headers.get("X-Msghub-Signature", "")
    if not sig_header:
        return False

    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig_header, expected)


async def _send_sms_fallback(db: Session, messages: list[Message]) -> int:
    """양방향 CHAT RCS 실패 메시지에 대해 SMS fallback을 발송한다.

    각 메시지마다 savepoint 로 보호하여 부분 실패가 다른 메시지에 영향주지 않도록 한다.
    실패한 메시지는 FAILED 로 전이하고 result_desc 에 원인 기록.

    Returns:
        fallback 발송 성공 건수.
    """
    from app.main import get_msghub_client

    client = get_msghub_client()
    if client is None:
        log.error("SMS fallback 실패: msghub 클라이언트 미초기화")
        return 0

    campaign_cache: dict[int, Campaign] = {}
    for msg in messages:
        if msg.campaign_id not in campaign_cache:
            campaign_cache[msg.campaign_id] = db.get(Campaign, msg.campaign_id)

    sent = 0
    for msg in messages:
        campaign = campaign_cache.get(msg.campaign_id)
        if campaign is None:
            continue

        # 각 메시지마다 savepoint — 부분 실패 격리
        sp = db.begin_nested()
        try:
            fb_cli_key = f"{msg.cli_key}-fb"
            msg.cli_key = fb_cli_key
            msg.status = "FB_PENDING"

            recv = RecvInfo(cli_key=fb_cli_key, phone=msg.to_number)
            await client.send_sms(
                callback=campaign.caller_number,
                msg=campaign.content,
                recv_list=[recv],
            )
            sp.commit()
            sent += 1
        except Exception:
            sp.rollback()
            log.exception(
                "SMS fallback 발송 실패: msg_id=%s, phone=%s",
                msg.id,
                msg.to_number,
            )
            # 실패 기록 — outer transaction 에 남김
            msg.status = "FAILED"
            msg.result_desc = (msg.result_desc or "") + " (SMS fallback 실패)"

    db.flush()
    return sent


@router.post("/msghub/report")
async def receive_report(
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """msghub 발송 결과 웹훅 수신.

    응답 코드:
    - 200: 정상 처리 (msghub 가 재시도하지 않음)
    - 400: 페이로드 포맷 오류 (영구 실패, 재시도해도 무의미)
    - 401: 서명 검증 실패
    - 500: 서버 내부 오류 (msghub 가 지연 후 재시도)
    """
    raw_body = await request.body()

    if not await _verify_webhook(request, raw_body, db):
        log.warning(
            "웹훅 인증 실패: %s",
            request.client.host if request.client else "unknown",
        )
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = json.loads(raw_body)
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

        fallback_sent = 0
        if fallback_needed:
            fallback_sent = await _send_sms_fallback(db, fallback_needed)
            db.commit()
            log.info(
                "SMS fallback 발송: %d/%d건",
                fallback_sent,
                len(fallback_needed),
            )

        log.info("웹훅 리포트 처리: %d/%d건", processed, report.rpt_cnt)
        return JSONResponse(
            {"status": "ok", "processed": processed, "fallback": fallback_sent},
            status_code=200,
        )
    except Exception:
        db.rollback()
        log.exception("웹훅 리포트 처리 실패")
        # 500: 일시적 서버 오류로 간주 → msghub 가 일정 지연 후 재시도.
        # 400 은 "영구 실패" 로 해석되므로, 처리 중 예외는 500 이 맞다.
        return JSONResponse({"error": "processing failed"}, status_code=500)


@router.post("/msghub/mo")
async def receive_mo(
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    """msghub RCS 양방향 MO 수신 웹훅.

    고객이 챗봇으로 보낸 답장과 자동응답 과금 데이터를 저장한다.
    moKey UNIQUE로 재시도 중복 저장을 방지한다.
    """
    raw_body = await request.body()

    if not await _verify_webhook(request, raw_body, db):
        log.warning(
            "MO 웹훅 인증 실패: %s",
            request.client.host if request.client else "unknown",
        )
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = json.loads(raw_body)
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
        return JSONResponse({"error": "storage failed"}, status_code=500)

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
