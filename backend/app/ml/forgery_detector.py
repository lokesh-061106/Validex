"""Document tampering indicators (advisory, evidence-linked).

Digital PDFs are checked structurally, which is far more reliable than pixel forensics on a
rendered page:
  * cover-up boxes: an opaque white shape drawn *after* existing text (whiteout edit)
  * overlapping text: two text runs occupying the same position (old value left underneath)
  * font / baseline inconsistency of a date or number against its neighbours on the line
  * incremental updates: the file was re-saved after creation
  * metadata: editing tools in Creator/Producer, modification long after creation

Raster images (photos, scans, JPEG pages inside PDFs) get:
  * Error Level Analysis normalised by local edge energy (JPEG only; weak signal)
  * copy-move detection via ORB matches clustered by a common displacement
  * EXIF editing-software traces

Each indicator carries a strength (weak/medium/strong), a plain-language reason and, where
possible, a bounding box normalised to the page (0..1). Results are preliminary indicators
for human verification, never proof of forgery.
"""

import base64
import io
import logging
import re
from collections import Counter, defaultdict
from typing import Any

import fitz
import numpy as np
from PIL import Image, ImageDraw, ExifTags

logger = logging.getLogger(__name__)

try:
    import cv2
    HAS_OPENCV = True
except ImportError:  # pragma: no cover
    HAS_OPENCV = False

STRENGTH_POINTS = {"weak": 10, "medium": 25, "strong": 45}
EDITING_TOOLS = [
    "photoshop", "gimp", "canva", "sejda", "pdfescape", "ilovepdf", "smallpdf", "nitro",
    "foxit phantom", "inkscape", "illustrator", "coreldraw", "pixlr", "paint.net", "pdf-xchange editor",
]
DIGITS = re.compile(r"\d")


def _family(font: str) -> str:
    """Font family without style suffixes or subset prefix (ABCDEF+Helvetica-Bold -> helvetica)."""
    f = font.split("+")[-1].lower()
    f = re.split(r"[-,]", f)[0]
    for suffix in ("bold", "italic", "oblique", "regular", "mt", "ps"):
        f = f.replace(suffix, "")
    return f.strip()


def _norm_box(rect, width: float, height: float, page: int = 0, label: str = "") -> dict[str, Any]:
    x0, y0, x1, y1 = rect
    return {
        "page": page,
        "x": round(max(x0, 0) / width, 4),
        "y": round(max(y0, 0) / height, 4),
        "w": round((x1 - x0) / width, 4),
        "h": round((y1 - y0) / height, 4),
        "label": label,
    }


def _overlap_ratio(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max((a[2] - a[0]) * (a[3] - a[1]), 1e-6)
    return (ix * iy) / area


class ForgeryReport:
    def __init__(self, indicators: list[dict[str, Any]], evidence_image: str | None, heatmap: str | None,
                 metadata: dict[str, Any], checks_run: list[str]):
        self.indicators = indicators
        self.evidence_image = evidence_image
        self.heatmap = heatmap
        self.metadata = metadata
        self.checks_run = checks_run
        points = sum(STRENGTH_POINTS[i["strength"]] for i in indicators)
        self.forgery_score = float(min(points, 100))
        has_strong = any(i["strength"] == "strong" for i in indicators)
        if has_strong or self.forgery_score >= 60:
            self.level = "high"
        elif self.forgery_score >= 25:
            self.level = "medium"
        elif self.forgery_score > 0:
            self.level = "low"
        else:
            self.level = "none"

    @property
    def is_tampered(self) -> bool:
        """'Suspected' — enough independent evidence to ask a human to look."""
        return self.level in ("medium", "high")

    @property
    def tampered_regions(self) -> list[dict[str, Any]]:
        return [b for i in self.indicators for b in i.get("boxes", [])]

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_suspected": self.is_tampered,
            "level": self.level,
            "forgery_score": self.forgery_score,
            "indicators": self.indicators,
            "checks_run": self.checks_run,
            "metadata": self.metadata,
            "disclaimer": "Preliminary indicators for human verification; not proof of forgery.",
        }


class ForgeryDetector:
    def analyze_document(self, file_bytes: bytes, filename: str = "") -> ForgeryReport:
        is_pdf = file_bytes[:5] == b"%PDF-" or filename.lower().endswith(".pdf")
        try:
            if is_pdf:
                return self._analyze_pdf(file_bytes)
            return self._analyze_image_file(file_bytes)
        except Exception as e:
            logger.exception(f"Forensics failed: {e}")
            return ForgeryReport(
                [{"method": "Forensics", "strength": "weak", "description": f"Analysis could not complete: {e}", "boxes": []}],
                None, None, {}, ["error"],
            )

    # ------------------------------------------------------------------ PDF
    def _analyze_pdf(self, pdf_bytes: bytes) -> ForgeryReport:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        indicators: list[dict[str, Any]] = []
        checks = ["metadata", "incremental_updates", "cover_up_boxes", "overlapping_text", "font_consistency"]
        meta = {k: v for k, v in (doc.metadata or {}).items() if v}

        indicators += self._pdf_metadata(meta)
        indicators += self._pdf_revisions(pdf_bytes, doc)

        heatmap = None
        for pno, page in enumerate(doc):
            if pno >= 5:
                break
            w, h = page.rect.width, page.rect.height
            spans = self._text_spans(page)
            indicators += self._cover_ups(page, spans, pno, w, h)
            indicators += self._overlapping_text(spans, pno, w, h)
            indicators += self._font_inconsistency(spans, pno, w, h)

            # Scanned pages: run raster checks on embedded JPEG images
            if not spans:
                for img in page.get_images(full=True)[:2]:
                    info = doc.extract_image(img[0])
                    if info.get("ext") in ("jpeg", "jpg"):
                        checks.append("ela_embedded_jpeg")
                        image = Image.open(io.BytesIO(info["image"]))
                        img_ind, heatmap = self._raster_checks(image, is_jpeg=True, page=pno)
                        indicators += img_ind

        evidence = self._render_evidence(doc, indicators)
        return ForgeryReport(indicators, evidence, heatmap, meta, checks)

    @staticmethod
    def _pdf_metadata(meta: dict[str, Any]) -> list[dict[str, Any]]:
        out = []
        tools = " ".join(str(meta.get(k, "")) for k in ("creator", "producer")).lower()
        for tool in EDITING_TOOLS:
            if tool in tools:
                out.append({
                    "method": "Metadata forensics",
                    "strength": "medium",
                    "description": f"File was produced or edited with '{tool.title()}' (Creator/Producer: "
                                   f"{meta.get('creator', '-')} / {meta.get('producer', '-')}). Official certificates "
                                   "are normally generated by the issuing system, not edited in such tools.",
                    "boxes": [],
                })
                break
        c, m = meta.get("creationDate", ""), meta.get("modDate", "")
        cd, md = re.sub(r"\D", "", c)[:8], re.sub(r"\D", "", m)[:8]
        if len(cd) == 8 and len(md) == 8 and md > cd:
            from datetime import datetime
            try:
                gap = (datetime.strptime(md, "%Y%m%d") - datetime.strptime(cd, "%Y%m%d")).days
                if gap > 30:
                    out.append({
                        "method": "Metadata forensics",
                        "strength": "weak",
                        "description": f"Modified {gap} days after creation (created {cd[:4]}-{cd[4:6]}-{cd[6:]}, "
                                       f"modified {md[:4]}-{md[4:6]}-{md[6:]}).",
                        "boxes": [],
                    })
            except ValueError:
                pass
        return out

    @staticmethod
    def _pdf_revisions(pdf_bytes: bytes, doc) -> list[dict[str, Any]]:
        revisions = len(re.findall(rb"%%EOF", pdf_bytes))
        if revisions <= 1:
            return []
        signed = bool(doc.get_sigflags() > 0) if hasattr(doc, "get_sigflags") else False
        return [{
            "method": "PDF revision history",
            "strength": "weak" if signed else "medium",
            "description": f"The file contains {revisions} saved revisions: content was changed after the document "
                           "was first produced." + (" (Digitally signed PDFs also append revisions.)" if signed else ""),
            "boxes": [],
        }]

    @staticmethod
    def _text_spans(page) -> list[dict[str, Any]]:
        spans = []
        try:
            trace = page.get_texttrace()
        except Exception:
            trace = []
        for s in trace:
            chars = [(chr(c[0]), tuple(c[3])) for c in s.get("chars", []) if c[0] >= 32]
            text = "".join(ch for ch, _ in chars)
            if not text.strip():
                continue
            spans.append({
                "text": text, "chars": chars, "bbox": tuple(s["bbox"]), "font": s.get("font", ""),
                "size": round(s.get("size", 0), 1), "seqno": s.get("seqno", 0), "color": s.get("color"),
            })
        return spans

    @staticmethod
    def _chars_inside(span, rect) -> str:
        """Characters of a span whose centre lies inside rect."""
        out = []
        for ch, (x0, y0, x1, y1) in span["chars"]:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            if rect[0] <= cx <= rect[2] and rect[1] <= cy <= rect[3]:
                out.append(ch)
        return "".join(out).strip()

    def _cover_ups(self, page, spans, pno, w, h) -> list[dict[str, Any]]:
        out = []
        for d in page.get_drawings():
            fill = d.get("fill")
            if not fill or min(fill) < 0.95 or (d.get("fill_opacity") or 1) < 0.9:
                continue
            r = d["rect"]
            rect = (r.x0, r.y0, r.x1, r.y1)
            if (r.x1 - r.x0) * (r.y1 - r.y0) > 0.25 * w * h:
                continue  # page background
            seq = d.get("seqno", 0)
            hidden_text = " ".join(t for t in (self._chars_inside(s, rect) for s in spans if s["seqno"] < seq) if t)
            if len(hidden_text.replace(" ", "")) < 2:
                continue
            new_text = " ".join(t for t in (self._chars_inside(s, rect) for s in spans if s["seqno"] > seq) if t)
            desc = f"An opaque white box was drawn over existing text '{hidden_text[:120]}'"
            desc += f" and new text '{new_text[:120]}' was written on top of it." if new_text else "."
            out.append({
                "method": "Cover-up detection",
                "strength": "strong",
                "description": desc,
                "hidden_text": hidden_text[:120],
                "visible_text": new_text[:120] or None,
                "boxes": [_norm_box(rect, w, h, pno, "Covered text")],
            })
        return out

    def _overlapping_text(self, spans, pno, w, h) -> list[dict[str, Any]]:
        out = []
        for i, a in enumerate(spans):
            for b in spans[i + 1:]:
                under, over = (a, b) if a["seqno"] < b["seqno"] else (b, a)
                if _overlap_ratio(over["bbox"], under["bbox"]) < 0.5:
                    continue
                hidden = self._chars_inside(under, over["bbox"])
                if len(hidden.replace(" ", "")) < 3 or hidden == over["text"].strip():
                    continue  # identical text = fake-bold / shadow rendering, not an edit
                out.append({
                    "method": "Overlapping text layers",
                    "strength": "strong",
                    "description": f"Two different texts occupy the same position: '{hidden}' (earlier layer) "
                                   f"is underneath '{over['text'].strip()}' (later layer).",
                    "hidden_text": hidden,
                    "visible_text": over["text"].strip(),
                    "boxes": [_norm_box(over["bbox"], w, h, pno, "Overlapping text")],
                })
        return out

    def _font_inconsistency(self, spans, pno, w, h) -> list[dict[str, Any]]:
        out = []
        for s in spans:
            if not DIGITS.search(s["text"]):
                continue
            covered_later = any(
                n["seqno"] > s["seqno"] and _overlap_ratio(n["bbox"], s["bbox"]) > 0.5 for n in spans
            )
            if covered_later:
                continue  # the hidden original; the visible replacement is the one to judge
            neighbours = [
                n for n in spans
                if n is not s
                and n["text"].strip() != s["text"].strip()
                and abs(n["bbox"][3] - s["bbox"][3]) < 3.0
                and max(0.0, max(n["bbox"][0], s["bbox"][0]) - min(n["bbox"][2], s["bbox"][2])) < 80
            ]
            if not neighbours:
                continue
            weights = Counter()
            for n in neighbours:
                weights[(_family(n["font"]), n["size"])] += len(n["text"])
            (fam, size), _ = weights.most_common(1)[0]
            reasons = []
            if _family(s["font"]) != fam:
                reasons.append(f"font '{s['font']}' differs from the surrounding '{fam}'")
            if abs(s["size"] - size) > 0.6:
                reasons.append(f"size {s['size']}pt vs {size}pt around it")
            base_diff = min(abs(n["bbox"][3] - s["bbox"][3]) for n in neighbours)
            if 0.8 < base_diff < 3.0 and not reasons:
                reasons.append(f"baseline shifted by {base_diff:.1f}pt from the rest of the line")
            if reasons:
                out.append({
                    "method": "Font consistency",
                    "strength": "medium" if len(reasons) == 1 else "strong",
                    "description": f"The value '{s['text'].strip()}' does not match the typography of its line: "
                                   + "; ".join(reasons) + ".",
                    "boxes": [_norm_box(s["bbox"], w, h, pno, "Inconsistent typography")],
                })
        return out

    def _render_evidence(self, doc, indicators) -> str | None:
        boxes = [b for i in indicators for b in i.get("boxes", []) if b.get("page", 0) == 0]
        if not boxes:
            return None
        page = doc[0]
        pix = page.get_pixmap(dpi=110)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        draw = ImageDraw.Draw(img)
        for b in boxes:
            x0, y0 = b["x"] * img.width, b["y"] * img.height
            x1, y1 = x0 + b["w"] * img.width, y0 + b["h"] * img.height
            draw.rectangle([x0 - 3, y0 - 3, x1 + 3, y1 + 3], outline=(225, 29, 72), width=3)
        return _to_data_uri(img)

    # ---------------------------------------------------------------- Images
    def _analyze_image_file(self, file_bytes: bytes) -> ForgeryReport:
        image = Image.open(io.BytesIO(file_bytes))
        is_jpeg = (image.format or "").upper() in ("JPEG", "JPG")
        indicators = self._exif_checks(image)
        raster, heatmap = self._raster_checks(image, is_jpeg=is_jpeg, page=0)
        indicators += raster
        evidence = None
        boxes = [b for i in indicators for b in i.get("boxes", [])]
        if boxes:
            img = image.convert("RGB")
            img.thumbnail((WORK_MAX_SIDE, WORK_MAX_SIDE))
            draw = ImageDraw.Draw(img)
            for b in boxes:
                x0, y0 = b["x"] * img.width, b["y"] * img.height
                draw.rectangle([x0, y0, x0 + b["w"] * img.width, y0 + b["h"] * img.height], outline=(225, 29, 72), width=4)
            evidence = _to_data_uri(img)
        big = image.size[0] * image.size[1] > ELA_MAX_PIXELS
        checks = ["exif", "noise", "copy_move"] + (["ela_skipped_large_image" if big else "ela"] if is_jpeg else [])
        return ForgeryReport(indicators, evidence, heatmap, {"format": image.format, "size": image.size}, checks)

    @staticmethod
    def _exif_checks(image: Image.Image) -> list[dict[str, Any]]:
        try:
            exif = {ExifTags.TAGS.get(k, k): v for k, v in (image.getexif() or {}).items()}
        except Exception:
            return []
        software = str(exif.get("Software", "")).lower()
        for tool in EDITING_TOOLS:
            if tool in software:
                return [{
                    "method": "EXIF metadata",
                    "strength": "medium",
                    "description": f"Image EXIF 'Software' tag shows it was saved by '{exif.get('Software')}'.",
                    "boxes": [],
                }]
        return []

    def _raster_checks(self, image: Image.Image, is_jpeg: bool, page: int) -> tuple[list[dict[str, Any]], str | None]:
        if not HAS_OPENCV:
            return [], None
        rgb = np.array(image.convert("RGB"))
        # Geometry-based checks run on a bounded copy so 12-MP phone photos stay within small-host memory;
        # boxes are normalised, so they map back onto the original
        work = _downscale(rgb, WORK_MAX_SIDE)
        out, heatmap = [], None
        # ELA is a weak signal aimed at scans (~4 MP); skip it on large camera photos to bound memory
        if is_jpeg and rgb.shape[0] * rgb.shape[1] <= ELA_MAX_PIXELS:
            ela, heatmap = self._ela(image, rgb, work, page)
            out += ela
        # Noise statistics need native pixels: decimate (no averaging) only when very large
        noise_img = _downscale(rgb, NOISE_MAX_SIDE, interpolation=cv2.INTER_NEAREST)
        del rgb
        out += self._noise_consistency(noise_img, page)
        del noise_img
        out += self._copy_move(work, page)
        return out, heatmap

    @staticmethod
    def _noise_consistency(rgb: np.ndarray, page: int, block: int = 16) -> list[dict[str, Any]]:
        """Find regions whose sensor/scan noise is far lower than the rest of the page.

        Content pasted from a digital source into a camera photo or scan is unnaturally clean.
        Abstains on heavily compressed or born-digital images where noise is not measurable.
        """
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
        residual = gray - cv2.GaussianBlur(gray, (0, 0), 1.2)
        hb, wb = gray.shape[0] // block, gray.shape[1] // block
        if hb < 4 or wb < 4:
            return []
        res = residual[: hb * block, : wb * block].reshape(hb, block, wb, block).transpose(0, 2, 1, 3).reshape(hb, wb, -1)
        img = gray[: hb * block, : wb * block].reshape(hb, block, wb, block)
        # Only judge background-like blocks (bright, flat) where noise is measurable
        background = (img.mean(axis=(1, 3)) > 150) & ((img.max(axis=(1, 3)) - img.min(axis=(1, 3))) < 60)
        sigma = (np.percentile(res, 95, axis=2) - np.percentile(res, 5, axis=2)) / 3.29
        if background.sum() < 50:
            return []
        page_sigma = float(np.median(sigma[background]))
        if page_sigma < 0.9:
            return []
        clean = (background & (sigma < page_sigma * 0.3)).astype(np.uint8)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(clean, connectivity=4)
        H, W = gray.shape
        out = []
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            # A flat region the size of a whole margin is natural; a small isolated patch is not
            if area < 3 or area > 0.05 * background.sum():
                continue
            out.append({
                "method": "Noise consistency",
                "strength": "medium",
                "description": f"A {bw * block}x{bh * block}px region has almost no scan/camera noise "
                               f"(σ≈{float(sigma[labels == i].mean()):.1f} vs {page_sigma:.1f} on the rest of the page), "
                               "typical of digitally pasted content.",
                "boxes": [_norm_box((x * block, y * block, (x + bw) * block, (y + bh) * block), W, H, page, "Noise anomaly")],
            })
        return out[:3]

    @staticmethod
    def _ela(image: Image.Image, rgb: np.ndarray, work: np.ndarray, page: int, block: int = 16):
        """ELA needs the original pixels (the JPEG grid), so it is computed in horizontal strips to
        bound memory; only per-block means are kept."""
        buf = io.BytesIO()
        image.convert("RGB").save(buf, "JPEG", quality=90)
        resaved = np.array(Image.open(io.BytesIO(buf.getvalue())).convert("RGB"))
        H, W = rgb.shape[:2]
        hb, wb = H // block, W // block
        if hb < 4 or wb < 4:
            return [], None
        d = np.zeros((hb, wb), np.float32)
        g = np.zeros((hb, wb), np.float32)
        rows = block * 32
        for y0 in range(0, hb * block, rows):
            y1 = min(y0 + rows, hb * block)
            a = rgb[y0:y1, : wb * block].astype(np.int16)
            b = resaved[y0:y1, : wb * block].astype(np.int16)
            diff = np.abs(a - b).mean(axis=2, dtype=np.float32)
            gray = cv2.cvtColor(rgb[y0:y1, : wb * block], cv2.COLOR_RGB2GRAY).astype(np.float32)
            grad = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0), cv2.Sobel(gray, cv2.CV_32F, 0, 1))
            nb = (y1 - y0) // block
            d[y0 // block: y0 // block + nb] = diff.reshape(nb, block, wb, block).mean(axis=(1, 3))
            g[y0 // block: y0 // block + nb] = grad.reshape(nb, block, wb, block).mean(axis=(1, 3))
        del resaved
        diff = d  # per-block values from here on
        content = g > 8.0
        if content.sum() < 20:
            return [], None
        ratio = d / (g + 1.0)
        vals = ratio[content]
        med = float(np.median(vals))
        mad = float(np.median(np.abs(vals - med))) * 1.4826 + 1e-6
        z = np.where(content, (ratio - med) / mad, 0)
        suspicious = (z > 8.0).astype(np.uint8)

        # Heatmap for the reviewer regardless of verdict
        zmap = np.clip(z / 10.0, 0, 1)
        zmap = cv2.resize((zmap * 255).astype(np.uint8), (work.shape[1], work.shape[0]), interpolation=cv2.INTER_NEAREST)
        heat = cv2.applyColorMap(zmap, cv2.COLORMAP_JET)[:, :, ::-1]
        blend = (work * 0.6 + heat * 0.4).astype(np.uint8)
        heatmap = _to_data_uri(Image.fromarray(blend))

        n, labels, stats, _ = cv2.connectedComponentsWithStats(suspicious, connectivity=8)
        out: list[dict[str, Any]] = []
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            if area < 6:
                continue
            region_z = float(z[labels == i].mean())
            out.append({
                "method": "Error Level Analysis",
                "strength": "weak",
                "description": f"A {bw * block}x{bh * block}px region recompresses differently from the rest of the "
                               f"image (≈{region_z:.0f}σ above the page norm), as happens when content is pasted in. "
                               "ELA alone is unreliable on rescanned files.",
                "boxes": [_norm_box((x * block, y * block, (x + bw) * block, (y + bh) * block), W, H, page, "ELA anomaly")],
            })
        # ELA is a weak, supporting signal: report at most the single most anomalous region
        return out[:1], heatmap

    @staticmethod
    def _copy_move(rgb: np.ndarray, page: int) -> list[dict[str, Any]]:
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        H, W = gray.shape
        orb = cv2.ORB_create(nfeatures=15000, fastThreshold=10)
        kps, des = orb.detectAndCompute(gray, None)
        if des is None or len(des) < 50:
            return []
        matches = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(des, des, k=8)
        votes: dict[tuple[int, int], list] = defaultdict(list)
        for m in matches:
            for cand in m[1:]:
                if cand.distance > 32:
                    continue
                p1, p2 = np.array(kps[cand.queryIdx].pt), np.array(kps[cand.trainIdx].pt)
                dx, dy = p2 - p1
                if np.hypot(dx, dy) < 50:
                    continue
                if dx < 0 or (dx == 0 and dy < 0):  # count each pair once
                    continue
                votes[(int(round(dx / 6)), int(round(dy / 6)))].append((p1, p2))
        out: list[dict[str, Any]] = []
        tried: set[tuple[int, int]] = set()
        # ORB votes only propose candidate offsets; each is verified by dense correlation of a
        # window of at least 96x96 px around the matched features. A real clone correlates over the
        # whole window; repeated words or ruled lines stop correlating once their surroundings are included.
        for (qx, qy), pairs in sorted(votes.items(), key=lambda kv: -len(kv[1]))[:120]:
            if len(pairs) < 4:
                break
            src = np.array([p[0] for p in pairs])
            dst = np.array([p[1] for p in pairs])
            offset = np.median(dst - src, axis=0)
            key = (int(offset[0] // 4), int(offset[1] // 4))
            if key in tried:
                continue
            tried.add(key)
            sx0, sy0 = src.min(axis=0)
            sx1, sy1 = src.max(axis=0)
            if (sx1 - sx0) > 0.35 * W or (sy1 - sy0) > 0.35 * H:
                continue
            cx, cy = (sx0 + sx1) / 2, (sy0 + sy1) / 2
            half_w = int(min(max((sx1 - sx0) / 2 + 24, 48), 150))
            half_h = int(min(max((sy1 - sy0) / 2 + 24, 48), 150))
            x0, y0, x1, y1 = int(cx - half_w), int(cy - half_h), int(cx + half_w), int(cy + half_h)
            tx, ty = int(round(x0 + offset[0])), int(round(y0 + offset[1]))
            if x0 < 0 or y0 < 0 or x1 > W or y1 > H or tx < 0 or ty < 0 or tx + (x1 - x0) > W or ty + (y1 - y0) > H:
                continue
            if abs(tx - x0) < (x1 - x0) and abs(ty - y0) < (y1 - y0):
                continue  # overlapping windows (texture self-similarity), not a moved region
            a = gray[y0:y1, x0:x1].astype(np.float32)
            b = gray[ty:ty + (y1 - y0), tx:tx + (x1 - x0)].astype(np.float32)
            if a.std() < 20 or b.std() < 20:
                continue
            ncc = float(((a - a.mean()) * (b - b.mean())).mean() / (a.std() * b.std() + 1e-6))
            if ncc < 0.9:
                continue  # features coincide but the surrounding pixels differ: not a clone
            # Natural look-alikes (two similar edges) carry independent noise; a copied region carries
            # the same noise. Correlate the high-pass residual to tell them apart.
            ra, rb = a - cv2.GaussianBlur(a, (0, 0), 1.5), b - cv2.GaussianBlur(b, (0, 0), 1.5)
            residual_ncc = float(((ra - ra.mean()) * (rb - rb.mean())).mean() / (ra.std() * rb.std() + 1e-6))
            if residual_ncc < 0.6:
                continue
            sw, sh = x1 - x0, y1 - y0
            sx0, sy0, sx1, sy1 = x0, y0, x1, y1
            dx0, dy0, dx1, dy1 = tx, ty, tx + sw, ty + sh
            out.append({
                "method": "Copy-move detection",
                "strength": "strong" if ncc > 0.96 else "medium",
                "description": f"A {int(sw)}x{int(sh)}px region is repeated elsewhere with the same offset "
                               f"({int(offset[0])}px, {int(offset[1])}px), pixel correlation {ncc:.2f} over "
                               f"{len(pairs)} matching features: a stamp or signature appears to have been duplicated.",
                "boxes": [
                    _norm_box((sx0, sy0, sx1, sy1), W, H, page, "Source region"),
                    _norm_box((dx0, dy0, dx1, dy1), W, H, page, "Duplicated region"),
                ],
            })
        return out


WORK_MAX_SIDE = 1600
NOISE_MAX_SIDE = 2400
ELA_MAX_PIXELS = 8_000_000


def _downscale(rgb: np.ndarray, max_side: int, interpolation: int | None = None) -> np.ndarray:
    h, w = rgb.shape[:2]
    if max(h, w) <= max_side:
        return rgb
    r = max_side / max(h, w)
    return cv2.resize(rgb, (int(w * r), int(h * r)), interpolation=cv2.INTER_AREA if interpolation is None else interpolation)


def _to_data_uri(img: Image.Image, max_width: int = 1000) -> str:
    if img.width > max_width:
        img = img.resize((max_width, int(img.height * max_width / img.width)))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


forgery_detector = ForgeryDetector()
