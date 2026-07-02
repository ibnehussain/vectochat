"""Document ingestion pipeline.

Reads .txt files from a source folder, splits them into overlapping chunks,
generates embeddings via Azure AI Foundry, and upserts to the CosmosDB
documents container.

Usage:
    python -m scripts.ingest --folder ./docs --category general
    python -m scripts.ingest --folder ./docs --category product_manual
"""

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

import httpx
import tiktoken
from azure.cosmos import CosmosClient
from urllib.parse import urlparse

CHUNK_TOKENS = 500
OVERLAP_TOKENS = 50
ENCODING = "cl100k_base"  # matches text-embedding-3-small / GPT-4 family


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into overlapping token-based chunks."""
    enc = tiktoken.get_encoding(ENCODING)
    tokens = enc.encode(text)
    chunks: list[str] = []
    start = 0
    while start < len(tokens):
        end = min(start + chunk_size, len(tokens))
        chunk_tokens = tokens[start:end]
        chunks.append(enc.decode(chunk_tokens))
        if end == len(tokens):
            break
        start += chunk_size - overlap
    return chunks


def embed_texts(texts: list[str], model: str) -> list[list[float]]:
    """Embed a batch of texts via Azure AI Foundry, splitting into sub-batches of 16."""
    endpoint = os.environ["AZURE_FOUNDRY_ENDPOINT"].rstrip("/")
    parsed = urlparse(endpoint)
    base = f"{parsed.scheme}://{parsed.netloc}"
    api_version = os.environ.get("AZURE_FOUNDRY_EMBEDDING_API_VERSION", "2024-10-21")
    url = f"{base}/openai/deployments/{model}/embeddings?api-version={api_version}"
    headers = {"api-key": os.environ["AZURE_FOUNDRY_KEY"], "Content-Type": "application/json"}
    vectors: list[list[float]] = []
    with httpx.Client(timeout=60.0) as client:
        for i in range(0, len(texts), 16):
            batch = texts[i : i + 16]
            resp = client.post(url, headers=headers, json={"input": batch})
            if not resp.is_success:
                print(f"  Embeddings API error {resp.status_code}: {resp.text}")
            resp.raise_for_status()
            vectors.extend([item["embedding"] for item in resp.json()["data"]])
    return vectors


def stable_id(source: str, chunk_index: int) -> str:
    """Generate a deterministic document ID."""
    raw = f"{source}::{chunk_index}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def ingest_folder(folder: str, category: str) -> None:
    folder_path = Path(folder)
    if not folder_path.exists():
        print(f"Folder not found: {folder_path}")
        sys.exit(1)

    txt_files = sorted(folder_path.glob("**/*.txt"))
    if not txt_files:
        print("No .txt files found in the folder.")
        return

    # ── Clients ───────────────────────────────────────────────────────────────
    cosmos = CosmosClient(
        url=os.environ["COSMOS_ENDPOINT"],
        credential=os.environ["COSMOS_KEY"],
    )
    container = (
        cosmos
        .get_database_client(os.environ["COSMOS_DATABASE"])
        .get_container_client(os.environ["COSMOS_DOCS_CONTAINER"])
    )
    embedding_model = os.environ["AZURE_FOUNDRY_EMBEDDING_MODEL"]

    total_upserted = 0

    for file_path in txt_files:
        print(f"Processing: {file_path.name}")
        text = file_path.read_text(encoding="utf-8", errors="replace")
        chunks = chunk_text(text, CHUNK_TOKENS, OVERLAP_TOKENS)
        print(f"  → {len(chunks)} chunks")

        # Embed all chunks for this file
        vectors = embed_texts(chunks, embedding_model)

        # Upsert to CosmosDB
        for idx, (chunk, vector) in enumerate(zip(chunks, vectors)):
            doc = {
                "id": stable_id(file_path.name, idx),
                "source": file_path.name,
                "category": category,
                "chunk_index": idx,
                "content": chunk,
                "embedding": vector,
            }
            container.upsert_item(doc)
            total_upserted += 1

        # Brief pause to respect rate limits
        time.sleep(0.2)

    print(f"\nIngestion complete. {total_upserted} chunks upserted.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest documents into CosmosDB vector store.")
    parser.add_argument("--folder", required=True, help="Path to folder containing .txt files")
    parser.add_argument("--category", default="general", help="Category tag for the documents")
    args = parser.parse_args()
    ingest_folder(args.folder, args.category)


if __name__ == "__main__":
    main()
