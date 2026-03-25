import os
from core.vfs.base import VeraFileSystem


def create_vfs() -> VeraFileSystem:
    """Factory that selects VFS backend from VERA_VFS_BACKEND env var."""
    backend = os.getenv("VERA_VFS_BACKEND", "local")
    if backend == "local":
        from core.vfs.local_fs import LocalFS
        return LocalFS()
    elif backend == "redis":
        from core.vfs.redis_fs import RedisFS  # Phase 6
        return RedisFS()
    else:
        raise ValueError(f"Unknown VFS backend: {backend}")