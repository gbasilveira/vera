"""
VERA API SDK — plugin-facing abstractions for REST and WebSocket.

Plugins import from here; they never import fastapi directly.  This keeps
the fastapi coupling to a single boundary and lets VERA swap the underlying
framework without touching plugin code.

Typical plugin usage::

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

    # WebSocket — pushing events to a connected client
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
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

# FastAPI is a declared project dependency — safe to import in core.
from fastapi import APIRouter, Depends, Header, HTTPException, WebSocket as _FastAPIWebSocket
from fastapi import status as _status


# ── VeraRouter ────────────────────────────────────────────────────────────────

class VeraRouter:
    """High-level router for plugin REST endpoints.

    Wraps :class:`fastapi.APIRouter` so plugins never import fastapi directly.
    Expose it to the API server via the ``interfaces.api.routes`` extension point.
    """

    def __init__(
        self,
        prefix: str = "",
        tags: Optional[list[str]] = None,
    ) -> None:
        self._router = APIRouter(prefix=prefix, tags=tags or [])

    # ── HTTP method decorators ────────────────────────────────────────────

    def get(self, path: str, **kw):      return self._router.get(path, **kw)
    def post(self, path: str, **kw):     return self._router.post(path, **kw)
    def put(self, path: str, **kw):      return self._router.put(path, **kw)
    def patch(self, path: str, **kw):    return self._router.patch(path, **kw)
    def delete(self, path: str, **kw):   return self._router.delete(path, **kw)
    def websocket(self, path: str, **kw): return self._router.websocket(path, **kw)

    @property
    def _fastapi_router(self) -> APIRouter:
        """Internal: the underlying FastAPI router, used by the API server."""
        return self._router


# ── VeraWebSocket ─────────────────────────────────────────────────────────────

class VeraWebSocket:
    """Thin wrapper around a FastAPI WebSocket connection.

    Plugins receive one of these when their ``@router.websocket`` handler is
    called.  See :class:`WebSocketManager` for broadcast utilities.
    """

    def __init__(self, ws: _FastAPIWebSocket, user_id: str = "") -> None:
        self._ws = ws
        self.user_id = user_id

    async def accept(self, subprotocol: Optional[str] = None) -> None:
        await self._ws.accept(subprotocol)

    async def send_json(self, data: Any) -> None:
        await self._ws.send_json(data)

    async def send_text(self, text: str) -> None:
        await self._ws.send_text(text)

    async def send_bytes(self, data: bytes) -> None:
        await self._ws.send_bytes(data)

    async def receive_json(self) -> Any:
        return await self._ws.receive_json()

    async def receive_text(self) -> str:
        return await self._ws.receive_text()

    async def receive_bytes(self) -> bytes:
        return await self._ws.receive_bytes()

    async def close(self, code: int = 1000, reason: str = "") -> None:
        await self._ws.close(code, reason)


# ── WebSocketManager ──────────────────────────────────────────────────────────

class WebSocketManager:
    """Manages active WebSocket connections across all namespaces.

    Injected into every request via ``deps.ws_manager``.  Plugins use it to
    broadcast events to connected clients without holding raw socket references.

    Connection lifecycle (plugin responsibility)::

        ws = VeraWebSocket(raw_ws, user_id=deps.user_id)
        await ws.accept()
        await deps.ws_manager.connect("my-plugin", deps.user_id, ws)
        try:
            ...serve messages...
        finally:
            deps.ws_manager.disconnect("my-plugin", ws)
    """

    def __init__(self) -> None:
        # namespace → list of (user_id, VeraWebSocket)
        self._conns: dict[str, list[tuple[str, VeraWebSocket]]] = {}
        self._lock = asyncio.Lock()

    # ── Connection management ─────────────────────────────────────────────

    async def connect(self, namespace: str, user_id: str, ws: VeraWebSocket) -> None:
        """Register an accepted WebSocket under *namespace*."""
        async with self._lock:
            self._conns.setdefault(namespace, []).append((user_id, ws))

    def disconnect(self, namespace: str, ws: VeraWebSocket) -> None:
        """Remove *ws* from *namespace*.  Safe to call even if not registered."""
        conns = self._conns.get(namespace, [])
        self._conns[namespace] = [(uid, w) for uid, w in conns if w is not ws]

    # ── Broadcasting ──────────────────────────────────────────────────────

    async def broadcast(self, namespace: str, data: Any) -> int:
        """Send *data* (JSON) to every connection in *namespace*.

        Silently drops dead connections.  Returns number of messages sent.
        """
        dead: list[VeraWebSocket] = []
        sent = 0
        for _uid, ws in list(self._conns.get(namespace, [])):
            try:
                await ws.send_json(data)
                sent += 1
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(namespace, ws)
        return sent

    async def broadcast_all(self, data: Any) -> int:
        """Send *data* to every connection across all namespaces."""
        total = 0
        for ns in list(self._conns):
            total += await self.broadcast(ns, data)
        return total

    async def send_to_user(
        self,
        user_id: str,
        data: Any,
        namespace: Optional[str] = None,
    ) -> int:
        """Send *data* to all connections belonging to *user_id*.

        Pass *namespace* to restrict to a single namespace.
        Returns number of messages sent.
        """
        namespaces = [namespace] if namespace else list(self._conns.keys())
        sent = 0
        for ns in namespaces:
            for uid, ws in list(self._conns.get(ns, [])):
                if uid == user_id:
                    try:
                        await ws.send_json(data)
                        sent += 1
                    except Exception:
                        self.disconnect(ns, ws)
        return sent

    # ── Introspection ─────────────────────────────────────────────────────

    def connection_count(self, namespace: Optional[str] = None) -> int:
        if namespace:
            return len(self._conns.get(namespace, []))
        return sum(len(v) for v in self._conns.values())

    def connected_users(self, namespace: Optional[str] = None) -> list[str]:
        """Return unique user IDs with active connections."""
        namespaces = [namespace] if namespace else list(self._conns.keys())
        return list({uid for ns in namespaces for uid, _ in self._conns.get(ns, [])})

    def namespaces(self) -> list[str]:
        return [ns for ns, conns in self._conns.items() if conns]


# ── vera_deps — the FastAPI dependency injection sentinel ─────────────────────

def _build_deps_dependency() -> Any:
    """
    Build a FastAPI ``Depends()`` that extracts the Bearer token from
    ``Authorization``, validates it via AuthManager, and returns a fully
    wired ``VeraDeps`` instance.

    The result is assigned to ``vera_deps`` below and re-exported so plugins
    can write::

        from core.api import vera_deps
        from core.deps import VeraDeps

        @router.get("/me")
        async def me(deps: VeraDeps = vera_deps) -> dict:
            return {"user": deps.user_id, "role": deps.user_role}
    """

    async def _get_deps(
        authorization: Optional[str] = Header(None, alias="Authorization"),
    ) -> "VeraDeps":  # noqa: F821 — VeraDeps imported at call-time to avoid circular
        from core.kernel import VeraKernel
        from core.auth.base import SessionExpired, SessionNotFound

        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=_status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header.  Use: Bearer <session_token>",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = authorization.removeprefix("Bearer ").strip()
        kernel = VeraKernel.get_instance()
        auth_manager = kernel.get_auth_manager()

        if auth_manager is None:
            raise HTTPException(
                status_code=_status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Auth manager not initialised.",
            )

        try:
            session = await auth_manager.verify_session(token)
        except SessionNotFound:
            raise HTTPException(
                status_code=_status.HTTP_401_UNAUTHORIZED,
                detail="Session not found or already expired.",
            )
        except SessionExpired:
            raise HTTPException(
                status_code=_status.HTTP_401_UNAUTHORIZED,
                detail="Session expired.  Please log in again.",
            )

        factory = getattr(kernel, "_deps_factory", None)
        if factory is None:
            raise HTTPException(
                status_code=_status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Deps factory not ready.",
            )

        return factory.create(
            user_id=session.user_id,
            user_role=session.user_role,
            session_id=session.session_token,
        )

    return Depends(_get_deps)


#: Pre-built FastAPI dependency.  Use as the default value for ``deps`` params
#: in plugin route handlers.
vera_deps: Any = _build_deps_dependency()
