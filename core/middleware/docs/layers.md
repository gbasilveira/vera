---
title: "Middleware Layers — Reference"
description: "What each built-in middleware layer does and when it fires."
tags: [middleware, auth, pii, retry, cost, audit, secrets]
---

# Middleware Layers — Reference

## AuthGuardMiddleware (order 10)

**File:** `core/middleware/auth.py`

- `before_call`: iterates `ctx.user_roles` and calls
  `enforcer.enforce(role, tool_name, "execute")` for each role
- Access is **granted** when any role allows it (and none explicitly deny it)
- Raises `PermissionDenied` if no role permits the action
- Emits `security.permission_denied` on the bus with `user_roles` list

## SecretsInjectorMiddleware (order 20)

**File:** `core/middleware/secret_injector.py`

- `before_call`: reads `manifest.storage.secrets_required` for the plugin
- Retrieves each secret from `SecretsManager`
- Stores them in `ctx.injected_secrets` (never in the payload)
- Raises `SecretNotFound` if any required secret is missing

## PIIMaskerMiddleware (order 30)

**File:** `core/middleware/pii_masker.py`

Only active for `is_external=True` tools (those that call external APIs).

- `before_call`: detects PII patterns in payload, replaces with tokens,
  stores the token→value mapping in VFS under `pii:mapping:<call_id>` (TTL 3600 s)
- `after_call`: restores original values in the result, deletes the mapping

## RetryMiddleware (order 40)

**File:** `core/middleware/retry.py`

- Wraps the tool execution with exponential backoff
- Config from `manifest.retry`: `max_attempts`, `backoff_factor`, `retryable_errors`
- Emits `tool.retry_attempt` for each retry

```python
# retry_with_backoff helper (also importable directly)
from core.middleware.retry import retry_with_backoff
result = await retry_with_backoff(fn, ctx, deps, max_attempts=3, backoff_factor=2)
```

## CostRecorderMiddleware (order 70)

**File:** `core/middleware/cost_recorder.py`

- `after_call`: checks result for a `TokenUsage` namedtuple
- Aggregates into VFS key: `cost:<agent_id>:<YYYY-MM-DD>:<tool_name>`
- Data visible via `vera logs costs`

## AuditLoggerMiddleware (order 80)

**File:** `core/middleware/auditor.py`

- `after_call` + `on_error`: appends one JSON line to `data/logs/audit.jsonl`
- Logged fields: `timestamp`, `call_id`, `tool_name`, `plugin_name`, `user_id`,
  `user_role` (primary role), `tenant_id`, `status`, `duration_ms`, `error`
- **Payload and result are never logged** (PII safety)
- Data visible via `vera logs audit`
