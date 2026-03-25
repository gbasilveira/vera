---
title: "VeraFileSystem — Virtual KV Store"
description: "Key-value store used by the kernel and middleware for ephemeral and persistent data."
tags: [vfs, kv, storage, sqlite, redis]
---

# VeraFileSystem — Virtual KV Store

**File:** `core/vfs/base.py`
**Default implementation:** `LocalFS` (`core/vfs/local_fs.py`) backed by aiosqlite

## API

```python
await vfs.set("cost:alice:2024-01-15:llm.generate", b"1234", ttl=3600)
value = await vfs.get("cost:alice:2024-01-15:llm.generate")   # bytes or None
await vfs.delete("cost:alice:2024-01-15:llm.generate")
keys = await vfs.list_keys("cost:alice:")                      # prefix scan
await vfs.close()
```

## Key naming convention

`<domain>:<entity>:<id>` — examples:

| Key pattern | Written by |
|---|---|
| `pii:mapping:<call_id>` | PIIMaskerMiddleware |
| `cost:<agent_id>:<date>:<tool>` | CostRecorderMiddleware |
| `<plugin_ns>:<entity>:<id>` | Plugin-specific storage |

## LocalFS

- Storage: SQLite via `aiosqlite` at `$VERA_VFS_PATH` (default `data/vera_vfs.db`)
- TTL is enforced lazily on read (expired keys return `None` and are deleted)
- Thread-safe for single-process use

## RedisFS

- Planned; swap by setting `VERA_VFS_BACKEND=redis` and `VERA_REDIS_URL`
- Enables cross-process and multi-tenant deployments

## Plugin storage namespace

Each plugin declares its VFS namespace in `manifest.yaml`:

```yaml
storage:
  namespace: my_plugin     # VFS key prefix
  backend: local           # local | redis | inherit
  ttl_seconds: 3600
```
