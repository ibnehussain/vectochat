# RAG Chatbot

A production-ready conversational AI chatbot built with Python and FastAPI, backed by:

| Layer | Technology |
|---|---|
| LLM + Embeddings | Azure AI Foundry (GPT-4o + text-embedding-3-small) |
| Vector search | Azure Cosmos DB for NoSQL — DiskANN cosine index |
| Conversation history | Azure Cosmos DB for NoSQL |
| Caching | Azure Managed Redis — Balanced_B0 (0.5 GB) |
| Container runtime | Docker (Python 3.11-slim) |
| Orchestration | Azure Kubernetes Service (AKS) |
| Image registry | Azure Container Registry (ACR) |

**How it works:**

```
Browser ──► FastAPI ──► Redis (history cache hit?)
                   │              │ miss
                   │              ▼
                   │         Cosmos DB (conversations)
                   │
                   ├──► Redis (embedding cache hit?)
                   │              │ miss
                   │              ▼
                   │         Azure AI Foundry (embed query)
                   │
                   ├──► Cosmos DB (DiskANN vector search → top-K chunks)
                   │
                   └──► Azure AI Foundry (GPT-4o chat completion)
                                   │
                              reply + sources
```

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Python | 3.11+ | [python.org](https://www.python.org) |
| Docker Desktop | 4.x+ | [docker.com](https://www.docker.com) |
| Azure CLI | 2.60+ | `winget install Microsoft.AzureCLI` |
| kubectl | 1.29+ | `az aks install-cli` |
| Git Bash / WSL | — | Required to run `deploy.sh` on Windows |

Azure resources you must provision **before** local development:

- **Azure AI Foundry hub** with deployed models:
  - Chat model: `gpt-4o` (or any GPT-4-family model)
  - Embedding model: `text-embedding-3-small`
- **Azure Cosmos DB for NoSQL** account with two containers:

  | Container | Partition Key | Purpose |
  |---|---|---|
  | `documents` | `/category` | Stores document chunks with DiskANN cosine vector index on `/embedding` (float32, 1536 dims) |
  | `conversations` | `/session_id` | Stores per-session conversation history |

  > Run `python -m scripts.setup_cosmos` to create the database and both containers automatically.

- **Azure Managed Redis** Balanced_B0 (0.5 GB) *(or let `deploy.sh` create it)*

---

## Project Structure

```
chatbot/
├── app/
│   ├── main.py              # FastAPI entry point, /health, static mount
│   ├── chat.py              # POST /api/chat, GET/DELETE /api/history/{id}
│   ├── rag.py               # Embedding cache + vector search + prompt builder
│   ├── cosmos_client.py     # CosmosDB vector search + conversation CRUD
│   ├── foundry_client.py    # Azure AI Foundry LLM + embedding wrapper
│   ├── redis_client.py      # Redis history cache (1 h) + embedding cache (24 h)
│   ├── models.py            # Pydantic request/response schemas
│   └── static/
│       ├── index.html       # Chat web UI
│       └── app.js           # Frontend — fetch, markdown render, session state
├── scripts/
│   ├── setup_cosmos.py      # One-time: create DB + containers + vector index
│   └── ingest.py            # Chunk .txt files → embed → upsert to CosmosDB
├── k8s/
│   ├── namespace.yaml
│   ├── configmap.yaml       # Non-secret configuration
│   ├── secret.yaml          # Template — never commit real values
│   ├── deployment.yaml      # 2 replicas, liveness/readiness probes
│   └── service.yaml         # LoadBalancer, port 80 → 8000
├── Dockerfile
├── .dockerignore
├── requirements.txt
├── .env.example             # Document of all environment variables
└── deploy.sh                # End-to-end Azure + AKS deploy script
```

---

## 1 — Local Development

### 1.1 Clone and install dependencies

```bash
git clone <your-repo-url> chatbot
cd chatbot

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 1.2 Configure environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in every value:

```env
# Azure AI Foundry
AZURE_FOUNDRY_ENDPOINT=https://<your-hub>.services.ai.azure.com/models
AZURE_FOUNDRY_KEY=<your-key>
AZURE_FOUNDRY_CHAT_MODEL=gpt-4o
AZURE_FOUNDRY_EMBEDDING_MODEL=text-embedding-3-small

# Cosmos DB
COSMOS_ENDPOINT=https://<account>.documents.azure.com:443/
COSMOS_KEY=<primary-key>
COSMOS_DATABASE=chatbot_db
COSMOS_DOCS_CONTAINER=documents
COSMOS_CONV_CONTAINER=conversations

# Redis (use 127.0.0.1 / 6379 for local Docker Redis; Azure host for cloud)
REDIS_HOST=<cache>.redis.cache.windows.net
REDIS_PORT=6380
REDIS_PASSWORD=<access-key>
REDIS_TLS=true
```

> **Local Redis shortcut:** `docker run -p 6379:6379 redis:7-alpine` then set `REDIS_HOST=127.0.0.1 REDIS_PORT=6379 REDIS_PASSWORD= REDIS_TLS=false`.

> **Azure Managed Redis port:** Production uses port `10000` (TLS). The `configmap.yaml` is pre-set to `10000`.

### 1.3 Set up Cosmos DB (one-time)

```bash
python -m scripts.setup_cosmos
```

This creates:
- Database `chatbot_db`
- Container `documents` — partition key `/category`, DiskANN cosine vector index on `/embedding` (float32, 1536 dims)
- Container `conversations` — partition key `/session_id`

### 1.4 Ingest documents (optional but recommended)

Place `.txt` files in a folder, then run:

```bash
python -m scripts.ingest --folder ./docs --category general
```

The script chunks each file (~500 tokens, 50-token overlap), generates embeddings via Foundry, and upserts them to CosmosDB.

### 1.5 Run the app

```bash
uvicorn app.main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000). The `/health` endpoint confirms Redis and CosmosDB connectivity:

```json
{ "status": "ok", "redis": "pong", "cosmos": "ok" }
```

---

## 2 — Build & Run with Docker

```bash
# Build
docker build -t chatbot:local .

# Run (reads from .env file)
docker run --rm -p 8000:8000 --env-file .env chatbot:local
```

Open [http://localhost:8000](http://localhost:8000).

---

## 3 — Deploy to Azure AKS

`deploy.sh` automates all 8 provisioning and deployment steps end-to-end.

### 3.1 Log in to Azure

```bash
az login
az account set --subscription "<your-subscription-id>"
```

### 3.2 Set an optional suffix for idempotency

```bash
export DEPLOY_SUFFIX=abc123   # keep the same value on re-runs to avoid duplicate resources
```

If omitted, a random 6-character hex suffix is generated automatically.

### 3.3 Run the deploy script

> Requires Git Bash or WSL on Windows.

```bash
bash deploy.sh
```

**What the script does, step by step:**

| Step | Action |
|---|---|
| 1 | `az group create` — resource group `rg-chatbot` in `eastus` |
| 2 | `az acr create` — Azure Container Registry (Basic SKU) |
| 3 | `az redisenterprise create` + `az redisenterprise database create` — Azure Managed Redis Balanced_B0 (0.5 GB), TLS, polls until `Succeeded` (~5-10 min) |
| 4 | `az aks create` — 2-node AKS cluster (Standard_D2s_v3), attached to ACR, managed identity |
| 5 | `az aks get-credentials` — merges kube context locally |
| 6 | `docker build` + `docker push` — image pushed to ACR |
| 7 | `kubectl apply` — namespace → configmap → secret (prompts for Foundry + Cosmos keys) → deployment → service |
| 8 | `kubectl rollout status` — waits for 2/2 pods ready, then prints the external IP |

### 3.4 Access the live chatbot

When the script finishes it prints:

```
 Chatbot URL : http://<EXTERNAL-IP>
 Health      : http://<EXTERNAL-IP>/health
```

Open the chatbot URL in any browser.

---

## 4 — Update & Redeploy

To push a new version of the app after code changes:

```bash
export DEPLOY_SUFFIX=abc123   # same suffix as initial deploy
export IMAGE_TAG=v2

ACR_NAME="acrchatbot${DEPLOY_SUFFIX}"
az acr login --name "${ACR_NAME}"

docker build -t "${ACR_NAME}.azurecr.io/chatbot:${IMAGE_TAG}" .
docker push  "${ACR_NAME}.azurecr.io/chatbot:${IMAGE_TAG}"

# Patch the running deployment to the new image
kubectl set image deployment/chatbot \
  chatbot="${ACR_NAME}.azurecr.io/chatbot:${IMAGE_TAG}" \
  -n chatbot

kubectl rollout status deployment/chatbot -n chatbot
```

---

## 5 — Verify the Deployment

### Health check

```bash
curl http://<EXTERNAL-IP>/health
# {"status":"ok","redis":"pong","cosmos":"ok"}
```

### Send a chat message

```bash
curl -s -X POST http://<EXTERNAL-IP>/api/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"test-session-1","message":"Hello, what can you help me with?"}' \
  | python -m json.tool
```

### Inspect pods and logs

```bash
# Pod status
kubectl get pods -n chatbot

# App logs (replace <pod-name>)
kubectl logs -n chatbot <pod-name> --follow

# Service external IP
kubectl get svc -n chatbot
```

### Test Redis caching

Send the same question twice and watch logs for `Embedding cache hit` on the second request:

```bash
kubectl logs -n chatbot -l app=chatbot --follow | grep -i cache
```

---

## 6 — Configuration Reference

All values set via Kubernetes ConfigMap (`k8s/configmap.yaml`) and Secret (`k8s/secret.yaml`).

| Variable | Source | Default | Description |
|---|---|---|---|
| `AZURE_FOUNDRY_ENDPOINT` | Secret | — | Foundry models endpoint URL |
| `AZURE_FOUNDRY_KEY` | Secret | — | Foundry API key |
| `AZURE_FOUNDRY_CHAT_MODEL` | ConfigMap | `gpt-4o` | Chat deployment name |
| `AZURE_FOUNDRY_EMBEDDING_MODEL` | ConfigMap | `text-embedding-3-small` | Embedding deployment name |
| `COSMOS_ENDPOINT` | Secret | — | Cosmos DB account URL |
| `COSMOS_KEY` | Secret | — | Cosmos DB primary key |
| `COSMOS_DATABASE` | ConfigMap | `chatbot_db` | Database name |
| `COSMOS_DOCS_CONTAINER` | ConfigMap | `documents` | Vector search container |
| `COSMOS_CONV_CONTAINER` | ConfigMap | `conversations` | Chat history container |
| `REDIS_HOST` | Secret | — | Redis hostname |
| `REDIS_PASSWORD` | Secret | — | Redis access key |
| `REDIS_PORT` | ConfigMap | `10000` | Redis port (10000 = Azure Managed Redis TLS) |
| `REDIS_TLS` | ConfigMap | `true` | Enable TLS for Redis |
| `TOP_K` | ConfigMap | `5` | Document chunks returned per query |
| `MAX_HISTORY` | ConfigMap | `20` | Max conversation turns in prompt |
| `EMBEDDING_CACHE_TTL` | ConfigMap | `86400` | Embedding cache TTL (seconds) |
| `HISTORY_CACHE_TTL` | ConfigMap | `3600` | History cache TTL (seconds) |
| `ENABLE_DOCS` | ConfigMap | `false` | Set `true` to expose `/docs` (Swagger) |

---

## 7 — API Reference

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/chat` | Send a message; returns reply + source citations |
| `GET` | `/api/history/{session_id}` | Retrieve conversation history for a session |
| `DELETE` | `/api/history/{session_id}` | Delete all messages for a session |
| `GET` | `/health` | Health check (Redis + CosmosDB connectivity) |
| `GET` | `/` | Serves the chat web UI |

**POST /api/chat — request:**
```json
{ "session_id": "uuid-string", "message": "What is the return policy?" }
```

**POST /api/chat — response:**
```json
{
  "reply": "According to the policy document...",
  "session_id": "uuid-string",
  "sources": [
    { "id": "abc123", "source": "policy.txt", "category": "general", "content_preview": "..." }
  ]
}
```

---

## 8 — Tear Down Azure Resources

```bash
az group delete --name rg-chatbot --yes --no-wait
```

This deletes the entire resource group including AKS, ACR, Redis, and all associated resources.

---

## Security Notes

- Secrets are never stored in `k8s/secret.yaml` — the file is a template only. Real values are injected via `kubectl create secret`.
- The container runs as a **non-root user** (`appuser`).
- Redis requires **TLS 1.2** minimum.
- The Swagger UI (`/docs`) is **disabled by default** in production (`ENABLE_DOCS=false`).
- CosmosDB and Redis credentials should be rotated via Azure Key Vault + CSI driver for production hardening.
