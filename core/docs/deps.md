---
title: "VeraDeps & VeraDepsFactory"
description: "Dependency injection container carrying identity, roles, and all core services."
tags: [deps, di, identity, factory, permissions, websocket]
---

# VeraDeps & VeraDepsFactory

**File:** `core/deps.py`

`VeraDeps` is the single object passed into every tool call and every API
route handler. It carries the caller's identity (including all their roles)
and references to every core service so plugins never need to import from
`core/` directly.

## Fields

```python
class VeraDeps(BaseModel):
    # Identity
    user_id:    str
    user_roles: list[str]   # all roles — authoritative for enforcement
    session_id: str
    tenant_id:  str = "default"

    # Core services
    kernel:   VeraKernel
    bus:      VeraBus
    vfs:      VeraFileSystem
    secrets:  SecretsManager
    enforcer: casbin.Enforcer
    tracer:   opentelemetry.trace.Tracer

    # API services (None in CLI context, live in API context)
    ws_manager: WebSocketManager | None = None

    # LLM config
    llm_provider:    str   = "ollama"
    llm_model:       str   = "llama3"
    llm_temperature: float = 0.1

    # Memory
    memory_namespace: str = "default"
```

### `user_role` property

`deps.user_role` is a read-only property returning the first role from
`user_roles`, or `"guest"` when the list is empty. Use it **for display and
logging only** — never for authorization decisions.

---

## Permission helpers

```python
deps.can("llm.generate")                  # True if any role allows execute
deps.can("policy.rules", action="manage") # check a non-execute action
deps.can_all("llm.generate", "memory.store")  # True only if ALL allowed
deps.can_any("agent.run", "agent.edit")       # True if at least ONE allowed
```

All three methods iterate over `user_roles` and grant access when any role
passes the Casbin check. They are safe to call before `run_tool()` for
pre-flight checks without side effects.

---

## Tool execution

```python
await deps.run_tool("llm.generate", text="hello")
```

This is the **only** way plugins should call other tools. It passes through
the full middleware chain (auth, PII masking, retries, audit, etc.).

---

## ws_manager

`deps.ws_manager` is a `WebSocketManager` instance when running inside the
API server. It is `None` in CLI context:

```python
async def do_thing(deps, text: str) -> str:
    result = process(text)
    if deps.ws_manager:
        await deps.ws_manager.broadcast("my-plugin", {"event": "done", "result": result})
    return result
```

See `vera docs show core/api` for full `WebSocketManager` API.

---

## VeraDepsFactory

Creates `VeraDeps` instances bound to a specific identity.

```python
factory = VeraDepsFactory(kernel, bus, vfs, secrets, security, ws_manager=ws_manager)

# New API — list of roles
deps = factory.create(
    user_id="johndow",
    user_roles=["admin", "agent_editor"],
    session_id=None,         # auto-generated UUID if omitted
    tenant_id="acme",
    llm_provider="openai",   # optional overrides
    llm_model="gpt-4o",
)

# Legacy API — single role string (converted to [role] internally)
deps = factory.create(user_id="alice", user_role="owner")
```

The factory is created once in `setup_kernel()`, stored on the kernel as
`kernel._deps_factory`, and reused for every incoming request.
