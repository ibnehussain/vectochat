import logging

from fastapi import APIRouter, HTTPException

from app import cosmos_client, foundry_client, redis_client
from app import rag
from app.models import ChatRequest, ChatResponse, HistoryResponse, HistoryMessage

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    session_id = request.session_id
    message = request.message

    # 1. Fetch conversation history — Redis first, then CosmosDB
    history = await redis_client.get_history(session_id)
    if history is None:
        logger.debug("History cache miss for session %s — reading CosmosDB.", session_id)
        history = cosmos_client.get_history(session_id)
    else:
        logger.debug("History cache hit for session %s.", session_id)

    # 2. Retrieve RAG context (embedding cached in Redis)
    context, sources = await rag.retrieve_context(message)

    # 3. Build prompt and call Foundry LLM
    messages = rag.build_messages(query=message, context=context, history=history)
    try:
        reply = foundry_client.get_chat_completion(messages)
    except Exception as exc:
        logger.error("Foundry chat completion failed: %s", exc)
        raise HTTPException(status_code=502, detail="LLM service unavailable.") from exc

    # 4. Persist both turns to CosmosDB (fire-and-hopefully-complete; errors logged)
    try:
        cosmos_client.save_message(session_id, "user", message)
        cosmos_client.save_message(session_id, "assistant", reply)
    except Exception as exc:
        logger.error("Failed to persist messages to CosmosDB for session %s: %s", session_id, exc)

    # 5. Update Redis history cache (write-through)
    updated_history = history + [
        {"role": "user", "content": message},
        {"role": "assistant", "content": reply},
    ]
    await redis_client.set_history(session_id, updated_history)

    return ChatResponse(reply=reply, session_id=session_id, sources=sources)


@router.get("/history/{session_id}", response_model=HistoryResponse)
async def get_history(session_id: str) -> HistoryResponse:
    # Redis first
    history = await redis_client.get_history(session_id)
    if history is None:
        history = cosmos_client.get_history(session_id)

    messages = [
        HistoryMessage(
            role=msg["role"],
            content=msg["content"],
            timestamp=msg.get("timestamp", 0.0),
        )
        for msg in history
    ]
    return HistoryResponse(session_id=session_id, messages=messages)


@router.delete("/history/{session_id}")
async def delete_history(session_id: str) -> dict:
    # Remove from both cache and CosmosDB
    await redis_client.invalidate_history(session_id)
    deleted = cosmos_client.delete_history(session_id)
    return {"session_id": session_id, "deleted_count": deleted}
