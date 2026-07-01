import os
import logging
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


def _base_url() -> str:
    """Extract just the scheme + host from AZURE_FOUNDRY_ENDPOINT."""
    parsed = urlparse(os.environ["AZURE_FOUNDRY_ENDPOINT"])
    return f"{parsed.scheme}://{parsed.netloc}"


def _responses_url() -> str:
    return os.environ["AZURE_FOUNDRY_ENDPOINT"].rstrip("/")


def _embeddings_url() -> str:
    # Azure AI Inference style: <host>/models/embeddings
    api_version = os.environ.get("AZURE_FOUNDRY_EMBEDDING_API_VERSION", "2024-05-01-preview")
    return f"{_base_url()}/models/embeddings?api-version={api_version}"


def _headers() -> dict:
    return {
        "api-key": os.environ["AZURE_FOUNDRY_KEY"],
        "Content-Type": "application/json",
    }


def get_chat_completion(messages: list[dict]) -> str:
    """Call the Foundry Responses API endpoint.

    Args:
        messages: List of dicts with 'role' and 'content' keys.

    Returns:
        The assistant reply string.
    """
    model = os.environ["AZURE_FOUNDRY_CHAT_MODEL"]

    input_messages = []
    instructions: str | None = None
    for m in messages:
        if m["role"] == "system":
            instructions = m["content"]
        else:
            input_messages.append({"role": m["role"], "content": m["content"]})

    payload: dict = {"model": model, "input": input_messages}
    if instructions:
        payload["instructions"] = instructions

    with httpx.Client(timeout=60.0) as client:
        resp = client.post(_responses_url(), headers=_headers(), json=payload)
        if not resp.is_success:
            logger.error("Responses API error %s: %s", resp.status_code, resp.text)
        resp.raise_for_status()
        data = resp.json()

    # Responses API shape: output[0].content[0].text
    return data["output"][0]["content"][0]["text"]


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
            _embeddings_url(),
            headers=_headers(),
            json={"model": model, "input": [text]},  # input must be an array
        )
        if not resp.is_success:
            logger.error("Embeddings API error %s: %s", resp.status_code, resp.text)
        resp.raise_for_status()
        data = resp.json()

    return data["data"][0]["embedding"]

