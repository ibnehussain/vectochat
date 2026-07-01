import logging
import os

from app import cosmos_client, foundry_client, redis_client
from app.models import SourceChunk

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a helpful assistant. Answer the user's question using \
the provided document context. If the context does not contain enough information, \
say so clearly. Be concise and accurate."""


async def retrieve_context(query: str) -> tuple[str, list[SourceChunk]]:
    """Embed the query (cache-first) and run CosmosDB vector search.

    Returns:
        context_text: Formatted string of top document chunks for the prompt.
        sources:      List of SourceChunk objects for the API response.
    """
    # 1. Try Redis embedding cache
    vector = await redis_client.get_embedding(query)
    if vector is not None:
        logger.debug("Embedding cache hit for query.")
    else:
        logger.debug("Embedding cache miss — calling Foundry.")
        vector = foundry_client.get_embedding(query)
        await redis_client.set_embedding(query, vector)

    # 2. CosmosDB vector search
    top_k = int(os.environ.get("TOP_K", "5"))
    raw_docs = cosmos_client.search_documents(vector, top_k=top_k)

    # 3. Build formatted context and source list
    context_parts: list[str] = []
    sources: list[SourceChunk] = []

    for doc in raw_docs:
        content = doc.get("content", "")
        context_parts.append(
            f"[Source: {doc.get('source', 'unknown')} | Category: {doc.get('category', '')}]\n{content}"
        )
        sources.append(
            SourceChunk(
                id=doc.get("id", ""),
                source=doc.get("source", ""),
                category=doc.get("category", ""),
                content_preview=content[:200],
            )
        )

    context_text = "\n\n---\n\n".join(context_parts) if context_parts else "No relevant documents found."
    return context_text, sources


def build_messages(
    query: str,
    context: str,
    history: list[dict],
) -> list[dict]:
    """Assemble the messages list for the chat completions call.

    Structure:
        system  — instructions + document context
        user/assistant turns from history
        user    — current query
    """
    max_history = int(os.environ.get("MAX_HISTORY", "20"))
    trimmed_history = history[-max_history:]

    messages: list[dict] = [
        {
            "role": "system",
            "content": (
                f"{SYSTEM_PROMPT}\n\n"
                f"## Relevant Documents\n\n{context}"
            ),
        }
    ]

    for turn in trimmed_history:
        messages.append({"role": turn["role"], "content": turn["content"]})

    messages.append({"role": "user", "content": query})
    return messages
