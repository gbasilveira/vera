"""
VeraDeps — PydanticAI dependency injection object.

This is the SINGLE interface between an agent/tool and all kernel services.
Tools receive ctx: RunContext[VeraDeps] and access everything via ctx.deps.

Rules enforced by vera lint:
  - NO direct imports from core/ in plugin tool files
  - NO os.environ access in plugin tool files
  - ALL secrets via ctx.deps.secrets.get()
  - ALL LLM calls via ctx.deps.run_tool('llm.*')

This stub is fully typed.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

import os
import casbin
from opentelemetry import trace as otel_trace

if TYPE_CHECKING:
    import casbin
    from opentelemetry import trace

    from core.bus import VeraBus
    from core.kernel import VeraKernel
    from core.secrets import SecretsManager
    from core.vfs.base import VeraFileSystem


class VeraDeps(BaseModel):
    """
    Injected into every tool call via RunContext[VeraDeps].
    Never instantiate directly in plugin code — the kernel creates this.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    # ── Identity ───────────────────────────────────────────────────────────
    user_id:    str
    user_roles: list[str]       # all roles — authoritative for enforcement
    session_id: str
    tenant_id:  str = "default"

    # ── Kernel services (injected by VeraDepsFactory) ──────────────────────
    kernel:   "VeraKernel"
    bus:      "VeraBus"
    vfs:      "VeraFileSystem"
    secrets:  "SecretsManager"
    enforcer: "casbin.Enforcer"
    tracer:   Any              # opentelemetry.trace.Tracer

    # ── LLM configuration ──────────────────────────────────────────────────
    llm_provider:    str   = "ollama"    # 'openai' | 'anthropic' | 'ollama'
    llm_model:       str   = "llama3"
    llm_temperature: float = 0.1

    # ── Memory configuration ───────────────────────────────────────────────
    memory_namespace: str = "default"

    # ── API / WebSocket services ────────────────────────────────────────────
    ws_manager: Any = None   # WebSocketManager — None in CLI context

    # ── Identity helpers ───────────────────────────────────────────────────

    @property
    def user_role(self) -> str:
        """Primary (first) role, or 'guest'. For display / logging only."""
        return self.user_roles[0] if self.user_roles else "guest"

    # ── Permission helpers ─────────────────────────────────────────────────

    def can(self, tool_name: str, action: str = "execute") -> bool:
        """
        Return True if the user can perform action on tool_name.
        Checks all roles — access granted if any role allows it.
        """
        return any(
            self.enforcer.enforce(role, tool_name, action)
            for role in self.user_roles
        )

    def can_all(self, *tool_names: str, action: str = "execute") -> bool:
        """Return True only if the user can perform action on ALL given tools."""
        return all(self.can(t, action) for t in tool_names)

    def can_any(self, *tool_names: str, action: str = "execute") -> bool:
        """Return True if the user can perform action on AT LEAST ONE of the given tools."""
        return any(self.can(t, action) for t in tool_names)

    # ── Tool execution ─────────────────────────────────────────────────────

    async def run_tool(self, tool_name: str, **kwargs: Any) -> Any:
        """
        Execute a kernel-registered tool through the full middleware stack.
        This is the ONLY way plugins should call other tools.
        """
        return await self.kernel.execute(tool_name, self, **kwargs)


class VeraDepsFactory:
    """
    Constructs VeraDeps instances for use in FastAPI request handlers (Phase 5)
    and test fixtures.

    Usage:
        factory = VeraDepsFactory(kernel=kernel, bus=bus, vfs=vfs, secrets=secrets, security=security)
        deps = factory.create(user_id='u1', user_roles=['owner'], session_id='s1')

        # Legacy single-role call also accepted:
        deps = factory.create(user_id='u1', user_role='owner', session_id='s1')
    """

    def __init__(self, kernel, bus, vfs, secrets, security, ws_manager=None):
        self._kernel = kernel
        self._bus = bus
        self._vfs = vfs
        self._secrets = secrets
        self._security = security
        self._tracer = otel_trace.get_tracer("vera")
        self._ws_manager = ws_manager

    def create(
        self,
        user_id: str,
        user_roles: list[str] | None = None,
        session_id: str | None = None,
        tenant_id: str = "default",
        llm_provider: str | None = None,
        llm_model: str | None = None,
        # Legacy parameter — converted to user_roles=[user_role]
        user_role: str | None = None,
    ) -> "VeraDeps":
        import uuid as _uuid
        # Normalize: accept either user_roles list or legacy user_role string
        if user_roles is None:
            user_roles = [user_role] if user_role else []
        return VeraDeps(
            user_id=user_id,
            user_roles=user_roles,
            session_id=session_id or str(_uuid.uuid4()),
            tenant_id=tenant_id,
            kernel=self._kernel,
            bus=self._bus,
            vfs=self._vfs,
            secrets=self._secrets,
            enforcer=self._security.enforcer,
            tracer=self._tracer,
            llm_provider=llm_provider or os.getenv("VERA_LLM_PROVIDER", "ollama"),
            llm_model=llm_model or os.getenv("VERA_LLM_MODEL", "llama3"),
            ws_manager=self._ws_manager,
        )

from core.bus import VeraBus
from core.kernel import VeraKernel
from core.secrets import SecretsManager
from core.vfs.base import VeraFileSystem

VeraDeps.model_rebuild()
