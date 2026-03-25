"""RedisFS — Redis-backed VFS (Phase 6 implementation)."""
from core.vfs.base import VeraFileSystem


class RedisFS(VeraFileSystem):
    async def get(self, key, **_): raise NotImplementedError("RedisFS not yet implemented")
    async def set(self, key, value, ttl=None): raise NotImplementedError
    async def delete(self, key): raise NotImplementedError
    async def list_keys(self, prefix): raise NotImplementedError