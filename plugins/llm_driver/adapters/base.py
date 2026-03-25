"""
LLMAdapter — Abstract interface for LLM provider adapters.

Concrete adapters: OpenAIAdapter, AnthropicAdapter, OllamaAdapter...

IMPORTANT: Plugins must NEVER import openai/anthropic/ollama directly.
All LLM calls must go through ctx.deps.run_tool('llm.*').
The LLM Driver plugin is the ONLY place where SDK imports are permitted.
"""
import dataclasses
from abc import ABC, abstractmethod
from typing import AsyncIterator

from pydantic import BaseModel


@dataclasses.dataclass
class TokenUsage:
    """Token consumption and cost for a single LLM call."""
    prompt_tokens:     int
    completion_tokens: int
    total_tokens:      int
    cost_usd:          float


class LLMAdapter(ABC):
    """
    Abstract LLM provider adapter.

    Each adapter wraps one provider (OpenAI / Anthropic / Ollama).
    The LLMDriver plugin selects the active adapter from VERA_LLM_PROVIDER.
    """
    provider: str  # 'openai' | 'anthropic' | 'ollama'

    @abstractmethod
    async def generate_structured(
        self,
        prompt: str,
        schema: type[BaseModel],
        model: str,
        temperature: float,
    ) -> tuple[BaseModel, TokenUsage]:
        """
        Generate a structured response conforming to the given Pydantic schema.
        Returns (parsed_model_instance, token_usage).
        """
        ...

    @abstractmethod
    async def stream(self, prompt: str, model: str) -> AsyncIterator[str]:
        """Stream a plain-text response token by token."""
        ...

    @abstractmethod
    async def embed(self, text: str, model: str) -> list[float]:
        """Return a dense vector embedding for the given text."""
        ...