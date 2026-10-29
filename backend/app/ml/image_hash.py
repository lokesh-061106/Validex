"""Perceptual hashing (pHash) for near-duplicate image detection."""

import io

import numpy as np
from PIL import Image

try:
    import cv2
    HAS_OPENCV = True
except ImportError:  # pragma: no cover
    HAS_OPENCV = False


def phash(image_bytes: bytes) -> str | None:
    """64-bit DCT perceptual hash as 16 hex chars; robust to resizing, recompression and small edits."""
    if not HAS_OPENCV:
        return None
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("L").resize((32, 32), Image.Resampling.LANCZOS)
    except Exception:
        return None
    dct = cv2.dct(np.asarray(img, dtype=np.float32))
    low = dct[:8, :8].flatten()[1:]  # drop the DC term
    bits = low > np.median(low)
    value = 0
    for b in bits:
        value = (value << 1) | int(b)
    return f"{value:016x}"


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def frame_phashes(video_frames: list[bytes]) -> list[str]:
    return [h for h in (phash(f) for f in video_frames) if h]
