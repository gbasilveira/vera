---
title: "API SDK — VeraRouter, VeraWebSocket, WebSocketManager"
description: "Plugin-facing SDK for contributing REST endpoints and WebSocket handlers."
tags: [api, rest, websocket, router, sdk, fastapi]
---

# API SDK — VeraRouter, VeraWebSocket, WebSocketManager

**File:** `core/api.py`

Plugins import from here to contribute REST and WebSocket endpoints.  They
never import `fastapi` directly — `core.api` is the single boundary.

## VeraRouter

Wraps `fastapi.APIRouter`.  Expose it via the `interfaces.api.routes`
extension point.

```python
# plugins/my_plugin/api.py
from core.api import VeraRouter, vera_deps
from core.deps import VeraDeps

router = VeraRouter(prefix="/my-plugin", tags=["my-plugin"])

@router.get("/status")
async def status(deps: VeraDeps = vera_deps) -> dict:
    return {"user": deps.user_id, "tools": len(deps.kernel.list_tools())}

@router.post("/run")
async def run(body: dict, deps: VeraDeps = vera_deps) -> dict:
    result = await deps.run_tool("my_plugin.do_thing", **body)
    return {"result": result}
```

Supported methods: `get`, `post`, `put`, `patch`, `delete`, `websocket`.

## vera_deps

A pre-built `fastapi.Depends(...)` that:

1. Extracts the `Bearer` token from `Authorization`
2. Calls `auth_manager.verify_session(token)`
3. Builds and returns a fully wired `VeraDeps`

The same `VeraDeps` object that tools receive in the middleware chain — all
services (kernel, bus, VFS, secrets, ws_manager) already injected.

```python
from core.api import vera_deps
from core.deps import VeraDeps

@router.get("/me")
async def me(deps: VeraDeps = vera_deps) -> dict:
    return {"user": deps.user_id, "role": deps.user_role}
```

## VeraWebSocket

Thin wrapper around FastAPI's `WebSocket`.

```python
from core.api import VeraRouter, VeraWebSocket, vera_deps
from core.deps import VeraDeps

router = VeraRouter(prefix="/my-plugin")

@router.websocket("/stream")
async def stream(raw_ws, deps: VeraDeps = vera_deps):
    ws = VeraWebSocket(raw_ws, user_id=deps.user_id)
    await ws.accept()
    await deps.ws_manager.connect("my-plugin", deps.user_id, ws)
    try:
        while True:
            msg = await ws.receive_json()
            result = await deps.run_tool("my_plugin.do_thing", **msg)
            await ws.send_json({"result": result})
    except Exception:
        pass
    finally:
        deps.ws_manager.disconnect("my-plugin", ws)
```

## WebSocketManager

Injected via `deps.ws_manager`.  Available in both REST handlers and tool
functions.  Lets tools push events to connected WebSocket clients.

```python
# Inside a tool function — push to all clients watching "my-plugin"
async def do_thing(deps, text: str) -> str:
    result = process(text)
    await deps.ws_manager.broadcast("my-plugin", {"event": "done", "result": result})
    return result
```

| Method | Description |
|---|---|
| `await connect(ns, user_id, ws)` | Register an accepted connection |
| `disconnect(ns, ws)` | Remove a connection |
| `await broadcast(ns, data)` | Send to all connections in namespace |
| `await broadcast_all(data)` | Send to every connection |
| `await send_to_user(user_id, data, ns=None)` | Send to all of one user's connections |
| `connection_count(ns=None)` | Count active connections |
| `connected_users(ns=None)` | List unique user IDs |
| `namespaces()` | List namespaces with active connections |

## Registering routes via the extension system

```yaml
# manifest.yaml
contributes:
  - point: interfaces.api.routes
    type: router
    params:
      prefix: /my-plugin
      handler: "plugins.my_plugin.api:router"
      tags: [my-plugin]

  - point: interfaces.api.websocket
    type: ws_namespace
    params:
      namespace: my-plugin
      description: "Real-time events from My Plugin"
```

The API server mounts contributed routers automatically at startup — no
changes to `interfaces/api/main.py` required.
