"""Pluggable adapters for external sources (issuing authorities, AICTE records).

The platform never assumes direct database access to a source. Each source is reached through
an adapter: the in-process mock for local demos, or HTTP to the mock-authority service /
a sandbox gateway when AUTHORITY_API_URL is set. Only the minimum identifier is sent.
"""

import logging
import random
import threading
import time
from typing import Any

import httpx

from app.core.config import settings
from app.mock_authority import service as mock
from app.mock_authority.service import SourceUnavailable

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """Stops hammering a source that keeps failing; re-opens after a cool-down."""

    def __init__(self, threshold: int = 3, cooldown_seconds: float = 30.0):
        self.threshold = threshold
        self.cooldown = cooldown_seconds
        self.failures = 0
        self.opened_at: float | None = None
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            if self.opened_at is None:
                return True
            if time.monotonic() - self.opened_at >= self.cooldown:
                self.opened_at = None
                self.failures = 0
                return True
            return False

    def record(self, ok: bool) -> None:
        with self._lock:
            if ok:
                self.failures = 0
                self.opened_at = None
            else:
                self.failures += 1
                if self.failures >= self.threshold:
                    self.opened_at = time.monotonic()


_breakers: dict[str, CircuitBreaker] = {}


def _breaker(name: str) -> CircuitBreaker:
    return _breakers.setdefault(name, CircuitBreaker())


def backoff_delay(attempt: int, base: float = 2.0, cap: float = 600.0) -> float:
    """Exponential backoff with full jitter (seconds)."""
    return random.uniform(0, min(cap, base * (2 ** attempt)))


def _with_retries(source: str, fn, attempts: int = 3):
    breaker = _breaker(source)
    if not breaker.allow():
        raise SourceUnavailable(f"{source}: circuit open after repeated failures; will retry later")
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            result = fn()
            breaker.record(True)
            return result
        except SourceUnavailable as e:
            last_exc = e
            breaker.record(False)
            if attempt < attempts - 1:
                time.sleep(min(backoff_delay(attempt, base=0.05), 0.3))  # short in-request retries
    raise last_exc  # type: ignore[misc]


class AuthorityConnector:
    def lookup(self, authority: str, identifier: str) -> dict[str, Any]:
        raise NotImplementedError

    def institution_record(self, permanent_id: str) -> dict[str, Any] | None:
        raise NotImplementedError


class InProcessMockConnector(AuthorityConnector):
    def lookup(self, authority: str, identifier: str) -> dict[str, Any]:
        return _with_retries(authority, lambda: mock.lookup(authority, identifier))

    def institution_record(self, permanent_id: str) -> dict[str, Any] | None:
        return _with_retries("aicte_records", lambda: mock.institution_record(permanent_id))


class HttpAuthorityConnector(AuthorityConnector):
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str) -> httpx.Response:
        try:
            resp = httpx.get(f"{self.base_url}{path}", timeout=settings.AUTHORITY_TIMEOUT_SECONDS)
        except httpx.HTTPError as e:
            raise SourceUnavailable(f"Source unreachable: {e}") from e
        if resp.status_code >= 500:
            raise SourceUnavailable(f"Source returned HTTP {resp.status_code}")
        return resp

    def lookup(self, authority: str, identifier: str) -> dict[str, Any]:
        def call():
            resp = self._get(f"/mock-authority/{authority}/records/{identifier}")
            resp.raise_for_status()
            return resp.json()

        return _with_retries(authority, call)

    def institution_record(self, permanent_id: str) -> dict[str, Any] | None:
        def call():
            resp = self._get(f"/mock-authority/aicte/institutions/{permanent_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()

        return _with_retries("aicte_records", call)


def get_connector() -> AuthorityConnector:
    if settings.AUTHORITY_API_URL:
        return HttpAuthorityConnector(settings.AUTHORITY_API_URL)
    return InProcessMockConnector()


def reset_breakers() -> None:
    _breakers.clear()
