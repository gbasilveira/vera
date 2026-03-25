---
title: "VFS — LocalFS & RedisFS"
description: "Concrete implementations of the VeraFileSystem KV store."
tags: [vfs, localfs, redis, storage, sqlite]
---

# VFS Implementations

## LocalFS (`core/vfs/local_fs.py`)

Default backend.  Uses `aiosqlite` for an async SQLite database.

```
Schema:
  kv_store (key TEXT PRIMARY KEY, value BLOB, expires_at REAL)
```

- **TTL**: stored as Unix timestamp; expired entries are deleted on read
- **Path**: `$VERA_VFS_PATH` (default `data/vera_vfs.db`)
- **Close**: always call `await vfs.close()` to flush WAL

## RedisFS (`core/vfs/redis_fs.py`)

Planned.  Activate with:

```
VERA_VFS_BACKEND=redis
VERA_REDIS_URL=redis://localhost:6379/0
```

Enables:
- Cross-process shared state
- Built-in TTL support via Redis `EXPIRE`
- Pub/sub for cache invalidation

## Choosing a backend

| Scenario | Backend |
|---|---|
| Single-process development / CI | `local` (default) |
| Multi-agent or multi-tenant production | `redis` |
| Air-gapped / no external services | `local` |
