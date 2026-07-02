import os
import logging
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


def _base_url() -> str:
    """Extract just the scheme + host from AZURE_FOUNDRY_ENDPOINT."""
    parsed = urlparse(os.environ["AZURE_FOUNDRY_ENDPOINT"])
    return f"{parsed.scheme}://{parsed.netloc}"


def _chat_completions_url(model: str) -> str:
    api_version = os.environ.get("AZURE_FOUNDRY_CHAT_API_VERSION", "2024-10-21")
    return f"{_base_url()}/openai/deployments/{model}/chat/completions?api-version={api_version}"


def _embeddings_url(model: str) -> str:
    api_version = os.environ.get("AZURE_FOUNDRY_EMBEDDING_API_VERSION", "2024-10-21")
    return f"{_base_url()}/openai/deployments/{model}/embeddings?api-version={api_version}"


def _headers() -> dict:
    return {
        "api-key": os.environ["AZURE_FOUNDRY_KEY"],
        "Content-Type": "application/json",
    }


def get_chat_completion(messages: list[dict]) -> str:
    """Call the Azure OpenAI Chat Completions endpoint.

    Args:
        messages: List of dicts with 'role' and 'content' keys.

    Returns:
        The assistant reply string.
    """
    model = os.environ["AZURE_FOUNDRY_CHAT_MODEL"]

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            _chat_completions_url(model),
            headers=_headers(),
            json={"messages": messages},
        )
        if not resp.is_success:
            logger.error("Chat Completions API error %s: %s", resp.status_code, resp.text)
        resp.raise_for_status()
        data = resp.json()

    return data["choices"][0]["message"]["content"]


def get_embedding(text: str) -> list[float]:
    """Generate an embedding vector for the given text.

    Args:
        text: The text to embed.

    Returns:
        A list of floats representing the embedding vector.
    """
    model = os.environ["AZURE_FOUNDRY_EMBEDDING_MODEL"]

    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            _embeddings_url(model),
            headers=_headers(),
            json={"input": [text]},
        )
        if not resp.is_success:
            logger.error("Embeddings API error %s: %s", resp.status_code, resp.text)
        resp.raise_for_status()
        data = resp.json()

    return data["data"][0]["embedding"]

