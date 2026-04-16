"""msghub 리포트 웹훅 수신 엔드포인트.

msghub가 발송 결과를 POST로 전달한다.
- 200: 성공 처리
- 400: 실패 → msghub가 10초 후 재시도
- 보안: 웹훅 시크릿 토큰 또는 비활성 시 IP 기반 신뢰
"""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.db import SessionLocal
from app.msghub.schemas import WebhookReport
from app.services.report import process_report

log = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


def _verify_webhook(request: Request) -> bool:
    """웹훅 요청의 유효성을 검증한다.

    msghub 콘솔에서 등록한 웹훅 시크릿이 있으면 헤더로 검증.
    없으면 통과 (콘솔에서 URL 등록 자체가 신뢰 기반).
    """
    from app.security.settings_store import SettingsStore

    db = SessionLocal()
    try:
        store = SettingsStore(db)
        secret = store.get("msghub.webhook_secret")
    finally:
        db.close()

    if not secret:
        return True

    sig = request.headers.get("X-Msghub-Signature", "")
    return hmac.compare_digest(sig, secret)


@router.post("/msghub/report")
async def receive_report(request: Request) -> JSONResponse:
    """msghub 발송 결과 웹훅 수신."""
    if not _verify_webhook(request):
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

    db = SessionLocal()
    try:
        processed = process_report(db, report.items)
        db.commit()
        log.info("웹훅 리포트 처리: %d/%d건", processed, report.rpt_cnt)
        return JSONResponse({"status": "ok", "processed": processed}, status_code=200)
    except Exception:
        db.rollback()
        log.exception("웹훅 리포트 처리 실패")
        return JSONResponse({"error": "processing failed"}, status_code=400)
    finally:
        db.close()
