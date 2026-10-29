"""Minimal in-memory token-bucket limiter (per key), used to slow down login brute force."""

import threading
import time


class TokenBucket:
    def __init__(self, capacity: int, refill_per_second: float):
        self.capacity = capacity
        self.refill = refill_per_second
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, last = self._buckets.get(key, (float(self.capacity), now))
            tokens = min(self.capacity, tokens + (now - last) * self.refill)
            if tokens < 1:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1, now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


# 10 attempts, then one more every 30 seconds
login_limiter = TokenBucket(capacity=10, refill_per_second=1 / 30)
