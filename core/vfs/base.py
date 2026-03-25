"""
VeraFileSystem — Abstract Virtual File System interface.

All VFS backends implement this ABC.
Plugins never import a concrete backend directly; they receive a VeraFileSystem instance via ctx.deps.vfs (VeraDeps).

Key naming convention: plugin:entity:id
  e.g. gmail:thread:abc123
       pii:mapping:call_456
       cost:agent_x:2026-03-24:llm.generate_structured
"""
from abc import ABC, abstractmethod
from typing import Optional


class VeraFileSystem(ABC):
    """Plugin-agnostic key-value storage with optional TTL."""

    @abstractmethod
    async def get(self, key: str) -> Optional[bytes]:
        """Return value for key, or None if missing/expired."""
        ...

    @abstractmethod
    async def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> None:
        """Upsert key. ttl is seconds until expiry; None means no expiry."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Delete key. No-op if key does not exist."""
        ...

    @abstractmethod
    async def list_keys(self, prefix: str) -> list[str]:
        """Return all non-expired keys that start with prefix."""
        ...