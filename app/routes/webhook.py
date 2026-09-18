"""msghub 리포트 + MO 웹훅 수신 엔드포인트.

msghub가 발송 결과(리포트)와 고객 답장(MO)을 POST로 전달한다.
- 200: 성공 처리
- 400: 실패 → msghub가 10초 후 재시도. 발송 응답·커밋을 기다리느라 행이 아직 없는
  리포트가 섞이면 나머지를 반영하고 400 으로 배치째 다시 받는다 (services.report.split_unrecorded)
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
from starlette.background import BackgroundTask

from app.config import settings
from app.db import get_db
from app.models import MoMessage
from app.msghub.schemas import MoWebhookPayload, WebhookReport
from app.security.settings_store import SettingsStore
from app.services import events
from app.services.report import (
    awaiting_record,
    process_report,
    send_sms_fallback,
    split_unrecorded,
)
from app.util.phone import normalize_phone

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

    # defense-in-depth: 양쪽 strip — URL path 는 브라우저/프록시가 trailing
    # whitespace 넣지 않지만, 저장 경로에 따라 expected 에 공백이 섞여 저장된
    # 이력이 있으면 대조 실패로 이어질 수 있어 명시 정규화.
    return _secrets.compare_digest(token.strip(), (expected or "").strip())


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
        # 행 기록 전 리포트는 빼고 반영한 뒤 400 으로 배치째 재전송을 받는다 (report.split_unrecorded)
        ready, deferred = split_unrecorded(db, report.items)
        processed, fallback_needed = process_report(db, ready)

        # 양방향 CHAT RCS 실패 → SMS 자동 fallback
        # process_report 결과와 fallback을 단일 트랜잭션으로 커밋.
        # fallback 루프가 실패하면 rollback되어 msghub 재시도 시 멱등하게 재처리.
        # 커밋 전엔 -fb 로 바꾼 행이 다른 요청에 안 보인다 — 그사이 온 대체 SMS 리포트는 재전송으로 받는다.
        fallback_sent = 0
        with awaiting_record({m.campaign_id for m in fallback_needed}):
            if fallback_needed:
                from app.main import get_msghub_client

                fallback_sent = await send_sms_fallback(db, get_msghub_client(), fallback_needed)
                log.info("SMS fallback 발송: %d/%d건", fallback_sent, len(fallback_needed))

            db.commit()
    except Exception:
        db.rollback()
        log.exception("웹훅 리포트 처리 실패")
        return JSONResponse({"error": "processing failed"}, status_code=400)

    # 열린 대화방의 전달 상태(대기 → 전달/실패)와 채널 라벨을 새로고침 없이 반영한다.
    # 커밋이 끝나고 바뀐 행이 있을 때만. 대량 발송 리포트는 몰려오므로 창당 1회로 합쳐
    # 발행한다 — 이벤트마다 열린 탭이 목록·상세를 다시 불러온다(events.publish_throttled).
    # 행 기록 전 리포트로 400 을 주는 배치도 나머지는 커밋됐다 — 재전송 때는 DONE 이라 건너뛰어 다시 알리지 않는다.
    if processed or fallback_sent:
        events.publish_throttled("thread.updated")
    if deferred:
        log.warning(
            "행 기록 전 리포트 — 나머지 %d건 반영, %d건은 400 으로 msghub 재전송을 받는다: cliKey=%s",
            processed, len(deferred), next(item.cli_key for item in deferred if item.cli_key),
        )
        return JSONResponse({"error": "report before record"}, status_code=400)
    log.info("웹훅 리포트 처리: %d/%d건", processed, report.rpt_cnt)
    return JSONResponse(
        {"status": "ok", "processed": processed, "fallback": fallback_sent},
        status_code=200,
    )


def _callback_aliases(value: str | None) -> tuple[str, ...]:
    """발신번호·RCS chatbotId를 비교할 정규화 별칭 집합."""
    raw = (value or "").strip().casefold()
    if not raw:
        return ()
    digits = "".join(c for c in raw if c.isdigit())
    if not digits or digits == raw:
        return (raw,)
    return (raw, digits)


def _active_caller_callbacks(db: Session) -> dict[str, str]:
    """활성 발신번호와 chatbotId 별칭을 대표 발신번호에 매핑한다."""
    from app.models import Caller

    rows = db.execute(
        select(Caller.number, Caller.rcs_chatbot_id).where(Caller.active == 1)
    ).all()
    aliases: dict[str, str] = {}
    for number, chatbot_id in rows:
        canonical = "".join(c for c in number if c.isdigit())
        if not canonical:
            continue
        for value in (number, chatbot_id):
            for alias in _callback_aliases(value):
                aliases[alias] = canonical
    return aliases


def _resolve_callback(value: str | None, aliases: dict[str, str]) -> str | None:
    """공급자 callback 값을 등록된 대표 발신번호로 변환한다."""
    for alias in _callback_aliases(value):
        canonical = aliases.get(alias)
        if canonical:
            return canonical
    return None


def _synth_mo_key(
    number: str, recv_dt: str | None, msg: str | None, callback: str | None
) -> str:
    """moKey 누락 시 페이로드 기반 대체 멱등키 — 영구 유실 방지 + 재시도 중복 방지.

    같은 MO 가 재전송되면 같은 해시가 나와 UNIQUE 제약으로 중복 저장이 차단된다.
    """
    import hashlib

    basis = f"{number}|{recv_dt or ''}|{msg or ''}|{callback or ''}"
    return "syn-" + hashlib.sha256(basis.encode()).hexdigest()[:24]


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
    rejected = 0
    saved_mos: list[MoMessage] = []  # n8n 알림 대상 (신규 저장분만)
    delivery_ids: list[int] = []
    active_callbacks = _active_caller_callbacks(db)

    try:
        for item in payload.items:
            # 인바운드(회신) 번호도 숫자만 저장(테마 D 통일). 휴대폰은 normalize_phone,
            # 그 외(지역/대표번호 등)는 숫자만 추출해 하이픈·공백 등 구분자를 제거한다.
            # 표시용 하이픈은 프론트(formatPhone)에서 처리.
            item.number = normalize_phone(item.number) or "".join(
                c for c in item.number if c.isdigit()
            )

            # SMS/MMS MO의 공식 필드 의미는 moNumber=우리 수신번호,
            # moCallback=고객 발신번호다. RCS MO는 phone=고객, chatbotId=우리
            # 채널이므로 두 형식을 분리한다. 구버전/테스트 payload의 반대
            # 표기도 활성 Caller를 기준으로 안전하게 호환한다.
            provider_number = "".join(c for c in item.number if c.isdigit())
            provider_callback_raw = item.callback
            provider_callback = "".join(c for c in provider_callback_raw if c.isdigit())
            number_canonical = _resolve_callback(provider_number, active_callbacks)
            callback_canonical = _resolve_callback(provider_callback_raw, active_callbacks)
            if item.is_rcs:
                customer_number = provider_number
                our_callback = callback_canonical or provider_callback or provider_callback_raw.strip()
                callback_registered = callback_canonical is not None
            elif number_canonical:
                customer_number, our_callback = provider_callback, number_canonical
                callback_registered = True
            elif callback_canonical:
                # 이전 내부 payload 호환: moNumber=고객, moCallback=대표번호.
                customer_number, our_callback = provider_number, callback_canonical
                callback_registered = True
            elif provider_number.startswith("010") and not provider_callback.startswith("010"):
                # 활성 Caller 정보가 없는 구형 내부 payload 호환.
                customer_number, our_callback = provider_number, provider_callback
                callback_registered = not active_callbacks
            else:
                customer_number, our_callback = provider_callback or provider_number, provider_number
                callback_registered = not active_callbacks

            # 위변조 방지 — 공식 MO 수신번호(our_callback)가 활성 발신번호인지
            # 확인한다. 발신번호 미등록 환경에서는 검증 불가하므로 통과시킨다.
            if active_callbacks and not callback_registered:
                log.warning(
                    "MO 수신번호 미등록 — 거부(위변조 의심): %s", our_callback
                )
                rejected += 1
                continue

            item.number = customer_number
            item.callback = our_callback

            # 유실 방지 — moKey 누락 시 페이로드 기반 대체 멱등키로 저장(영구 유실 방지).
            mo_key = item.mo_key or _synth_mo_key(
                item.number, item.mo_recv_dt, item.mo_msg, item.callback
            )

            exists = db.execute(
                select(MoMessage.id).where(MoMessage.mo_key == mo_key)
            ).scalar_one_or_none()
            if exists is not None:
                duplicates += 1
                continue

            mo = MoMessage(
                mo_key=mo_key,
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
            saved_mos.append(mo)
            saved += 1

        # MO와 알림 outbox를 한 트랜잭션에 넣는다. n8n HTTP 장애는 이후
        # 재시도하지만, 큐 기록 자체가 실패하면 msghub에 400을 보내 MO부터
        # 다시 받는다. 이로써 저장된 회신만 있고 알림 요청은 없는 상태를 막는다.
        if saved_mos:
            db.flush()
            from app.services.notify import enqueue_n8n_delivery, prepare_n8n_delivery

            n8n_url, n8n_payloads = prepare_n8n_delivery(db, saved_mos)
            if n8n_url and n8n_payloads:
                delivery_ids = enqueue_n8n_delivery(
                    db, saved_mos, n8n_url, n8n_payloads
                )
        db.commit()
    except Exception:
        db.rollback()
        log.exception("MO 저장 실패")
        return JSONResponse(
            {"code": "20004", "message": "storage failed"}, status_code=400
        )

    log.warning(  # WARNING — 기본 uvicorn 필터 통과용 (운영 안정화 후 INFO로 강등)
        "MO 수신: 저장 %d건, 중복 %d건, 거부 %d건, 페이로드 %d건",
        saved,
        duplicates,
        rejected,
        payload.mo_cnt,
    )

    # 대화방 실시간 갱신 — 접속 중인 브라우저(SSE)로 알린다. 새로 저장한 회신이 있을 때만.
    # 회신을 부르는 캠페인("YES 로 답장")이면 MO 가 몰려오므로 창당 1회로 합쳐 발행한다 —
    # 이벤트마다 열린 탭이 목록·상세를 다시 불러온다(events.publish_throttled). 조용하던 뒤 첫
    # 회신은 바로, 몰려온 회신의 마지막 것도 창 길이 안에 반영된다. 발행은 논블로킹이고
    # 예외를 던지지 않지만 방어적으로 한 번 더 감싼다(알림 실패가 msghub success 를 막지 않게).
    if saved_mos:
        try:
            events.publish_throttled("message.new")
        except Exception:  # noqa: BLE001
            log.debug("SSE 이벤트 발행 실패(무시)", exc_info=True)

    # outbox HTTP 전송은 응답 반환 후 수행한다. 네트워크 장애면 FAILED로 남고
    # 주기 작업이 재시도한다. 같은 MO는 UNIQUE(mo_id)라 중복 알림 행이 생기지 않는다.
    background: BackgroundTask | None = None
    if delivery_ids:
        from app.services.notify import process_n8n_outbox

        background = BackgroundTask(process_n8n_outbox, db)

    return JSONResponse(
        {"code": "10000", "message": "success"},
        status_code=200,
        background=background,
    )
