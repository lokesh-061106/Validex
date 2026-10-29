"""Redis client configuration and helper utilities with graceful fallback."""

import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

redis_client = None

try:
    import redis
    redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
except Exception as e:
    logger.info(f"Redis not connected on init: {e}")


def get_redis():
    """Dependency / helper to get Redis connection."""
    return redis_client
