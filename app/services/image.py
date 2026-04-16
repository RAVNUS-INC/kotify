"""이미지 전처리 서비스.

MMS 제약:
- 포맷: JPG/JPEG
- 최대 파일 크기: 300KB
- 최대 해상도: 1500 × 1440 px

RCS 제약:
- 포맷: JPG/JPEG/PNG/BMP/GIF
- 최대 파일 크기: 1MB
- 해상도: 유형별 상이 (이미지 강조형: 900×900 또는 900×1200)

전처리 전략:
1. Pillow로 입력 이미지를 연다 (포맷 무관)
2. RGBA/P/LA 등 알파/팔레트 이미지는 흰 배경에 합성하여 RGB로 평탄화
3. 해상도 초과 시 종횡비 유지하며 thumbnail()로 다운스케일
4. JPEG 인코딩 — 품질 95부터 시작해 제한 이내가 될 때까지 5씩 낮춤
5. 품질 50까지도 안 되면 ValueError
"""
from __future__ import annotations

import io

from PIL import Image, UnidentifiedImageError

# MMS 제약
MMS_MAX_BYTES = 300 * 1024  # 300KB
MMS_MAX_WIDTH = 1500
MMS_MAX_HEIGHT = 1440

# RCS 제약
RCS_MAX_BYTES = 1 * 1024 * 1024  # 1MB
RCS_MAX_WIDTH = 1500
RCS_MAX_HEIGHT = 1440

# 품질 스케일링 파라미터
_QUALITY_START = 95
_QUALITY_MIN = 50
_QUALITY_STEP = 5


class ImageProcessingError(ValueError):
    """이미지 전처리 실패. 사용자에게 보여줄 메시지를 담는다."""


def _open_image(raw: bytes) -> Image.Image:
    """바이트에서 이미지를 열고 RGB로 변환한다."""
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageProcessingError(
            "이미지를 읽을 수 없습니다. JPG, PNG, GIF, WebP 형식만 지원합니다."
        ) from exc

    # RGB 평탄화 (JPEG는 알파 미지원)
    if img.mode in ("RGBA", "LA"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        alpha = img.split()[-1]
        background.paste(img, mask=alpha)
        img = background
    elif img.mode == "P":
        img = img.convert("RGBA")
        background = Image.new("RGB", img.size, (255, 255, 255))
        background.paste(img, mask=img.split()[-1])
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    return img


def _compress_jpeg(
    img: Image.Image, max_bytes: int, max_width: int, max_height: int,
) -> tuple[bytes, int, int]:
    """이미지를 JPEG으로 압축하여 크기 제한에 맞춘다."""
    if img.width > max_width or img.height > max_height:
        img.thumbnail((max_width, max_height), resample=Image.Resampling.LANCZOS)

    quality = _QUALITY_START
    while quality >= _QUALITY_MIN:
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=True)
        data = buf.getvalue()
        if len(data) <= max_bytes:
            return data, img.width, img.height
        quality -= _QUALITY_STEP

    raise ImageProcessingError(
        f"이미지가 너무 복잡해서 {max_bytes // 1024}KB 이내로 압축할 수 없습니다. "
        "더 작은 해상도의 이미지를 사용해주세요."
    )


def preprocess_mms_image(raw: bytes) -> tuple[bytes, int, int]:
    """MMS용 이미지를 제약에 맞게 변환한다 (JPEG, ≤300KB, ≤1500×1440).

    Returns:
        (jpeg_bytes, width, height)
    """
    img = _open_image(raw)
    return _compress_jpeg(img, MMS_MAX_BYTES, MMS_MAX_WIDTH, MMS_MAX_HEIGHT)


def preprocess_rcs_image(raw: bytes) -> tuple[bytes, int, int]:
    """RCS용 이미지를 제약에 맞게 변환한다 (JPEG, ≤1MB, ≤1500×1440).

    RCS는 PNG/GIF/BMP도 지원하지만, 통일성을 위해 JPEG으로 변환.
    이미지 강조형(900×900) 등 유형별 사이즈는 호출자가 검증.

    Returns:
        (jpeg_bytes, width, height)
    """
    img = _open_image(raw)
    return _compress_jpeg(img, RCS_MAX_BYTES, RCS_MAX_WIDTH, RCS_MAX_HEIGHT)
