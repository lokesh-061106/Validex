"""Synthetic document factory for demos and evaluation (all data is fictitious).

Produces certificate-style PDFs with issuer-signed QR codes, scanned-image versions, and tampered
variants using realistic editing techniques:
  * whiteout   - white box over a value, new value typed on top (online PDF editors)
  * redact     - value properly removed, replacement typed in a different font
  * overlay    - new value typed over the old one without hiding it
  * metadata   - re-saved through an online editor (Producer + incremental revision)
  * paste      - (scans) digitally clean patch pasted onto a noisy scan
  * clone      - (scans) stamp/seal duplicated within the page
"""

import io
import os
import sys

import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend")))

import cv2  # noqa: E402
from app.mock_authority.keys import sign_payload  # noqa: E402

A4 = (595, 842)


def qr_png(text: str, scale: int = 6) -> bytes:
    enc = cv2.QRCodeEncoder.create()
    m = enc.encode(text)
    m = cv2.resize(m, (m.shape[1] * scale, m.shape[0] * scale), interpolation=cv2.INTER_NEAREST)
    m = cv2.copyMakeBorder(m, 4 * scale, 4 * scale, 4 * scale, 4 * scale, cv2.BORDER_CONSTANT, value=255)
    ok, buf = cv2.imencode(".png", m)
    return buf.tobytes()


def make_certificate(title: str, subtitle: str, lines: list[str], qr: tuple[str, dict] | None = None,
                     table: list[list[str]] | None = None, seal_text: str = "OFFICIAL SEAL", producer: str = "Validex Issuer System") -> bytes:
    """A one-page certificate. qr = (issuer, data) produces an Ed25519-signed QR code."""
    doc = fitz.open()
    page = doc.new_page(width=A4[0], height=A4[1])
    page.draw_rect(fitz.Rect(24, 24, 571, 818), color=(0.15, 0.2, 0.45), width=2)
    page.draw_rect(fitz.Rect(30, 30, 565, 812), color=(0.15, 0.2, 0.45), width=0.5)
    page.draw_circle(fitz.Point(70, 78), 26, color=(0.15, 0.2, 0.45), width=1.5)
    page.insert_text((58, 82), "GOI", fontsize=10, fontname="hebo", color=(0.15, 0.2, 0.45))
    page.insert_text((110, 72), title, fontsize=13, fontname="hebo", color=(0.1, 0.12, 0.4))
    page.insert_text((110, 92), subtitle, fontsize=9.5, fontname="helv", color=(0.3, 0.3, 0.3))
    page.draw_line(fitz.Point(40, 115), fitz.Point(555, 115), color=(0.75, 0.35, 0.1), width=1.2)

    y = 150
    for line in lines:
        if line.startswith("## "):
            y += 8
            page.insert_text((50, y), line[3:], fontsize=11.5, fontname="hebo", color=(0.15, 0.15, 0.15))
            y += 22
        else:
            for chunk in _wrap(line, 92):
                page.insert_text((50, y), chunk, fontsize=10, fontname="helv", color=(0.08, 0.08, 0.08))
                y += 17
    if table:
        y += 8
        col_w = (495) / len(table[0])
        row_h = 18 if len(table) <= 20 else 13
        size = 8.5 if len(table) <= 20 else 6.8
        for r, row in enumerate(table):
            if y + row_h > (640 if page.number == 0 else 800):  # continue the table on a new page
                page = doc.new_page(width=A4[0], height=A4[1])
                page.insert_text((50, 50), title + " (continued)", fontsize=9, fontname="hebo", color=(0.1, 0.12, 0.4))
                y = 62
            for c, cell in enumerate(row):
                rect = fitz.Rect(50 + c * col_w, y, 50 + (c + 1) * col_w, y + row_h)
                page.draw_rect(rect, color=(0.6, 0.6, 0.6), width=0.5)
                page.insert_text((rect.x0 + 3, rect.y1 - 3.5), cell, fontsize=size, fontname="hebo" if r == 0 else "helv")
            y += row_h
    page = doc[0]

    # Seal and signature
    page.draw_circle(fitz.Point(470, 700), 42, color=(0.2, 0.25, 0.65), width=2)
    page.draw_circle(fitz.Point(470, 700), 32, color=(0.2, 0.25, 0.65), width=0.8)
    page.insert_text((436, 703), seal_text[:14], fontsize=7.5, fontname="hebo", color=(0.2, 0.25, 0.65))
    page.draw_line(fitz.Point(330, 760), fitz.Point(545, 760), color=(0.3, 0.3, 0.3), width=0.6)
    page.insert_text((360, 775), "Authorised Signatory", fontsize=9, fontname="helv")
    if qr:
        issuer, data = qr
        page.insert_image(fitz.Rect(50, 655, 160, 765), stream=qr_png(sign_payload(issuer, data)))
        page.insert_text((50, 778), "Scan to verify (issuer-signed)", fontsize=7, fontname="helv", color=(0.35, 0.35, 0.35))
    page.insert_text((50, 800), "Synthetic document generated for the Validex prototype. Not a real certificate.",
                     fontsize=6.5, fontname="helv", color=(0.5, 0.5, 0.5))
    doc.set_metadata({"producer": producer, "creator": producer, "creationDate": "D:20260110100000+05'30'",
                      "modDate": "D:20260110100000+05'30'"})
    return doc.tobytes(garbage=3, deflate=True)


def _wrap(text: str, width: int) -> list[str]:
    words, out, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return out + ([cur] if cur else [])


# ------------------------------------------------------------------ PDF tampering

def tamper_whiteout(pdf: bytes, old: str, new: str, font: str = "tiro", size_delta: float = 0.5) -> bytes:
    doc = fitz.open(stream=pdf, filetype="pdf")
    page = doc[0]
    hit = page.search_for(old)[0]
    page.draw_rect(hit + (-1, -1, 1, 1), color=None, fill=(1, 1, 1), overlay=True)
    page.insert_text((hit.x0, hit.y1 - 2.2), new, fontsize=10 + size_delta, fontname=font)
    doc.set_metadata({**doc.metadata, "producer": "PDFescape Online", "modDate": "D:20261012120000+05'30'"})
    return doc.tobytes()


def tamper_redact(pdf: bytes, old: str, new: str, font: str = "cour") -> bytes:
    doc = fitz.open(stream=pdf, filetype="pdf")
    page = doc[0]
    hit = page.search_for(old)[0]
    page.add_redact_annot(hit, fill=(1, 1, 1))
    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)
    page.insert_text((hit.x0, hit.y1 - 2.2), new, fontsize=9.6, fontname=font)
    return doc.tobytes()


def tamper_overlay(pdf: bytes, old: str, new: str) -> bytes:
    doc = fitz.open(stream=pdf, filetype="pdf")
    page = doc[0]
    hit = page.search_for(old)[0]
    page.insert_text((hit.x0, hit.y1 - 2.0), new, fontsize=10, fontname="helv")
    return doc.tobytes()


def tamper_metadata(pdf: bytes) -> bytes:
    doc = fitz.open(stream=pdf, filetype="pdf")
    buf = io.BytesIO()
    doc.save(buf)
    doc = fitz.open(stream=buf.getvalue(), filetype="pdf")
    doc.set_metadata({**doc.metadata, "producer": "iLovePDF", "modDate": "D:20261015100000+05'30'"})
    tmp = os.path.join(os.environ.get("TEMP", "/tmp"), f"vx_inc_{os.getpid()}.pdf")
    with open(tmp, "wb") as f:
        f.write(buf.getvalue())
    d2 = fitz.open(tmp)
    d2.set_metadata({**d2.metadata, "producer": "iLovePDF", "modDate": "D:20261015100000+05'30'"})
    d2.saveIncr()
    d2.close()
    with open(tmp, "rb") as f:
        out = f.read()
    os.remove(tmp)
    return out


# ------------------------------------------------------------------ scans

def render(pdf: bytes, dpi: int = 150) -> Image.Image:
    return Image.open(io.BytesIO(fitz.open(stream=pdf, filetype="pdf")[0].get_pixmap(dpi=dpi).tobytes("png"))).convert("RGB")


def scan(img: Image.Image, seed: int, noise: float = 5.0, quality: int = 88, angle: float = 0.0) -> bytes:
    a = np.array(img).astype(np.float32) * 0.92 + 4
    a += np.random.RandomState(seed).normal(0, noise, a.shape)
    out = Image.fromarray(a.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))
    if angle:
        out = out.rotate(angle, fillcolor=(238, 238, 238), resample=Image.Resampling.BICUBIC)
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def scan_paste(scan_bytes: bytes, box: tuple[int, int, int, int], text: str, quality: int = 90) -> bytes:
    im = Image.open(io.BytesIO(scan_bytes)).convert("RGB")
    d = ImageDraw.Draw(im)
    d.rectangle(box, fill=(238, 238, 238))
    d.text((box[0] + 4, box[1] + 6), text, fill=(20, 20, 20))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def scan_clone(scan_bytes: bytes, src: tuple[int, int, int, int], dest: tuple[int, int], quality: int = 90) -> bytes:
    im = Image.open(io.BytesIO(scan_bytes)).convert("RGB")
    im.paste(im.crop(src), dest)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def lab_placeholder(seed: int, label: str) -> bytes:
    """Placeholder 'lab photo' (no real equipment). Replace with real photos in sample_docs/lab_photos/."""
    rs = np.random.RandomState(seed)
    w, h = 1280, 860
    img = Image.new("RGB", (w, h), tuple(int(v) for v in rs.randint(170, 220, 3)))
    d = ImageDraw.Draw(img)
    for _ in range(40):
        x, y = rs.randint(0, w), rs.randint(0, h)
        d.rectangle((x, y, x + rs.randint(40, 220), y + rs.randint(30, 160)), fill=tuple(int(v) for v in rs.randint(30, 230, 3)))
    d.text((30, 30), f"PLACEHOLDER LAB PHOTO - {label}", fill=(0, 0, 0))
    a = np.array(img.filter(ImageFilter.GaussianBlur(2))).astype(np.float32) + rs.normal(0, 4, (h, w, 3))
    buf = io.BytesIO()
    Image.fromarray(a.clip(0, 255).astype(np.uint8)).save(buf, "JPEG", quality=90)
    return buf.getvalue()


def recompress_resize(jpeg: bytes, scale: float = 0.8, quality: int = 75) -> bytes:
    im = Image.open(io.BytesIO(jpeg)).convert("RGB")
    im = im.resize((int(im.width * scale), int(im.height * scale)))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=quality)
    return buf.getvalue()
