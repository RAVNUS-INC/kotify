"""msghub 결과 코드 헬퍼.

msghub가 돌려주는 resultCodeDesc가 유일한 신뢰 원천이며,
DB의 result_desc 컬럼에 저장한다.

resultCodeDesc가 없는 엣지케이스에서는 raw 코드만 노출한다.
"""
from __future__ import annotations

# 재시도가 필요한 에러 코드
RETRYABLE_CODES: frozenset[str] = frozenset({
    "29002",  # CPS 초과
    "29006",  # WRITE 소켓
    "29007",  # READ 소켓
    "29012",  # 서버 에러
    "29015",  # 타임아웃
    "29017",  # Redis
    "29019",  # DB
    "29031",  # 재시도 필요
    "29032",  # 내부 에러
    "21400",  # 내부 에러
    "22004",  # 내부 에러
    "23004",  # 내부 에러
    "23005",  # 내부 에러
    "31112",  # 통신사 내부
    "31118",  # 내부 에러
    "41007",  # RCS 전달 가능성
    "54004",  # RCS 전달 가능성
    "55806",  # RCS 전달 가능성
    "55820",  # RCS 전달 가능성
    "65999",  # 내부 에러
})

SUCCESS_CODE = "10000"

# 건당 요금 (원, VAT 별도, 후불)
PRICE_TABLE: dict[tuple[str, str], int] = {
    # (channel, productCode) → 단가
    ("RCS", "CHAT"): 8,       # RCS 양방향 — 24h 세션 상한 적용 (아래 상수 참조)
    ("RCS", "SMS"): 17,       # RCS SMS (미사용, 양방향 우선)
    ("RCS", "LMS"): 27,       # RCS LMS
    ("RCS", "MMS"): 85,       # RCS MMS
    ("RCS", "ITMPL"): 40,     # RCS 이미지 템플릿
    ("SMS", "SMS"): 9,
    ("LMS", "LMS"): 27,
    ("MMS", "MMS"): 85,
}

# RCS 양방향(CHAT) 세션 과금 정책
# 동일 (챗봇, 고객) 쌍의 24시간 세션당 최대 10건까지만 건당 과금되고
# 이후는 상한(80원)으로 고정. 즉 한 세션 내 건수 N ≥ 10이면 청구는 80원.
CHAT_SESSION_WINDOW_HOURS: int = 24
CHAT_SESSION_MAX_UNITS: int = 10
CHAT_SESSION_CAP_KRW: int = 80


def chat_session_cost(unit_count_in_window: int) -> int:
    """24h 세션 내 RCS 양방향 발송 건수 → 실 청구액(원).

    0건=0원, 1~9건=건수×8원, 10건 이상=80원 상한.
    """
    if unit_count_in_window <= 0:
        return 0
    capped = min(unit_count_in_window, CHAT_SESSION_MAX_UNITS)
    return capped * PRICE_TABLE[("RCS", "CHAT")]

# 메시지 유형 → (RCS 키, Fallback 키) 매핑
_ESTIMATE_MAP: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {
    "short": (("RCS", "CHAT"), ("SMS", "SMS")),
    "long": (("RCS", "LMS"), ("LMS", "LMS")),
    "image": (("RCS", "ITMPL"), ("MMS", "MMS")),
}


def is_retryable(code: str) -> bool:
    """재시도 가능한 에러 코드인지 확인."""
    return code in RETRYABLE_CODES


def describe(code: str | None, raw_message: str | None = None) -> str:
    """msghub 결과 코드를 사람이 읽을 수 있는 문자열로 변환.

    우선순위:
    1. msghub가 보내준 resultCodeDesc — 유일한 신뢰 원천
    2. 없으면 raw 코드만 노출
    3. 코드도 없으면 "—"
    """
    if raw_message:
        return raw_message
    if code:
        return f"결과 코드 {code}"
    return "—"


def calculate_cost(channel: str | None, product_code: str | None, success: bool) -> int:
    """건당 비용 계산 (원). 실패 시 0."""
    if not success or not channel or not product_code:
        return 0
    return PRICE_TABLE.get((channel, product_code), 0)


def estimate_cost(msg_type: str, recipient_count: int) -> tuple[int, int]:
    """예상 비용 범위 (최소=RCS 전체 성공, 최대=전체 fallback).

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
    min_rate = PRICE_TABLE[keys[0]]
    max_rate = PRICE_TABLE[keys[1]]
    return (min_rate * recipient_count, max_rate * recipient_count)
