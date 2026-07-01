import logging
import os
import time
from functools import lru_cache
from typing import Optional

from azure.cosmos import CosmosClient, PartitionKey, exceptions

logger = logging.getLogger(__name__)

VECTOR_DIMS = 1536
VECTOR_METRIC = "cosine"


@lru_cache(maxsize=1)
def _get_client() -> CosmosClient:
    endpoint = os.environ["COSMOS_ENDPOINT"]
    key = os.environ["COSMOS_KEY"]
    return CosmosClient(url=endpoint, credential=key)


def _get_docs_container():
    client = _get_client()
    db_name = os.environ["COSMOS_DATABASE"]
    container_name = os.environ["COSMOS_DOCS_CONTAINER"]
    return client.get_database_client(db_name).get_container_client(container_name)


def _get_conv_container():
    client = _get_client()
    db_name = os.environ["COSMOS_DATABASE"]
    container_name = os.environ["COSMOS_CONV_CONTAINER"]
    return client.get_database_client(db_name).get_container_client(container_name)


# ── Vector search ─────────────────────────────────────────────────────────────

def search_documents(query_embedding: list[float], top_k: int = 5) -> list[dict]:
    """Run a vector similarity search against the documents container.

    Returns a list of document dicts (id, source, category, content, score).
    """
    container = _get_docs_container()

    query = (
        "SELECT TOP @top_k c.id, c.source, c.category, c.content, "
        "VectorDistance(c.embedding, @embedding) AS score "
        "FROM c "
        "ORDER BY VectorDistance(c.embedding, @embedding)"
    )
    params = [
        {"name": "@top_k", "value": top_k},
        {"name": "@embedding", "value": query_embedding},
    ]

    try:
        items = list(
            container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True,
            )
        )
        return items
    except exceptions.CosmosHttpResponseError as exc:
        logger.error("CosmosDB vector search failed: %s", exc)
        return []


# ── Conversation history ──────────────────────────────────────────────────────

def save_message(session_id: str, role: str, content: str) -> None:
    """Persist a single conversation turn to CosmosDB."""
    container = _get_conv_container()
    doc = {
        "id": f"{session_id}_{role}_{int(time.time() * 1000)}",
        "session_id": session_id,
        "role": role,
        "content": content,
        "timestamp": time.time(),
    }
    container.upsert_item(doc)


def get_history(session_id: str, limit: int = 20) -> list[dict]:
    """Fetch the most recent `limit` messages for a session from CosmosDB."""
    container = _get_conv_container()

    query = (
        "SELECT c.role, c.content, c.timestamp "
        "FROM c "
        "WHERE c.session_id = @session_id "
        "ORDER BY c.timestamp DESC "
        "OFFSET 0 LIMIT @limit"
    )
    params = [
        {"name": "@session_id", "value": session_id},
        {"name": "@limit", "value": limit},
    ]

    try:
        items = list(
            container.query_items(
                query=query,
                parameters=params,
                partition_key=session_id,
            )
        )
        # Return in chronological order
        return list(reversed(items))
    except exceptions.CosmosHttpResponseError as exc:
        logger.error("CosmosDB get_history failed for session %s: %s", session_id, exc)
        return []


def delete_history(session_id: str) -> int:
    """Delete all conversation messages for a session. Returns count deleted."""
    container = _get_conv_container()

    query = "SELECT c.id FROM c WHERE c.session_id = @session_id"
    params = [{"name": "@session_id", "value": session_id}]

    deleted = 0
    try:
        items = list(
            container.query_items(
                query=query,
                parameters=params,
                partition_key=session_id,
            )
        )
        for item in items:
            container.delete_item(item=item["id"], partition_key=session_id)
            deleted += 1
    except exceptions.CosmosHttpResponseError as exc:
        logger.error("CosmosDB delete_history failed for session %s: %s", session_id, exc)

    return deleted


def ping() -> bool:
    """Return True if CosmosDB is reachable."""
    try:
        client = _get_client()
        db_name = os.environ["COSMOS_DATABASE"]
        client.get_database_client(db_name).read()
        return True
    except Exception as exc:
        logger.warning("CosmosDB ping failed: %s", exc)
        return False
