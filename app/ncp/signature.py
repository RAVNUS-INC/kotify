"""NCP API Gateway HMAC-SHA256 시그니처 생성.

명세 (SPEC §5.1):
- signing string: "{METHOD} {URI}\\n{TIMESTAMP}\\n{ACCESS_KEY}"
- {METHOD}와 {URI} 사이는 공백 1개, 그 외는 LF
- URI는 host 제외, querystring 포함
- timestamp는 epoch milliseconds (string)
- secret_key를 UTF-8 바이트로 HMAC-SHA256 → Base64

함정:
- timestamp는 한 번만 생성해서 헤더와 signing string에 동일하게 사용
- 5분 이상 drift 시 401 (NTP 동기화 필수)
- URI에 host 포함 시 401
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import time


def make_headers(
    method: str,
    uri: str,
    access_key: str,
    secret_key: str,
) -> dict[str, str]:
    """NCP API Gateway 호출에 필요한 4개 헤더를 반환.

    Returns:
        {
            "x-ncp-apigw-timestamp": "<epoch ms string>",
            "x-ncp-iam-access-key": access_key,
            "x-ncp-apigw-signature-v2": "<base64 hmac-sha256>",
            "Content-Type": "application/json",
        }
    """
    # timestamp는 단 한 번만 생성하여 헤더와 signing string에 동일하게 사용
    timestamp = str(int(time.time() * 1000))

    # signing string: "METHOD URI\nTIMESTAMP\nACCESS_KEY"
    message = f"{method.upper()} {uri}\n{timestamp}\n{access_key}"

    # HMAC-SHA256 (secret_key를 UTF-8 바이트로) → Base64
    digest = hmac.new(
        secret_key.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature = base64.b64encode(digest).decode("utf-8")

    return {
        "x-ncp-apigw-timestamp": timestamp,
        "x-ncp-iam-access-key": access_key,
        "x-ncp-apigw-signature-v2": signature,
        "Content-Type": "application/json",
    }
