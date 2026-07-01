from pydantic import BaseModel, Field
from typing import Literal


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=128)
    message: str = Field(..., min_length=1, max_length=4096)


class SourceChunk(BaseModel):
    id: str
    source: str
    category: str
    content_preview: str  # first 200 chars of the chunk


class ChatResponse(BaseModel):
    reply: str
    session_id: str
    sources: list[SourceChunk] = []


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    timestamp: float


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[HistoryMessage]


class HealthResponse(BaseModel):
    status: str
    redis: str
    cosmos: str
