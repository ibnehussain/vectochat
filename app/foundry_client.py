import os
import logging
from functools import lru_cache

from azure.ai.inference import ChatCompletionsClient, EmbeddingsClient
from azure.ai.inference.models import SystemMessage, UserMessage, AssistantMessage
from azure.core.credentials import AzureKeyCredential

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _get_chat_client() -> ChatCompletionsClient:
    endpoint = os.environ["AZURE_FOUNDRY_ENDPOINT"]
    key = os.environ["AZURE_FOUNDRY_KEY"]
    return ChatCompletionsClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key),
    )


@lru_cache(maxsize=1)
def _get_embedding_client() -> EmbeddingsClient:
    endpoint = os.environ["AZURE_FOUNDRY_ENDPOINT"]
    key = os.environ["AZURE_FOUNDRY_KEY"]
    return EmbeddingsClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key),
    )


def get_chat_completion(messages: list[dict]) -> str:
    """Call the Foundry chat completions endpoint.

    Args:
        messages: List of dicts with 'role' and 'content' keys.

    Returns:
        The assistant reply string.
    """
    client = _get_chat_client()
    model = os.environ["AZURE_FOUNDRY_CHAT_MODEL"]

    sdk_messages = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if role == "system":
            sdk_messages.append(SystemMessage(content=content))
        elif role == "user":
            sdk_messages.append(UserMessage(content=content))
        elif role == "assistant":
            sdk_messages.append(AssistantMessage(content=content))
        else:
            logger.warning("Unknown message role '%s' — skipping.", role)

    response = client.complete(model=model, messages=sdk_messages)
    return response.choices[0].message.content


def get_embedding(text: str) -> list[float]:
    """Generate an embedding vector for the given text.

    Args:
        text: The text to embed.

    Returns:
        A list of floats representing the 1536-dimensional embedding.
    """
    client = _get_embedding_client()
    model = os.environ["AZURE_FOUNDRY_EMBEDDING_MODEL"]
    response = client.embed(model=model, input=[text])
    return response.data[0].embedding
