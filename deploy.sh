#!/usr/bin/env bash
# deploy.sh — End-to-end Azure provisioning + AKS deployment for RAG Chatbot
# Usage: bash deploy.sh
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
RESOURCE_GROUP="rg-chatbot"
LOCATION="eastus"
SUFFIX="${DEPLOY_SUFFIX:-$(openssl rand -hex 3)}"   # override via env var for idempotency
ACR_NAME="acrchatbot${SUFFIX}"
AKS_NAME="aks-chatbot"
REDIS_NAME="redis-chatbot-${SUFFIX}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
IMAGE_FULL="${ACR_NAME}.azurecr.io/chatbot:${IMAGE_TAG}"
NODE_COUNT=2
NODE_VM="Standard_D2s_v3"

echo "════════════════════════════════════════════════════"
echo " VectoChat — Azure Deployment"
echo " Resource Group : ${RESOURCE_GROUP}"
echo " Location       : ${LOCATION}"
echo " ACR            : ${ACR_NAME}"
echo " AKS            : ${AKS_NAME}"
echo " Redis          : ${REDIS_NAME}"
echo "════════════════════════════════════════════════════"

# ── 1. Resource Group ─────────────────────────────────────────────────────────
echo ""
echo "[1/8] Creating resource group '${RESOURCE_GROUP}'…"
az group create --name "${RESOURCE_GROUP}" --location "${LOCATION}" --output none

# ── 2. Azure Container Registry ───────────────────────────────────────────────
echo ""
echo "[2/8] Creating ACR '${ACR_NAME}' (Basic)…"
az acr create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${ACR_NAME}" \
  --sku Basic \
  --admin-enabled false \
  --output none

# ── 3. Azure Managed Redis (Balanced_B0 — 0.5 GB) ───────────────────────────
echo ""
echo "[3/8] Creating Azure Managed Redis '${REDIS_NAME}' (Balanced_B0 — 0.5 GB)…"
echo "      This typically takes 5-10 minutes. Waiting…"
az redisenterprise create \
  --resource-group "${RESOURCE_GROUP}" \
  --cluster-name "${REDIS_NAME}" \
  --location "${LOCATION}" \
  --sku "Balanced_B0" \
  --output none

# Create the default database on the cluster
az redisenterprise database create \
  --resource-group "${RESOURCE_GROUP}" \
  --cluster-name "${REDIS_NAME}" \
  --name "default" \
  --client-protocol "Encrypted" \
  --eviction-policy "AllKeysLRU" \
  --output none

# Poll until cluster provisioning completes
echo "      Waiting for Azure Managed Redis provisioning to complete…"
while true; do
  STATE=$(az redisenterprise show \
    --resource-group "${RESOURCE_GROUP}" \
    --cluster-name "${REDIS_NAME}" \
    --query "provisioningState" \
    --output tsv)
  echo "      State: ${STATE}"
  if [[ "${STATE}" == "Succeeded" ]]; then break; fi
  if [[ "${STATE}" == "Failed" ]]; then
    echo "ERROR: Azure Managed Redis provisioning failed." >&2; exit 1
  fi
  sleep 30
done

# Azure Managed Redis hostname and port (TLS 10000)
REDIS_HOST="${REDIS_NAME}.${LOCATION}.redisenterprise.cache.azure.net"
REDIS_KEY=$(az redisenterprise database list-keys \
  --resource-group "${RESOURCE_GROUP}" \
  --cluster-name "${REDIS_NAME}" \
  --name "default" \
  --query "primaryKey" --output tsv)

# ── 4. AKS Cluster ────────────────────────────────────────────────────────────
echo ""
echo "[4/8] Creating AKS cluster '${AKS_NAME}' (${NODE_COUNT}× ${NODE_VM})…"
az aks create \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${AKS_NAME}" \
  --node-count "${NODE_COUNT}" \
  --node-vm-size "${NODE_VM}" \
  --attach-acr "${ACR_NAME}" \
  --enable-managed-identity \
  --generate-ssh-keys \
  --output none

echo ""
echo "[5/8] Fetching AKS credentials…"
az aks get-credentials \
  --resource-group "${RESOURCE_GROUP}" \
  --name "${AKS_NAME}" \
  --overwrite-existing

# ── 5. Build & push Docker image ──────────────────────────────────────────────
echo ""
echo "[6/8] Building and pushing Docker image…"
az acr login --name "${ACR_NAME}"
docker build -t "${IMAGE_FULL}" .
docker push "${IMAGE_FULL}"

# ── 6. Kubernetes resources ───────────────────────────────────────────────────
echo ""
echo "[7/8] Deploying to Kubernetes…"

# Update image reference in deployment.yaml before applying
sed "s|acrchatbot.azurecr.io/chatbot:latest|${IMAGE_FULL}|g" k8s/deployment.yaml \
  > /tmp/deployment-patched.yaml

kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml

# Create secret from live values (skip if already exists — idempotent)
echo "      Creating Kubernetes secret (populate FOUNDRY + COSMOS values)…"
echo ""
echo "      ⚠️  You must set the following variables before continuing:"
echo "         AZURE_FOUNDRY_ENDPOINT, AZURE_FOUNDRY_KEY, COSMOS_ENDPOINT, COSMOS_KEY"
echo ""
read -rp "      AZURE_FOUNDRY_ENDPOINT: " FOUNDRY_ENDPOINT
read -rp "      AZURE_FOUNDRY_KEY: " FOUNDRY_KEY
read -rp "      COSMOS_ENDPOINT: " COSMOS_ENDPOINT
read -rp "      COSMOS_KEY: " COSMOS_KEY

kubectl create secret generic chatbot-secret \
  --namespace chatbot \
  --from-literal=AZURE_FOUNDRY_ENDPOINT="${FOUNDRY_ENDPOINT}" \
  --from-literal=AZURE_FOUNDRY_KEY="${FOUNDRY_KEY}" \
  --from-literal=COSMOS_ENDPOINT="${COSMOS_ENDPOINT}" \
  --from-literal=COSMOS_KEY="${COSMOS_KEY}" \
  --from-literal=REDIS_HOST="${REDIS_HOST}" \
  --from-literal=REDIS_PASSWORD="${REDIS_KEY}" \
  --dry-run=client -o yaml | kubectl apply -f -

kubectl apply -f /tmp/deployment-patched.yaml
kubectl apply -f k8s/service.yaml

# ── 7. Wait & report ──────────────────────────────────────────────────────────
echo ""
echo "[8/8] Waiting for rollout…"
kubectl rollout status deployment/chatbot -n chatbot --timeout=180s

echo ""
echo "════════════════════════════════════════════════════"
echo " Deployment complete!"
echo ""
EXTERNAL_IP=""
echo " Waiting for LoadBalancer external IP…"
while [[ -z "${EXTERNAL_IP}" ]]; do
  EXTERNAL_IP=$(kubectl get svc chatbot -n chatbot \
    --output jsonpath="{.status.loadBalancer.ingress[0].ip}" 2>/dev/null || true)
  sleep 5
done
echo " Chatbot URL : http://${EXTERNAL_IP}"
echo " Health      : http://${EXTERNAL_IP}/health"
echo " Redis name  : ${REDIS_NAME}"
echo " ACR name    : ${ACR_NAME}"
echo "════════════════════════════════════════════════════"
