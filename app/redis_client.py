import hashlib
import json
import logging
import os
from typing import Optional

from redis.asyncio.cluster import RedisCluster
from redis.asyncio.cluster import ClusterNode

logger = logging.getLogger(__name__)

_redis_client: Optional[RedisCluster] = None

# Key prefixes
_HISTORY_PREFIX = "chatbot:history:"
_EMBEDDING_PREFIX = "chatbot:emb:"


def _get_client() -> RedisCluster:
    global _redis_client
    if _redis_client is None:
        host = os.environ["REDIS_HOST"]
        port = int(os.environ.get("REDIS_PORT", "10000"))
        password = os.environ["REDIS_PASSWORD"]
        tls = os.environ.get("REDIS_TLS", "true").lower() == "true"

        _redis_client = RedisCluster(
            startup_nodes=[ClusterNode(host=host, port=port)],
            password=password,
            ssl=tls,
            ssl_cert_reqs=None,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
        )
    return _redis_client


async def ping() -> bool:
    """Return True if Redis is reachable."""
    try:
        return await _get_client().ping()
    except Exception as exc:
        logger.warning("Redis ping failed: %s", exc)
        return False


async def close() -> None:
    """Close the Redis connection pool (called on app shutdown)."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


# ── Conversation history ──────────────────────────────────────────────────────

async def get_history(session_id: str) -> Optional[list[dict]]:
    """Return cached conversation history or None on miss."""
    key = f"{_HISTORY_PREFIX}{session_id}"
    try:
        raw = await _get_client().get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.warning("Redis get_history error for session %s: %s", session_id, exc)
        return None


async def set_history(
    session_id: str,
    messages: list[dict],
    ttl: Optional[int] = None,
) -> None:
    """Write conversation history to cache with TTL (seconds)."""
    key = f"{_HISTORY_PREFIX}{session_id}"
    ttl = ttl or int(os.environ.get("HISTORY_CACHE_TTL", "3600"))
    try:
        await _get_client().set(key, json.dumps(messages), ex=ttl)
    except Exception as exc:
        logger.warning("Redis set_history error for session %s: %s", session_id, exc)


async def invalidate_history(session_id: str) -> None:
    """Remove a session's history from the cache."""
    key = f"{_HISTORY_PREFIX}{session_id}"
    try:
        await _get_client().delete(key)
    except Exception as exc:
        logger.warning("Redis invalidate_history error for session %s: %s", session_id, exc)


# ── Embedding cache ───────────────────────────────────────────────────────────

def _embedding_key(text: str) -> str:
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"{_EMBEDDING_PREFIX}{digest}"


async def get_embedding(text: str) -> Optional[list[float]]:
    """Return cached embedding vector or None on miss."""
    key = _embedding_key(text)
    try:
        raw = await _get_client().get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception as exc:
        logger.warning("Redis get_embedding error: %s", exc)
        return None


async def set_embedding(
    text: str,
    vector: list[float],
    ttl: Optional[int] = None,
) -> None:
    """Cache an embedding vector."""
    key = _embedding_key(text)
    ttl = ttl or int(os.environ.get("EMBEDDING_CACHE_TTL", "86400"))
    try:
        await _get_client().set(key, json.dumps(vector), ex=ttl)
    except Exception as exc:
        logger.warning("Redis set_embedding error: %s", exc)
