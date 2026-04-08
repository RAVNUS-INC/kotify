"""
한국 휴대폰 번호 정규화 + 일괄 파싱.

★ 사용자 직접 작성 영역 ★

명세 (SPEC §6):
- 입력 형식 (전부 허용):
    01012345678
    010-1234-5678
    010 1234 5678
    010.1234.5678
    +82-10-1234-5678
    +821012345678
    8210-1234-5678
- 정규화 규칙:
    1. 공백/-/./()  제거
    2. 선두 +82 → 0
    3. 선두 82 (10자리 이상) → 0
    4. 결과가 ^01[016789]\\d{7,8}$ 매치
    5. 미매치 → None
- 정책 (§6.3): 잘못된 번호 1개라도 있으면 발송 차단
"""
from __future__ import annotations


def normalize_phone(raw: str) -> str | None:
    """단일 번호 정규화. 성공 시 '01012345678' 형태, 실패 시 None."""
    raise NotImplementedError(
        "★ 직접 작성하세요. SPEC §6.2와 docstring을 참고하세요. ★"
    )


def parse_phone_list(text: str) -> tuple[list[str], list[str]]:
    """
    멀티라인/콤마/세미콜론 구분 텍스트에서 번호 추출.

    Returns:
        (valid_normalized, invalid_originals)
    """
    raise NotImplementedError(
        "★ 직접 작성하세요. 입력 한 줄에 여러 번호 가능, 빈 줄 무시. ★"
    )
