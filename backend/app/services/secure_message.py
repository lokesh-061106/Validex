"""Hybrid encryption to an institution's public key (RSA-OAEP-SHA256 + AES-256-GCM).

Compatible with the browser's WebCrypto: the portal generates an RSA-OAEP 2048 key pair, uploads
the SPKI public key, and decrypts with the private key that never leaves the browser.
"""

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ALG = "RSA-OAEP-256+A256GCM"


class KeyError_(ValueError):
    pass


def load_public_key(pem: str) -> rsa.RSAPublicKey:
    try:
        key = serialization.load_pem_public_key(pem.encode())
    except Exception as e:
        raise KeyError_("Not a valid PEM public key") from e
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 2048:
        raise KeyError_("An RSA public key of at least 2048 bits is required")
    return key


def encrypt_for(public_key_pem: str, payload: dict[str, Any]) -> tuple[dict[str, str], str]:
    """Return (envelope, sha256 of the plaintext) — the hash goes to the audit ledger."""
    plaintext = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    key = AESGCM.generate_key(bit_length=256)
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, plaintext, None)
    ek = load_public_key(public_key_pem).encrypt(
        key, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    b64 = lambda b: base64.b64encode(b).decode()  # noqa: E731
    return {"alg": ALG, "ek": b64(ek), "iv": b64(iv), "ct": b64(ct)}, hashlib.sha256(plaintext).hexdigest()


def decrypt_with(private_key: rsa.RSAPrivateKey, envelope: dict[str, str]) -> dict[str, Any]:
    """Reference decryption (tests / tooling). The portal does this in the browser."""
    d = lambda s: base64.b64decode(s)  # noqa: E731
    key = private_key.decrypt(d(envelope["ek"]), padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()),
                                                               algorithm=hashes.SHA256(), label=None))
    return json.loads(AESGCM(key).decrypt(d(envelope["iv"]), d(envelope["ct"]), None))
