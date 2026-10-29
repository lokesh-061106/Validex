"""OCR: native PDF text first, then EasyOCR (with OpenCV preprocessing) for scans and photos.

Fallback order for raster input: EasyOCR -> PaddleOCR -> Tesseract. If no engine is available
the result has empty text and zero confidence, which the validator reports as
"manual review required" instead of inventing data.
"""

import io
import os
import logging
from typing import Any

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

try:
    import cv2
    HAS_OPENCV = True
except ImportError:  # pragma: no cover
    HAS_OPENCV = False


class OCRResult:
    def __init__(self, text: str, confidence: float, engine: str, words: list[dict] | None = None, page_count: int = 1):
        self.text = text
        self.confidence = confidence
        self.engine = engine
        self.words = words or []  # [{"text", "bbox": [x0,y0,x1,y1], "page", "confidence"}]
        self.page_count = page_count

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "confidence": self.confidence, "engine": self.engine, "page_count": self.page_count}


def preprocess(image: Image.Image) -> np.ndarray:
    """Grayscale, upscale small scans, denoise, deskew and binarise."""
    img = np.array(image.convert("L"))
    if not HAS_OPENCV:
        return img
    h, w = img.shape
    if max(h, w) < 1500:
        scale = 1500 / max(h, w)
        img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    img = cv2.fastNlMeansDenoising(img, h=10)
    # Deskew using the minimum-area rectangle of dark pixels
    coords = np.column_stack(np.where(img < 128))
    if len(coords) > 100:
        angle = cv2.minAreaRect(coords.astype(np.float32))[-1]
        angle = -(90 + angle) if angle < -45 else -angle
        if angle > 45:
            angle -= 90
        if 0.3 < abs(angle) < 15:
            hh, ww = img.shape
            m = cv2.getRotationMatrix2D((ww / 2, hh / 2), angle, 1.0)
            img = cv2.warpAffine(img, m, (ww, hh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    img = cv2.adaptiveThreshold(img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)
    return img


def visible_text(page) -> tuple[str, list[dict]]:
    """Text a reader actually sees: drops characters hidden under a later white box or later text.

    Plain PDF text extraction also returns text that was covered up during an edit, which would make
    the validator read the *original* value instead of the altered one shown on the page.
    """
    try:
        trace = page.get_texttrace()
    except Exception:
        return page.get_text(), []
    covers = [(d["rect"], d.get("seqno", 0)) for d in page.get_drawings()
              if d.get("fill") and min(d["fill"]) > 0.95 and (d.get("fill_opacity") or 1) > 0.9]
    spans = [(tuple(s["bbox"]), s.get("seqno", 0)) for s in trace]

    chars = []
    for s in trace:
        seq, size = s.get("seqno", 0), s.get("size", 10)
        for c in s.get("chars", []):
            if c[0] < 32:
                continue
            x0, y0, x1, y1 = c[3]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            hidden = any(r.x0 <= cx <= r.x1 and r.y0 <= cy <= r.y1 and q > seq for r, q in covers) or any(
                b[0] <= cx <= b[2] and b[1] <= cy <= b[3] and q > seq for b, q in spans)
            if not hidden:
                chars.append((chr(c[0]), (x0, y0, x1, y1), size))

    chars.sort(key=lambda ch: (round(ch[1][3], 0), ch[1][0]))
    lines: list[list] = []
    for ch in chars:
        if lines and abs(lines[-1][0][1][3] - ch[1][3]) < 0.5 * ch[2]:
            lines[-1].append(ch)
        else:
            lines.append([ch])

    text_lines, words = [], []
    for line in lines:
        line.sort(key=lambda ch: ch[1][0])
        buf, prev, word = "", None, None
        for ch, box, size in line:
            gap = box[0] - prev[2] if prev else 0
            if prev and gap > 0.2 * size and ch != " " and not buf.endswith(" "):
                buf += " "
            buf += ch
            if ch == " " or (prev and gap > 0.2 * size):
                if word and word["text"].strip():
                    words.append(word)
                word = None
            if ch != " ":
                if word is None:
                    word = {"text": ch, "bbox": list(box), "confidence": 1.0, "unit": "pt"}
                else:
                    word["text"] += ch
                    word["bbox"][2], word["bbox"][3] = max(word["bbox"][2], box[2]), max(word["bbox"][3], box[3])
            prev = box
        if word and word["text"].strip():
            words.append(word)
        text_lines.append(buf.strip())
    return "\n".join(text_lines), words


class OCREngine:
    def __init__(self):
        self._easy = None
        self._easy_tried = False
        self._paddle = None
        self._paddle_tried = False

    def _easyocr(self):
        if not self._easy_tried:
            self._easy_tried = True
            try:
                import easyocr
                from app.ml.infrastructure_cv import MODEL_DIR
                model_dir = os.path.join(MODEL_DIR, "easyocr")
                os.makedirs(model_dir, exist_ok=True)
                self._easy = easyocr.Reader(["en"], gpu=False, verbose=False, model_storage_directory=model_dir)
                logger.info("EasyOCR initialised.")
            except Exception as e:
                logger.warning(f"EasyOCR unavailable: {e}")
        return self._easy

    def _paddleocr(self):
        if not self._paddle_tried:
            self._paddle_tried = True
            try:
                from paddleocr import PaddleOCR
                self._paddle = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
            except Exception as e:
                logger.info(f"PaddleOCR unavailable: {e}")
        return self._paddle

    def extract(self, file_bytes: bytes, is_pdf: bool) -> OCRResult:
        return self.extract_from_pdf_bytes(file_bytes) if is_pdf else self.extract_from_image_bytes(file_bytes)

    def extract_from_pdf_bytes(self, pdf_bytes: bytes) -> OCRResult:
        import fitz

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            logger.error(f"Unreadable PDF: {e}")
            return OCRResult("", 0.0, "none")

        pages, words, confidences, engines = [], [], [], set()
        for page_index, page in enumerate(doc):
            native, page_words = visible_text(page)
            if native and len(native.strip()) > 30:
                pages.append(native)
                confidences.append(0.99)
                engines.add("pdf-native")
                words += [{**w, "page": page_index} for w in page_words]
            else:
                pix = page.get_pixmap(dpi=200)
                res = self.extract_from_image(Image.open(io.BytesIO(pix.tobytes("png"))))
                pages.append(res.text)
                confidences.append(res.confidence)
                engines.add(res.engine)
                scale = 72 / 200
                for wd in res.words:
                    x0, y0, x1, y1 = wd["bbox"]
                    words.append({**wd, "bbox": [x0 * scale, y0 * scale, x1 * scale, y1 * scale], "page": page_index, "unit": "pt"})

        text = "\n\n--- Page Break ---\n\n".join(pages)
        conf = float(sum(confidences) / len(confidences)) if confidences else 0.0
        return OCRResult(text, round(conf, 3), "+".join(sorted(engines)) or "none", words, page_count=len(doc))

    def extract_from_image_bytes(self, file_bytes: bytes) -> OCRResult:
        try:
            image = Image.open(io.BytesIO(file_bytes))
        except Exception:
            return OCRResult("", 0.0, "none")
        return self.extract_from_image(image)

    def extract_from_image(self, image: Image.Image) -> OCRResult:
        if max(image.size) > 2500:  # phone photos: OCR at a bounded size (memory and speed)
            image = image.copy()
            image.thumbnail((2500, 2500))
        prepared = preprocess(image)
        sx = prepared.shape[1] / image.width
        sy = prepared.shape[0] / image.height

        reader = self._easyocr()
        if reader is not None:
            try:
                results = reader.readtext(prepared, detail=1, paragraph=False)
                words, lines, confs = [], [], []
                for bbox, text, conf in results:
                    xs, ys = [p[0] for p in bbox], [p[1] for p in bbox]
                    words.append({"text": text, "bbox": [min(xs) / sx, min(ys) / sy, max(xs) / sx, max(ys) / sy],
                                  "confidence": float(conf), "page": 0, "unit": "px"})
                    lines.append(text)
                    confs.append(float(conf))
                return OCRResult("\n".join(lines), round(float(np.mean(confs)) if confs else 0.0, 3), "easyocr", words)
            except Exception as e:
                logger.warning(f"EasyOCR inference failed: {e}")

        paddle = self._paddleocr()
        if paddle is not None:
            try:
                results = paddle.ocr(np.array(image.convert("RGB")), cls=True)
                lines, confs = [], []
                for bbox, (text, conf) in (results[0] or []):
                    lines.append(text)
                    confs.append(conf)
                return OCRResult("\n".join(lines), float(np.mean(confs)) if confs else 0.0, "paddleocr")
            except Exception as e:
                logger.warning(f"PaddleOCR inference failed: {e}")

        try:
            import pytesseract

            data = pytesseract.image_to_data(prepared, output_type=pytesseract.Output.DICT, config="--psm 4")
            words, lines, confs = [], {}, []
            for i, text in enumerate(data["text"]):
                conf = float(data["conf"][i])
                if not text.strip() or conf < 0:
                    continue
                x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
                words.append({"text": text, "bbox": [x / sx, y / sy, (x + w) / sx, (y + h) / sy],
                              "confidence": conf / 100, "page": 0, "unit": "px"})
                lines.setdefault((data["block_num"][i], data["par_num"][i], data["line_num"][i]), []).append(text)
                confs.append(conf / 100)
            text = "\n".join(" ".join(ws) for ws in lines.values())
            return OCRResult(text, round(float(np.mean(confs)), 3) if confs else 0.0, "tesseract", words)
        except Exception:
            logger.warning("No OCR engine available for raster input; returning empty text.")
            return OCRResult("", 0.0, "none")


ocr_engine = OCREngine()
