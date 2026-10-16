"""msghub 결과 코드 헬퍼.

msghub가 돌려주는 resultCodeDesc가 유일한 신뢰 원천이며,
DB의 result_desc 컬럼에 저장한다.

resultCodeDesc가 없는 엣지케이스에서는 raw 코드만 노출한다.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

# 공식 결과 코드표(claudedocs/msghub-api/09-result-codes.md)의 [재전송] 코드.
#
# 요청 단위 내부 오류 — 요청이 접수되지 않았으니 같은 요청을 다시 보내면 된다.
RESEND_CODES: frozenset[str] = frozenset({
    "21400", "22004", "23004", "23005",
    "29017", "29019", "29032",
    "31112", "31118",
    "65999",
})
# CPS 초과 — 잠시 뒤 다시 보낸다 (client 가 MsghubRateLimited 로 따로 분류).
RATE_LIMIT_CODE = "29002"
# RCS 발송 실패 코드이나 실제 단말로 전달됐을 수 있다 — 다시 보내면 이중 수신될 수 있어
# 자동 재발송하지 않는다. 리포트로 오면 '결과 불확실' 실패로 둔다(UNCERTAIN_CODES).
MAYBE_DELIVERED_CODES: frozenset[str] = frozenset({"41007", "54004", "55806", "55820"})

RETRYABLE_CODES: frozenset[str] = RESEND_CODES | MAYBE_DELIVERED_CODES | {RATE_LIMIT_CODE}

SUCCESS_CODE = "10000"

# 리포트 결과 코드 중 전달 성공으로 보는 것. 30124 는 코드표 설명이 "성공" 이다.
# 요청 응답 코드(SUCCESS_CODE)와 구분한다 — 이 집합은 메시지 리포트의 결과에만 쓴다.
DELIVERED_CODES: frozenset[str] = frozenset({SUCCESS_CODE, "30124"})

# 실패로 확정하되 실제로는 전달됐을 수 있는 리포트 결과 코드 — 화면에 '결과 불확실' 로 구분하고
# 양방향 답장의 대체 SMS 를 보내지 않는다(이중 수신 방지). 비용·집계는 실패와 같다(0원).
# 32114 성공불확실(3일이내수신가능), 55821 전송 성공 불확실, 56003 발송 성공·수신 여부 모름.
UNCERTAIN_CODES: frozenset[str] = MAYBE_DELIVERED_CODES | {"32114", "55821", "56003"}


def is_delivered(code: str | None) -> bool:
    """리포트 결과 코드가 전달 성공인가."""
    return code in DELIVERED_CODES


def is_uncertain(code: str | None) -> bool:
    """실패로 집계하지만 전달됐을 수 있는 리포트 결과 코드인가."""
    return code in UNCERTAIN_CODES

# 건당 요금 (원, VAT 별도, 후불)
PRICE_TABLE: dict[tuple[str, str], int] = {
    # (channel, productCode) → 단가
    ("RCS", "CHAT"): 8,       # RCS 양방향 — 24h 세션 상한 적용 (아래 상수 참조)
    # RCS 단문(단방향 SMS형, RPSSAXX001) — outbound 에서 실제 사용되는 단가.
    # U+ 공식 18.7원(VAT 포함)=17원. SMS fallback(9원)보다 비싸다(비용 역전).
    # 양방향 CHAT(8원)은 outbound 불가(compose.py:_MESSAGEBASE_MAP 주석 참조).
    ("RCS", "SMS"): 17,
    # 2026-09-18 실발송 RPSSAXX001 성공 리포트의 실제 상품코드.
    ("RCS", "RSMS"): 17,
    ("RCS", "LMS"): 27,       # RCS LMS
    ("RCS", "MMS"): 85,       # RCS MMS
    ("RCS", "ITMPL"): 40,     # RCS 이미지 템플릿
    ("SMS", "SMS"): 9,
    # 전송 채널과 과금 상품은 다를 수 있다. 공식 report_v12 예시는 MMS/LMS,
    # 기존 연동 스펙은 SMS/LMS로 장문 결과를 전달하므로 둘 다 LMS 단가다.
    ("SMS", "LMS"): 27,
    ("LMS", "LMS"): 27,
    ("MMS", "LMS"): 27,
    ("MMS", "MMS"): 85,
}

# RCS 양방향(CHAT) 세션 과금 정책
# 동일 (챗봇, 고객) 쌍의 24시간 세션당 최대 10건까지만 건당 과금되고
# 이후는 상한(80원)으로 고정. 즉 한 세션 내 건수 N ≥ 10이면 청구는 80원.
CHAT_SESSION_WINDOW_HOURS: int = 24
CHAT_SESSION_MAX_UNITS: int = 10
CHAT_SESSION_CAP_KRW: int = 80

# 양방향 응답에 쓰는 고객 MO replyId 의 유효시간 — 과금 세션(위)과 별개 규칙이다.
# 이통 공통 중계사 연동규격(/message replyId, /momsg): 중계사가 받은 replyId 는 24시간 유효.
# 24h 경계에 딱 맞춰 보내면 msghub→이통사 전달 지연·서버 간 시각 차이로 만료된 replyId 가
# 나갈 수 있어(리포트 단계 실패 → webhook 대체 발송) 여유를 빼고 판정한다.
# 검증 근거: claudedocs/review/reply-id-verification.md
REPLY_ID_VALID_HOURS: int = 24
REPLY_ID_SAFETY_MARGIN_MINUTES: int = 30


def chat_session_cost(unit_count_in_window: int) -> int:
    """24h 세션 내 RCS 양방향 발송 건수 → 실 청구액(원).

    0건=0원, 1~9건=건수×8원, 10건 이상=80원 상한.
    """
    if unit_count_in_window <= 0:
        return 0
    capped = min(unit_count_in_window, CHAT_SESSION_MAX_UNITS)
    return capped * PRICE_TABLE[("RCS", "CHAT")]


def allocate_chat_session_costs(event_times: Iterable[datetime]) -> list[int]:
    """시간순 CHAT 성공 건에 24시간 세션 상한을 배분한다.

    세션은 첫 성공 발송 시각부터 24시간으로 고정한다. 세션 안의 첫 10건은 8원,
    11번째 이후는 0원이며, 24시간 경계의 다음 성공 건부터 새 세션을 시작한다.
    호출자는 같은 (챗봇, 고객) 쌍의 시각을 오름차순으로 넘겨야 한다.
    """
    unit_price = PRICE_TABLE[("RCS", "CHAT")]
    window = timedelta(hours=CHAT_SESSION_WINDOW_HOURS)
    costs: list[int] = []
    session_start: datetime | None = None
    session_units = 0
    for event_time in event_times:
        if session_start is None or event_time >= session_start + window:
            session_start = event_time
            session_units = 0
        session_units += 1
        costs.append(unit_price if session_units <= CHAT_SESSION_MAX_UNITS else 0)
    return costs

# 메시지 유형 → (RCS 키, Fallback 키). 견적은 두 단가의 min~max 범위로 계산한다.
# 주의: 단문은 outbound 에서 양방향 CHAT(8원)을 쓸 수 없어 단방향 SMS형
# (RCS,SMS=17원)으로 발송되므로 RCS(17) > SMS fallback(9) 이다 — 단문은 RCS 가
# 오히려 비싸다(비용 역전). 양방향 8원 전환은 U+ 지원 확인 필요(TODO).
_ESTIMATE_MAP: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "short": (("RCS", "SMS"), ("SMS", "SMS")),
    "long": (("RCS", "LMS"), ("LMS", "LMS")),
    # 이미지 발송은 RPMSMMX001(통합 RCS MMS형) → 리포트 productCode=MMS=85원.
    # ITMPL(40)은 썸네일/SNS/슬라이드형 사전등록 템플릿 전용으로 outbound 미사용.
    "image": (("RCS", "MMS"), ("MMS", "MMS")),
}


def is_retryable(code: str) -> bool:
    """요청 응답 코드가 [재전송] 대상인가 (HTTP 5xx 는 client.py 에서 별도 처리).

    예전엔 49 로 시작하는 코드도 넣었지만 현행 코드표에 49xxx 대역이 없다.
    """
    return bool(code) and code in RETRYABLE_CODES


def calculate_cost(channel: str | None, product_code: str | None, success: bool) -> int:
    """건당 비용 계산 (원). 실패 시 0."""
    if not success or not channel or not product_code:
        return 0
    return PRICE_TABLE.get((channel, product_code), 0)


def estimate_cost(msg_type: str, recipient_count: int) -> tuple[int, int]:
    """예상 비용 범위 (항상 낮은 단가부터 높은 단가 순).

    PRICE_TABLE에서 실제 단가를 참조하여 계산.

    Args:
        msg_type: "short", "long", "image"
        recipient_count: 수신자 수

    Returns:
        (min_cost, max_cost) 튜플
    """
    keys = _ESTIMATE_MAP.get(msg_type)
    if keys is None:
        fallback = PRICE_TABLE.get(("SMS", "SMS"), 9)
        return (fallback * recipient_count, fallback * recipient_count)
    # RCS 단가가 fallback 보다 비쌀 수 있으므로(단문 17 vs 9) min/max 를 정렬한다.
    rate_rcs = PRICE_TABLE[keys[0]]
    rate_fb = PRICE_TABLE[keys[1]]
    lo, hi = min(rate_rcs, rate_fb), max(rate_rcs, rate_fb)
    return (lo * recipient_count, hi * recipient_count)
