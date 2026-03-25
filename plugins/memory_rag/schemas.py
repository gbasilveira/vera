"""Pydantic schemas for the Memory RAG plugin (Phase 4)."""
from pydantic import BaseModel


class MemoryChunk(BaseModel):
    """A single chunk retrieved from the vector store."""
    chunk_id:  str
    content:   str
    namespace: str
    metadata:  dict
    score:     float    # Similarity score [0, 1]; higher = more relevant


class StoreMemoryRequest(BaseModel):
    content:   str
    namespace: str
    metadata:  dict = {}


class RetrieveContextRequest(BaseModel):
    query:     str
    namespace: str
    top_k:     int = 5


class ForgetRequest(BaseModel):
    chunk_ids: list[str] | None = None
    namespace: str | None = None    # If set, deletes the entire namespace