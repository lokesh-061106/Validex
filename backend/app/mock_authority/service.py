"""Simulated issuing-authority and AICTE-records APIs.

Exposed both as plain functions (in-process adapter) and as a FastAPI router, so the same
service can run inside the backend or as its own container (see mock_authority/main.py).
"""

import json
import os
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from fastapi import APIRouter, HTTPException

from app.core.config import settings
from app.mock_authority.keys import public_key_b64

REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "registry.json")

_state = {"outage": settings.MOCK_AUTHORITY_OUTAGE}


class SourceUnavailable(Exception):
    """The issuing authority could not be reached (timeout, 5xx, maintenance)."""


@lru_cache(maxsize=1)
def _registry() -> dict[str, Any]:
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)


def set_outage(enabled: bool) -> None:
    _state["outage"] = enabled


def outage_enabled() -> bool:
    return _state["outage"]


def authority_name(authority: str) -> str:
    return _registry()["authorities"].get(authority, {}).get("name", authority)


def lookup(authority: str, identifier: str) -> dict[str, Any]:
    """Look up one record. Raises SourceUnavailable during a simulated outage.

    Returns {"authority", "identifier", "status": "found"|"not_found"|"pending", "record", "checked_at"}.
    """
    if _state["outage"]:
        raise SourceUnavailable(f"{authority_name(authority)} is not responding (simulated outage)")
    reg = _registry()["authorities"]
    if authority not in reg:
        raise KeyError(f"Unknown authority: {authority}")
    record = reg[authority]["records"].get(identifier.strip())
    result = {
        "authority": authority,
        "authority_name": reg[authority]["name"],
        "identifier": identifier,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    if record is None:
        return {**result, "status": "not_found", "record": None}
    if record.get("simulate") == "pending":
        return {**result, "status": "pending", "record": None,
                "message": "Record exists but has not yet been digitised by the issuing authority"}
    return {**result, "status": "found", "record": {k: v for k, v in record.items() if k != "simulate"}}


def institution_record(permanent_id: str) -> dict[str, Any] | None:
    if _state["outage"]:
        raise SourceUnavailable("AICTE institutional records service is not responding (simulated outage)")
    return _registry()["aicte_institutions"].get(permanent_id)


# ---------------------------------------------------------------- HTTP facade

router = APIRouter(prefix="/mock-authority", tags=["Simulated Issuing Authorities (demo only)"])


@router.get("/{authority}/records/{identifier:path}")
def http_lookup(authority: str, identifier: str):
    try:
        return lookup(authority, identifier)
    except SourceUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/aicte/institutions/{permanent_id}")
def http_institution(permanent_id: str):
    try:
        rec = institution_record(permanent_id)
    except SourceUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    if rec is None:
        raise HTTPException(status_code=404, detail="Institution not found")
    return rec


@router.get("/{authority}/public-key")
def http_public_key(authority: str):
    return {"issuer": authority, "algorithm": "Ed25519", "public_key_b64": public_key_b64(authority)}


@router.get("/status")
def http_status():
    return {"outage": _state["outage"], "authorities": list(_registry()["authorities"].keys())}
