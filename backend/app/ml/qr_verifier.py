"""Find and verify signed QR codes on certificates, and detect embedded PDF digital signatures."""

import io
import logging
import base64
from typing import Any

import fitz
import numpy as np
from PIL import Image

from app.mock_authority.keys import parse_and_verify

logger = logging.getLogger(__name__)

try:
    import cv2
    HAS_OPENCV = True
except ImportError:  # pragma: no cover
    HAS_OPENCV = False


def _pages_as_images(file_bytes: bytes, is_pdf: bool, max_pages: int = 3) -> list[np.ndarray]:
    if is_pdf:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        out = []
        for page in list(doc)[:max_pages]:
            pix = page.get_pixmap(dpi=200)
            out.append(np.array(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")))
        return out
    return [np.array(Image.open(io.BytesIO(file_bytes)).convert("RGB"))]


def _embedded_images(file_bytes: bytes, max_pages: int = 3) -> list[np.ndarray]:
    """Raster images embedded in a PDF (a QR is usually inserted as a lossless image)."""
    out = []
    doc = fitz.open(stream=file_bytes, filetype="pdf")
    for page in list(doc)[:max_pages]:
        for img in page.get_images(full=True)[:6]:
            try:
                info = doc.extract_image(img[0])
                arr = np.array(Image.open(io.BytesIO(info["image"])).convert("RGB"))
                if min(arr.shape[:2]) >= 60:
                    out.append(arr)
            except Exception:
                continue
    return out


MAX_DECODE_SIDE = 2400  # cap upscaling so a full-page search cannot spike memory on small hosts


def _try_decode(gray: np.ndarray, detectors) -> str | None:
    scales = [s for s in (1, 2, 3) if max(gray.shape) * s <= MAX_DECODE_SIDE] or [1]
    for det in detectors:
        for scale in scales:
            img = gray if scale == 1 else cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
            img = cv2.copyMakeBorder(img, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
            try:
                text, _, _ = det.detectAndDecode(img)
            except Exception:
                text = None
            if text:
                return text
    return None


def decode_qr_codes(file_bytes: bytes, is_pdf: bool) -> list[str]:
    if not HAS_OPENCV:
        return []
    detectors = [cv2.QRCodeDetector()]
    if hasattr(cv2, "QRCodeDetectorAruco"):
        detectors.append(cv2.QRCodeDetectorAruco())
    found: list[str] = []
    candidates = _embedded_images(file_bytes) if is_pdf else []
    for img in candidates:
        text = _try_decode(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY), detectors)
        if text:
            found.append(text)
    if not found:
        # Scanned documents / photos: search the rendered page, whole and in quadrants
        for img in _pages_as_images(file_bytes, is_pdf):
            gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            h, w = gray.shape
            regions = [gray, gray[h // 2:, : w // 2], gray[h // 2:, w // 2:], gray[: h // 2, : w // 2], gray[: h // 2, w // 2:]]
            for region in regions:
                text = _try_decode(region, detectors[:1])
                if text:
                    found.append(text)
                    break
            if found:
                break
    return list(dict.fromkeys(found))


def verify_qr(file_bytes: bytes, is_pdf: bool) -> dict[str, Any] | None:
    """Return the verification of the first recognised signed QR code, or None if no QR present."""
    codes = decode_qr_codes(file_bytes, is_pdf)
    if not codes:
        return None
    results = [parse_and_verify(c) for c in codes]
    signed = [r for r in results if r["format_ok"]]
    return signed[0] if signed else {**results[0], "raw": codes[0][:200]}


def render_qr_png(qr_text: str) -> str:
    """Generate a real PNG QR image; returns base64. Signing provenance is defined by caller."""
    if not HAS_OPENCV:
        raise RuntimeError("OpenCV QR encoder is unavailable")
    image = cv2.QRCodeEncoder.create().encode(qr_text)
    ok, encoded = cv2.imencode(".png", image)
    if not ok:
        raise RuntimeError("QR image encoding failed")
    return base64.b64encode(encoded.tobytes()).decode("ascii")


def pdf_signature_info(file_bytes: bytes) -> dict[str, Any]:
    """Detect embedded PDF digital signatures. Full PKI validation needs the CA chain (manual step)."""
    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        fields = []
        for page in doc:
            for w in page.widgets() or []:
                if w.field_type == fitz.PDF_WIDGET_TYPE_SIGNATURE:
                    fields.append({"name": w.field_name, "signed": bool(getattr(w, "is_signed", False))})
        return {"has_signature_fields": bool(fields), "fields": fields, "sigflags": doc.get_sigflags()}
    except Exception as e:
        return {"has_signature_fields": False, "error": str(e)}
