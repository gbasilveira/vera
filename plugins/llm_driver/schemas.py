"""Pydantic schemas for the LLM Driver plugin (Phase 4)."""
from pydantic import BaseModel

from plugins.llm_driver.adapters.base import TokenUsage


class LLMGenerateRequest(BaseModel):
    prompt: str
    schema_name: str    # Name of the registered Pydantic schema to parse into
    temperature: float = 0.1


class LLMStreamRequest(BaseModel):
    prompt: str


class LLMEmbedRequest(BaseModel):
    text: str


class LLMGenerateResponse(BaseModel):
    result: dict        # Serialised Pydantic model (avoid generic BaseModel nesting issues)
    usage: TokenUsage