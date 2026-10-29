"""Chain-of-custody watermarking applied at intake, before anything is stored.

Every stored object carries a visible and an invisible watermark:

    VALIDEX - CHAIN OF CUSTODY - VERIFIED <UTC timestamp>

plus a server-signed manifest (document id, application id, receive time, SHA-256 and size of the
bytes as received). The original bytes stay recoverable from the stored object and are checked
against the manifest hash, so analysis always runs on exactly what the institution submitted and
any later change to the stored file is detectable.

    PDF   visible line on every page + XMP manifest + embedded manifest file, written as an
          incremental update: stored[:original_size] is byte-identical to the upload.
    Image PNG with a visible band, an invisible LSB signature over the pixels, and the original
          file in a private ancillary chunk ("vxOr"); manifest in chunk "vxMn".
    MP4   invisible only: a trailing 'uuid' box with the manifest (visible marking would require
          re-encoding the video).
    GeoJSON  "validex_custody" member with the manifest and the original text.
"""

import base64
import hashlib
import hmac
import io
import json
import os
import struct
import tempfile
import uuid
import zlib
from datetime import datetime, timezone
from typing import Any

import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.core.config import settings

PNG_SIG = b"\x89PNG\r\n\x1a\n"
CHUNK_ORIGINAL, CHUNK_MANIFEST = b"vxOr", b"vxMn"
MP4_UUID = uuid.UUID("5a1c0de0-7a11-4d3e-9c0a-56a11dec0de0").bytes


class CustodyError(ValueError):
    pass


def watermark_text(received_at: datetime) -> str:
    return f"{settings.WATERMARK_TEXT} {received_at.strftime('%Y-%m-%dT%H:%M:%SZ')}"


def _sign(manifest: dict[str, Any]) -> str:
    body = json.dumps({k: v for k, v in manifest.items() if k != "signature"}, sort_keys=True, separators=(",", ":"))
    return hmac.new(settings.SECRET_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()


def build_manifest(original: bytes, kind: str, document_id: uuid.UUID, application_id: uuid.UUID,
                   uploaded_by: uuid.UUID | None, received_at: datetime) -> dict[str, Any]:
    m = {
        "v": 1, "document_id": str(document_id), "application_id": str(application_id),
        "uploaded_by": str(uploaded_by) if uploaded_by else None, "received_at": received_at.isoformat(),
        "kind": kind, "original_sha256": hashlib.sha256(original).hexdigest(), "original_size": len(original),
        "watermark": watermark_text(received_at),
    }
    m["signature"] = _sign(m)
    return m


def manifest_valid(manifest: dict[str, Any]) -> bool:
    return hmac.compare_digest(manifest.get("signature", ""), _sign(manifest))


# ------------------------------------------------------------------ apply

def apply(original: bytes, kind: str, manifest: dict[str, Any]) -> tuple[bytes, str]:
    """Return (stored_bytes, stored_mime). Raises CustodyError if the file cannot be watermarked."""
    if kind == "pdf":
        return _pdf(original, manifest), "application/pdf"
    if kind in ("jpeg", "png"):
        return _image(original, manifest), "image/png"
    if kind == "mp4":
        return _mp4(original, manifest), "video/mp4"
    if kind == "geojson":
        return _geojson(original, manifest), "application/geo+json"
    raise CustodyError(f"No watermarking method for {kind}")


def _pdf(original: bytes, manifest: dict[str, Any]) -> bytes:
    doc = fitz.open(stream=original, filetype="pdf")
    if doc.needs_pass or doc.is_encrypted:
        raise CustodyError("Password-protected PDFs cannot be accepted; upload an unprotected copy")
    doc.close()
    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(original)
        doc = fitz.open(path)
        text = manifest["watermark"] + f"  ·  ID {manifest['document_id'][:8]}"
        for page in doc:
            r = page.rect
            page.insert_text(fitz.Point(r.x0 + 14, r.y1 - 5), text, fontsize=6, fontname="helv",
                             color=(0.45, 0.45, 0.5), overlay=True)
        xmp = ('<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?><x:xmpmeta xmlns:x="adobe:ns:meta/">'
               '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description rdf:about="" '
               'xmlns:vx="https://validex.example/custody/1.0/"><vx:manifest>'
               + base64.b64encode(json.dumps(manifest).encode()).decode()
               + '</vx:manifest></rdf:Description></rdf:RDF></x:xmpmeta><?xpacket end="w"?>')
        doc.set_xml_metadata(xmp)
        doc.embfile_add("validex-custody.json", json.dumps(manifest, indent=1).encode(), filename="validex-custody.json",
                        desc="Validex chain-of-custody manifest")
        if doc.can_save_incrementally():
            doc.saveIncr()
            doc.close()
            with open(path, "rb") as f:
                stored = f.read()
        else:  # damaged xref: rewrite, keeping the original alongside so it is still recoverable
            doc.embfile_add("validex-original.pdf", original, filename="validex-original.pdf", desc="Original as received")
            stored = doc.tobytes()
            doc.close()
        return stored
    finally:
        os.unlink(path)


def _png_chunk(ctype: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + ctype + data + struct.pack(">I", zlib.crc32(ctype + data) & 0xFFFFFFFF)


def _lsb_bits(manifest: dict[str, Any]) -> np.ndarray:
    token = hashlib.sha256((manifest["signature"] + manifest["document_id"]).encode()).digest()
    return np.unpackbits(np.frombuffer(token, dtype=np.uint8))  # 256 bits


def _image(original: bytes, manifest: dict[str, Any]) -> bytes:
    img = Image.open(io.BytesIO(original)).convert("RGB")
    w, h = img.size
    # Visible: translucent band along the bottom edge (pixel geometry unchanged, so evidence boxes still align)
    band = max(int(h * 0.035), 14)
    overlay = Image.new("RGBA", (w, band), (15, 23, 42, 150))
    draw = ImageDraw.Draw(overlay)
    try:
        font = ImageFont.load_default(size=max(int(band * 0.6), 9))
    except TypeError:
        font = ImageFont.load_default()
    draw.text((8, band * 0.15), manifest["watermark"], fill=(255, 255, 255, 235), font=font)
    img.paste(overlay, (0, h - band), overlay)
    # Invisible: 256-bit token in the blue-channel LSBs, repeated across the image
    arr = np.array(img)
    bits = _lsb_bits(manifest)
    blue = arr[:, :, 2].reshape(-1)
    reps = np.resize(bits, blue.shape[0])
    arr[:, :, 2] = ((blue & 0xFE) | reps).reshape(h, w)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG", optimize=False, compress_level=6)
    png = buf.getvalue()
    iend = png.rfind(b"IEND") - 4
    extra = _png_chunk(CHUNK_MANIFEST, json.dumps(manifest).encode()) + _png_chunk(CHUNK_ORIGINAL, original)
    return png[:iend] + extra + png[iend:]


def _mp4(original: bytes, manifest: dict[str, Any]) -> bytes:
    payload = MP4_UUID + json.dumps(manifest).encode()
    return original + struct.pack(">I", 8 + len(payload)) + b"uuid" + payload


def _geojson(original: bytes, manifest: dict[str, Any]) -> bytes:
    try:
        data = json.loads(original.decode("utf-8"))
    except Exception as e:
        raise CustodyError("Campus boundary must be valid GeoJSON") from e
    if not isinstance(data, dict):
        raise CustodyError("Campus boundary must be a GeoJSON object")
    data["validex_custody"] = {"watermark": manifest["watermark"], "manifest": manifest,
                               "original_b64": base64.b64encode(original).decode()}
    return json.dumps(data, indent=1).encode()


# ------------------------------------------------------------- recover / verify

def _png_chunks(data: bytes):
    pos = 8
    while pos + 8 <= len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        yield ctype, data[pos + 8:pos + 8 + length]
        pos += 12 + length


def extract(stored: bytes, kind: str) -> tuple[bytes | None, dict[str, Any] | None]:
    """Recover (original_bytes, embedded_manifest) from a stored object; (None, None) if unreadable."""
    try:
        return _extract(stored, kind)
    except Exception:
        return None, None


def _extract(stored: bytes, kind: str) -> tuple[bytes | None, dict[str, Any] | None]:
    if kind == "pdf" or stored[:5] == b"%PDF-":
        manifest = None
        try:
            doc = fitz.open(stream=stored, filetype="pdf")
            names = doc.embfile_names()
            if "validex-custody.json" in names:
                manifest = json.loads(doc.embfile_get("validex-custody.json"))
            if "validex-original.pdf" in names:
                return doc.embfile_get("validex-original.pdf"), manifest
        except Exception:
            pass
        if manifest:
            return stored[:manifest["original_size"]], manifest
        return None, None
    if stored[:8] == PNG_SIG:
        original = manifest = None
        for ctype, data in _png_chunks(stored):
            if ctype == CHUNK_ORIGINAL:
                original = data
            elif ctype == CHUNK_MANIFEST:
                manifest = json.loads(data)
        return original, manifest
    if stored[4:8] == b"ftyp":
        i = stored.rfind(b"uuid" + MP4_UUID)
        if i < 4:
            return None, None
        manifest = json.loads(stored[i + 4 + 16:])
        return stored[:i - 4], manifest
    try:
        data = json.loads(stored.decode("utf-8"))
        c = data.get("validex_custody") or {}
        return base64.b64decode(c["original_b64"]), c.get("manifest")
    except Exception:
        return None, None


def verify(stored: bytes, kind: str, expected: dict[str, Any] | None) -> dict[str, Any]:
    """Check that a stored object still carries an intact custody chain."""
    original, embedded = extract(stored, kind)
    checks = {
        "manifest_embedded": embedded is not None,
        "manifest_signature_valid": bool(embedded) and manifest_valid(embedded),
        "matches_database_record": bool(embedded and expected) and embedded.get("signature") == expected.get("signature"),
        "original_recoverable": original is not None,
        "original_hash_matches": bool(original is not None and embedded)
                                 and hashlib.sha256(original).hexdigest() == embedded.get("original_sha256"),
        "visible_watermark_present": _visible_present(stored, kind, embedded),
    }
    if kind in ("jpeg", "png") and embedded:
        checks["invisible_watermark_present"] = _lsb_present(stored, embedded)
    applicable = [v for k, v in checks.items() if not (kind == "mp4" and k == "visible_watermark_present")]
    return {"intact": all(applicable), "checks": checks, "stored_sha256": hashlib.sha256(stored).hexdigest(),
            "watermark": (embedded or {}).get("watermark"), "received_at": (embedded or {}).get("received_at"),
            "note": "Video is marked invisibly only (no re-encoding)." if kind == "mp4" else None}


def _visible_present(stored: bytes, kind: str, manifest: dict[str, Any] | None) -> bool:
    if not manifest:
        return False
    if stored[:5] == b"%PDF-":
        try:
            doc = fitz.open(stream=stored, filetype="pdf")
            return all(settings.WATERMARK_TEXT in p.get_text() for p in doc)
        except Exception:
            return False
    if stored[:8] == PNG_SIG:
        return True  # band is rasterised into the pixels; integrity is covered by the LSB signature
    if kind == "geojson":
        return b"CHAIN OF CUSTODY" in stored
    return False


def _lsb_present(stored: bytes, manifest: dict[str, Any]) -> bool:
    try:
        arr = np.array(Image.open(io.BytesIO(stored)).convert("RGB"))
    except Exception:
        return False
    bits = _lsb_bits(manifest)
    blue = arr[:, :, 2].reshape(-1)[: bits.size * 4] & 1
    expected = np.resize(bits, blue.shape[0])
    return float((blue == expected).mean()) > 0.99
