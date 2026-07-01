"""One-time setup: creates the CosmosDB database and containers with
vector index policy for RAG + conversation history.

Usage:
    python -m scripts.setup_cosmos
"""

import os
import sys
from pathlib import Path

# Allow running from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from azure.cosmos import CosmosClient, PartitionKey, exceptions

VECTOR_DIMS = 1536
VECTOR_METRIC = "cosine"


def main() -> None:
    endpoint = os.environ["COSMOS_ENDPOINT"]
    key = os.environ["COSMOS_KEY"]
    db_name = os.environ["COSMOS_DATABASE"]
    docs_container = os.environ["COSMOS_DOCS_CONTAINER"]
    conv_container = os.environ["COSMOS_CONV_CONTAINER"]

    client = CosmosClient(url=endpoint, credential=key)

    # ── Database ──────────────────────────────────────────────────────────────
    print(f"Creating database '{db_name}' (if not exists)…")
    db = client.create_database_if_not_exists(id=db_name)

    # ── Documents container with vector index ─────────────────────────────────
    print(f"Creating documents container '{docs_container}'…")
    vector_embedding_policy = {
        "vectorEmbeddings": [
            {
                "path": "/embedding",
                "dataType": "float32",
                "distanceFunction": VECTOR_METRIC,
                "dimensions": VECTOR_DIMS,
            }
        ]
    }
    indexing_policy = {
        "indexingMode": "consistent",
        "automatic": True,
        "includedPaths": [{"path": "/*"}],
        "excludedPaths": [{"path": "/embedding/*"}],  # exclude raw vector from B-tree index
        "vectorIndexes": [
            {"path": "/embedding", "type": "diskANN"}
        ],
    }

    try:
        db.create_container(
            id=docs_container,
            partition_key=PartitionKey(path="/category"),
            indexing_policy=indexing_policy,
            vector_embedding_policy=vector_embedding_policy,
        )
        print(f"  ✓ '{docs_container}' created.")
    except exceptions.CosmosResourceExistsError:
        print(f"  — '{docs_container}' already exists, skipping.")

    # ── Conversations container ────────────────────────────────────────────────
    print(f"Creating conversations container '{conv_container}'…")
    try:
        db.create_container(
            id=conv_container,
            partition_key=PartitionKey(path="/session_id"),
        )
        print(f"  ✓ '{conv_container}' created.")
    except exceptions.CosmosResourceExistsError:
        print(f"  — '{conv_container}' already exists, skipping.")

    print("\nSetup complete.")


if __name__ == "__main__":
    main()
