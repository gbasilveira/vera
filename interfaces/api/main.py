"""
VERA REST & WebSocket API server.

Start with:
    vera api serve
    uvicorn interfaces.api.main:app --reload

The server boots the full kernel, then mounts every router contributed to
the ``interfaces.api.routes`` extension point by loaded plugins.

Built-in routes
---------------
GET  /health                    Liveness probe
GET  /vera/info                 Kernel / version metadata
POST /vera/auth/login           Obtain a session token
POST /vera/auth/logout          Revoke the current session token
GET  /vera/tools                List all registered tools
POST /vera/tools/{tool_name}    Execute a tool through the middleware chain
WS   /vera/ws/{namespace}       General-purpose WebSocket endpoint
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Boot the kernel, mount plugin routers, then gracefully shut down."""
    from core.setup import setup_kernel
    from core.extensions import ExtensionRegistry

    kernel, bus, vfs, secrets, security, tracer, factory = await setup_kernel()

    app.state.kernel  = kernel
    app.state.vfs     = vfs
    app.state.factory = factory

    # Mount plugin-contributed routers
    for contrib in kernel.extensions.get_contributions("interfaces.api.routes"):
        params       = contrib.params
        handler_path = params.get("handler", "")
        prefix       = params.get("prefix", f"/{contrib.plugin}")
        tags         = params.get("tags") or [contrib.plugin]
        if not handler_path:
            continue
        try:
            obj = ExtensionRegistry.resolve_import(handler_path)
            # Accept both VeraRouter wrappers and raw APIRouter instances
            router = obj._fastapi_router if hasattr(obj, "_fastapi_router") else obj
            app.include_router(router, prefix=prefix, tags=tags)
            print(f"[VERA API] Mounted {contrib.plugin} at {prefix}")
        except Exception as exc:
            print(f"[VERA API] Warning: could not mount '{contrib.plugin}': {exc}")

    yield

    # Shutdown
    await vfs.close()
    auth_manager = kernel.get_auth_manager()
    if auth_manager:
        await auth_manager.teardown()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="VERA API",
    description="Visible Edge Reasoning Architecture — REST & WebSocket gateway",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/vera/docs",
    redoc_url="/vera/redoc",
    openapi_url="/vera/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("VERA_API_CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Shared dependency ─────────────────────────────────────────────────────────

from core.api import vera_deps   # noqa: E402
from core.deps import VeraDeps   # noqa: E402


# ── Built-in routes ───────────────────────────────────────────────────────────

@app.get("/health", tags=["system"])
async def health() -> dict:
    """Liveness probe — no auth required."""
    return {"status": "ok"}


@app.get("/vera/info", tags=["system"])
async def info(deps: VeraDeps = vera_deps) -> dict:
    """Kernel metadata: version, loaded plugins, middleware chain."""
    try:
        from importlib.metadata import version as _v
        vera_ver = _v("vera")
    except Exception:
        vera_ver = "dev"

    plugins = deps.kernel.list_plugins()
    mw = [
        {"name": type(m).__name__, "order": m.order}
        for m in sorted(deps.kernel._middleware, key=lambda m: m.order)
    ]
    return {
        "vera_version": vera_ver,
        "plugins": [{"name": p["name"], "version": p["version"]} for p in plugins],
        "middleware": mw,
        "user": deps.user_id,
        "role": deps.user_role,
    }


# ── Auth routes ───────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    provider: str = "local"
    username: str
    password: str


class LoginResponse(BaseModel):
    session_token: str
    user_id: str
    user_role: str
    expires_at: str
    provider: str


@app.post("/vera/auth/login", tags=["auth"], response_model=LoginResponse)
async def login(body: LoginRequest) -> LoginResponse:
    """Authenticate and receive a session token.  No existing session required."""
    from core.kernel import VeraKernel
    kernel = VeraKernel.get_instance()
    auth_manager = kernel.get_auth_manager()
    if auth_manager is None:
        raise HTTPException(status_code=503, detail="Auth not configured.")

    try:
        result = await auth_manager.authenticate(
            body.provider,
            {"username": body.username, "password": body.password},
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc))

    return LoginResponse(
        session_token=result.session_token,
        user_id=result.user_id,
        user_role=result.user_role,
        expires_at=result.expires_at.isoformat(),
        provider=result.provider,
    )


@app.post("/vera/auth/logout", tags=["auth"])
async def logout(deps: VeraDeps = vera_deps) -> dict:
    """Revoke the current session token."""
    from core.kernel import VeraKernel
    kernel = VeraKernel.get_instance()
    auth_manager = kernel.get_auth_manager()
    if auth_manager:
        await auth_manager.revoke_session(deps.session_id)
    return {"status": "logged out"}


# ── Tool routes ───────────────────────────────────────────────────────────────

@app.get("/vera/tools", tags=["tools"])
async def list_tools(
    plugin: Optional[str] = None,
    deps: VeraDeps = vera_deps,
) -> dict:
    """List all registered tools, optionally filtered by plugin."""
    tools = deps.kernel.list_tool_details()
    if plugin:
        tools = [t for t in tools if t["plugin"] == plugin]
    return {"tools": tools, "count": len(tools)}


@app.post("/vera/tools/{tool_name}", tags=["tools"])
async def run_tool(
    tool_name: str,
    payload: dict = {},
    deps: VeraDeps = vera_deps,
) -> dict:
    """Execute a registered tool through the full middleware chain."""
    if not deps.kernel.has_tool(tool_name):
        raise HTTPException(
            status_code=404,
            detail=f"Tool '{tool_name}' not found.  "
                   f"GET /vera/tools to see available tools.",
        )
    try:
        result = await deps.run_tool(tool_name, **payload)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"tool": tool_name, "result": result}


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/vera/ws/{namespace}")
async def ws_endpoint(
    namespace: str,
    raw_ws: WebSocket,
    token: Optional[str] = None,
) -> None:
    """General-purpose WebSocket endpoint.

    Authenticate by passing the session token as a query parameter::

        ws://host/vera/ws/my-namespace?token=<session_token>

    Once connected, send JSON messages to execute tools::

        {"tool": "my_plugin.do_thing", "text": "hello"}

    The server replies with::

        {"tool": "my_plugin.do_thing", "result": "...", "error": null}
    """
    from core.kernel import VeraKernel
    from core.auth.base import SessionExpired, SessionNotFound
    from core.api import VeraWebSocket

    # Token from query param (WS can't set headers in browsers)
    token = raw_ws.query_params.get("token", "")
    if not token:
        await raw_ws.close(code=4001, reason="Missing token query parameter")
        return

    kernel = VeraKernel.get_instance()
    auth_manager = kernel.get_auth_manager()

    try:
        session = await auth_manager.verify_session(token)
    except (SessionNotFound, SessionExpired) as exc:
        await raw_ws.close(code=4001, reason=str(exc))
        return

    factory = getattr(kernel, "_deps_factory", None)
    if factory is None:
        await raw_ws.close(code=4503, reason="Server not ready")
        return

    deps = factory.create(
        user_id=session.user_id,
        user_role=session.user_role,
        session_id=session.session_token,
    )

    ws = VeraWebSocket(raw_ws, user_id=session.user_id)
    await ws.accept()

    ws_manager = getattr(kernel, "_ws_manager", None)
    if ws_manager:
        await ws_manager.connect(namespace, session.user_id, ws)

    try:
        while True:
            try:
                msg = await ws.receive_json()
            except Exception:
                break

            tool_name = msg.pop("tool", None)
            if not tool_name:
                await ws.send_json({"error": "Missing 'tool' field in message"})
                continue

            if not kernel.has_tool(tool_name):
                await ws.send_json({"tool": tool_name, "error": "Tool not found"})
                continue

            try:
                result = await deps.run_tool(tool_name, **msg)
                await ws.send_json({"tool": tool_name, "result": result, "error": None})
            except Exception as exc:
                await ws.send_json({"tool": tool_name, "result": None, "error": str(exc)})

    except WebSocketDisconnect:
        pass
    finally:
        if ws_manager:
            ws_manager.disconnect(namespace, ws)
