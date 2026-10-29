"""Deterministic Ed25519 keys for the simulated issuers.

Each mock issuer signs the QR payload printed on its certificates. Keys are derived from a
fixed seed so synthetic documents can be regenerated reproducibly. These are demo keys only.
"""

import base64
import hashlib
import json
from functools import lru_cache
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives import serialization

QR_PREFIX = "VALIDEX1:"


@lru_cache(maxsize=None)
def _private_key(issuer: str) -> Ed25519PrivateKey:
    seed = hashlib.sha256(f"validex-mock-issuer::{issuer}".encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


@lru_cache(maxsize=None)
def public_key(issuer: str) -> Ed25519PublicKey:
    return _private_key(issuer).public_key()


def public_key_b64(issuer: str) -> str:
    raw = public_key(issuer).public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def _canonical(issuer: str, data: dict[str, Any]) -> bytes:
    return json.dumps({"iss": issuer, "data": data}, sort_keys=True, separators=(",", ":")).encode()


def sign_payload(issuer: str, data: dict[str, Any]) -> str:
    """Return the QR text for a certificate: prefix + base64(json{iss,data,sig})."""
    sig = _private_key(issuer).sign(_canonical(issuer, data))
    body = {"iss": issuer, "data": data, "sig": base64.b64encode(sig).decode()}
    return QR_PREFIX + base64.urlsafe_b64encode(json.dumps(body, separators=(",", ":")).encode()).decode()


def parse_and_verify(qr_text: str) -> dict[str, Any]:
    """Decode QR text and verify the issuer signature.

    Returns {"format_ok", "issuer", "data", "signature_valid", "error"}.
    """
    out: dict[str, Any] = {"format_ok": False, "issuer": None, "data": None, "signature_valid": False, "error": None}
    if not qr_text or not qr_text.startswith(QR_PREFIX):
        out["error"] = "QR code is not a recognised signed certificate payload"
        return out
    try:
        body = json.loads(base64.urlsafe_b64decode(qr_text[len(QR_PREFIX):].encode()))
        issuer, data, sig = body["iss"], body["data"], base64.b64decode(body["sig"])
    except Exception:
        out["error"] = "QR payload is malformed"
        return out
    out.update({"format_ok": True, "issuer": issuer, "data": data})
    try:
        public_key(issuer).verify(sig, _canonical(issuer, data))
        out["signature_valid"] = True
    except InvalidSignature:
        out["error"] = "Issuer signature does not match the QR contents (QR altered or forged)"
    return out
