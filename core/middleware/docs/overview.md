---
title: "Middleware Chain — Overview"
description: "Architecture, execution order, and the ToolCallContext contract."
tags: [middleware, chain, execution, context]
---

# Middleware Chain — Overview

**Directory:** `core/middleware/`

Every tool call flows through a sorted chain of middleware layers.  Order
numbers determine sequence: lower numbers run first on the way *in* and last
on the way *out*.

## Execution order

```
BEFORE_CALL  (ascending order)
  10  AuthGuardMiddleware         permission check
  20  SecretsInjectorMiddleware   inject API keys
  30  PIIMaskerMiddleware         mask outbound PII
  40  RetryMiddleware             wrap execution with backoff

      ── tool function executes ──

AFTER_CALL   (ascending order)
  30  PIIMaskerMiddleware         restore inbound PII
  70  CostRecorderMiddleware      record token usage
  80  AuditLoggerMiddleware       write audit.jsonl

ON_ERROR     (all middleware, ascending)
  every layer's on_error() called
```

## ToolCallContext (frozen dataclass)

Passed through every middleware.  Immutable — use helper methods to derive
new versions:

```python
ctx.with_payload(new_dict)           # returns copy with updated payload
ctx.with_injected_secrets(secrets)   # returns copy with added secrets
```

| Field | Type | Description |
|---|---|---|
| `call_id` | str | UUID for this specific call |
| `tool_name` | str | e.g. `llm.generate` |
| `plugin_name` | str | owning plugin |
| `agent_id` | str | caller's user_id |
| `user_role` | str | e.g. `owner`, `intern` |
| `user_id` | str | authenticated user |
| `tenant_id` | str | multi-tenancy key |
| `payload` | dict | tool arguments |
| `is_external` | bool | triggers PII masking |
| `vfs` | VeraFileSystem | KV store |
| `secrets` | SecretsManager | secrets access |
| `enforcer` | casbin.Enforcer | policy enforcer |
| `bus` | VeraBus | event bus |
| `injected_secrets` | dict | filled by SecretsInjector |

## Writing a custom middleware

```python
from core.middleware.base import VeraMiddleware, ToolCallContext

class MyMiddleware(VeraMiddleware):
    order = 55   # pick a number in the available gap

    async def before_call(self, ctx: ToolCallContext) -> ToolCallContext:
        # inspect or modify ctx; return (possibly new) ctx
        return ctx

    async def after_call(self, ctx: ToolCallContext, result) -> Any:
        return result

    async def on_error(self, ctx: ToolCallContext, error: Exception) -> None:
        pass   # default; override to react to failures
```

Register it:

```bash
vera middleware enable MyMiddleware --class mypackage.middleware.MyMiddleware --order 55
```

Or in `data/middleware.json` directly.
