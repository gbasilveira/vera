---
title: "setup_kernel() — Bootstrap"
description: "One-call async function that wires all core services together."
tags: [setup, bootstrap, init]
---

# setup_kernel() — Bootstrap

**File:** `core/setup.py`

`setup_kernel()` is the single entry point for initialising the entire VERA
runtime. It is called by the CLI at the start of every command that needs the
kernel, and by the API server during its lifespan startup.

## What it does

1. Creates `VeraBus` (`BlinkerBus` by default)
2. Creates `VeraFileSystem` (`LocalFS` by default)
3. Creates `SecretsManager` (keyring or SQLite)
4. Creates `SecurityManager` (loads Casbin model + policy)
5. Sets up OpenTelemetry tracer
6. Wires Prometheus metrics to the bus
7. Initialises `AuthManager(vfs, security=security)` — the SecurityManager
   reference is passed so `AuthManager` can enrich `user_roles` from Casbin
   after every login and auto-migrate legacy DB roles
8. Registers `LocalAuthProvider`, calls `auth_manager.setup(secrets)`
9. Initialises `VeraKernel` singleton
10. Calls `kernel.set_auth_manager(auth_manager)` and `kernel.set_security(security)`
11. Loads middleware chain from `data/middleware.json` (falls back to defaults)
12. Calls `kernel.load_all_plugins()` — each plugin registers tools, listeners,
    auth providers, extension points, contributions, and **named permissions**
    declared in `manifest.permissions.provides`
13. Creates `WebSocketManager`
14. Creates `VeraDepsFactory` (with `ws_manager`)
15. Stores `factory` as `kernel._deps_factory` and `ws_manager` as `kernel._ws_manager`
16. Returns `(kernel, bus, vfs, secrets, security, tracer, factory)`

## Usage

```python
from core.setup import setup_kernel

kernel, bus, vfs, secrets, security, tracer, factory = await setup_kernel()

deps = factory.create(user_id="johndow", user_roles=["admin", "agent_editor"])
result = await deps.run_tool("llm.generate", text="hello")

await vfs.close()
```

## In the API server

The API server calls `setup_kernel()` inside the FastAPI `lifespan` context
manager. Plugin routers are then mounted from
`kernel.extensions.get_contributions("interfaces.api.routes")`.

## Environment variables consumed

See `vera docs show quickstart` for the full list.
