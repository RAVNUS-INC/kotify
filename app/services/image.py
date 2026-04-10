"""MMS 이미지 전처리 서비스.

NCP SENS MMS 제약 (https://api.ncloud-docs.com/docs/ai-application-service-sens-smsv2):
- 포맷: JPG/JPEG (PNG/GIF는 변환 필요)
- 최대 파일 크기: 300KB
- 최대 해상도: 1500 × 1440 px
- Base64 인코딩 후 전송 → 실제 wire 크기는 약 4/3 배

전처리 전략:
1. Pillow로 입력 이미지를 연다 (포맷 무관)
2. RGBA/P/LA 등 알파/팔레트 이미지는 흰 배경에 합성하여 RGB로 평탄화
3. 1500×1440 초과 시 종횡비 유지하며 thumbnail() 로 다운스케일
4. JPEG 인코딩 — 품질 95부터 시작해 300KB 이내가 될 때까지 5씩 낮춤
5. 품질 50까지도 안 되면 ValueError (사용자가 더 단순한 이미지를 올려야 함)
"""
from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

# NCP 제약 — 한 곳에 모아두고 send 코드와 전처리 코드가 함께 참조
NCP_MMS_MAX_BYTES = 300 * 1024  # 300KB
NCP_MMS_MAX_WIDTH = 1500
NCP_MMS_MAX_HEIGHT = 1440

# 품질 스케일링 파라미터
_QUALITY_START = 95
_QUALITY_MIN = 50
_QUALITY_STEP = 5


class ImageProcessingError(ValueError):
    """이미지 전처리 실패. 사용자에게 보여줄 메시지를 담는다."""


def preprocess_mms_image(raw: bytes) -> tuple[bytes, int, int]:
    """MMS용 이미지를 NCP 제약에 맞게 변환한다.

    Args:
        raw: 원본 이미지 바이트 (JPG/PNG/GIF/WebP 등 Pillow가 읽을 수 있는 모든 포맷)

    Returns:
        (jpeg_bytes, width, height) — 변환 후 JPEG 바이너리와 최종 픽셀 크기

    Raises:
        ImageProcessingError: 입력이 이미지가 아니거나, 품질 50에서도 300KB 초과
    """
    try:
        img = Image.open(io.BytesIO(raw))
        # Pillow는 lazy load — 픽셀에 접근하기 전까지 실제 디코딩이 안 됨
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageProcessingError(
            "이미지를 읽을 수 없습니다. JPG, PNG, GIF, WebP 형식만 지원합니다."
        ) from exc

    # ── 1. RGB 평탄화 ────────────────────────────────────────────────────────
    # JPEG는 알파 채널을 지원하지 않는다.
    # 알파/팔레트 이미지를 RGB로 그냥 변환하면 투명 영역이 검게 떨어지므로
    # 흰 배경에 합성한다.
    if img.mode in ("RGBA", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        # 알파 채널을 마스크로 사용하여 합성
        alpha = img.split()[-1]
        background.paste(img, mask=alpha)
        img = background
    elif img.mode == "P":
        # 팔레트 이미지 — 알파 정보가 있을 수 있으므로 일단 RGBA로 풀고 위 로직 재사용
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    # ── 2. 다운스케일 (필요 시) ──────────────────────────────────────────────
    # thumbnail() 은 종횡비를 유지하면서 in-place로 줄인다.
    # 입력보다 큰 사이즈로는 늘리지 않는다 (LANCZOS = 고품질 다운스케일).
    if img.width > NCP_MMS_MAX_WIDTH or img.height > NCP_MMS_MAX_HEIGHT:
        img.thumbnail(
            (NCP_MMS_MAX_WIDTH, NCP_MMS_MAX_HEIGHT),
            resample=Image.Resampling.LANCZOS,
        )

    # ── 3. 품질 스케일링 ────────────────────────────────────────────────────
    # 95 → 90 → 85 → ... → 50 까지 시도. 첫번째로 300KB 이내가 되는 품질을 채택.
    # optimize=True 는 Huffman 테이블을 한번 더 최적화하여 5~10% 더 줄여준다.
    quality = _QUALITY_START
    while quality >= _QUALITY_MIN:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
        data = buf.getvalue()
        if len(data) <= NCP_MMS_MAX_BYTES:
            return data, img.width, img.height
        quality -= _QUALITY_STEP

    raise ImageProcessingError(
        f"이미지가 너무 복잡해서 {NCP_MMS_MAX_BYTES // 1024}KB 이내로 압축할 수 없습니다. "
        "더 작은 해상도의 이미지를 사용해주세요."
    )
