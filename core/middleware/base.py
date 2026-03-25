"""
VeraMiddleware — Abstract middleware interface + shared types.

The middleware chain runs on EVERY kernel tool call, in a fixed order:
  10  AuthGuard         — Casbin permission check
  20  SecretsInjector   — inject API keys into context
  30  PIIMasker         — mask outbound PII, restore inbound
  40  RetryWrapper      — exponential backoff on transient errors
  50  (Execution)       — the actual tool function runs here
  60  (PII Swap)        — handled by PIIMasker.after_call
  70  CostRecorder      — record token usage to VFS
  80  AuditLogger       — write success/failure to audit

Order constants are defined here so every middleware file imports from one place.
"""
import dataclasses
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.vfs.base import VeraFileSystem
    from core.secrets import SecretsManager
    import casbin

# ── Order constants ────────────────────────────────────────────────────────
ORDER_AUTH    = 10
ORDER_SECRETS = 20
ORDER_PII     = 30
ORDER_RETRY   = 40
# Execution happens between RETRY and COST (order 50, not a middleware)
ORDER_COST    = 70
ORDER_AUDIT   = 80


# ── Shared exceptions ──────────────────────────────────────────────────────
class PermissionDenied(Exception):
    """Raised by AuthGuardMiddleware when Casbin denies a tool call."""


class SecretNotFound(Exception):
    """Raised by SecretsInjectorMiddleware when a required secret is missing."""


class PIIMaskError(Exception):
    """Raised by PIIMaskerMiddleware when masking fails."""


class PIISwapError(Exception):
    """Raised by PIIMaskerMiddleware when unmasking fails."""


class MaxRetriesExceeded(Exception):
    """Raised by RetryMiddleware after all retry attempts are exhausted."""


# ── ToolCallContext ────────────────────────────────────────────────────────
@dataclasses.dataclass(frozen=True)
class ToolCallContext:
    """
    Immutable context object passed through the middleware chain.

    Created once per tool call by VeraKernel.execute().
    Middleware can produce a modified copy via with_payload() or dataclasses.replace().
    Never mutate this object directly (frozen=True enforces this).

    user_roles holds ALL roles the user has at call time.  AuthGuardMiddleware
    checks all roles; access is granted if ANY role allows the action.
    user_role is the primary (first) role, kept for audit logging compatibility.
    """
    call_id:      str
    tool_name:    str
    plugin_name:  str
    agent_id:     str
    user_role:    str          # primary role — for logging/audit only
    user_id:      str
    tenant_id:    str
    payload:      dict          # kwargs passed to the tool function
    is_external:  bool          # True = triggers PII masking
    vfs:          "VeraFileSystem"
    secrets:      "SecretsManager"
    enforcer:     "casbin.Enforcer"
    bus:          Any           # VeraBus (Any to avoid circular import)
    # Optional fields with defaults ──────────────────────────────────────────
    # user_roles holds ALL roles for enforcement; defaults to [user_role] when
    # not provided so old code that only sets user_role still works.
    user_roles:   list = dataclasses.field(default_factory=list)
    injected_secrets: dict = dataclasses.field(default_factory=dict)

    def with_payload(self, new_payload: dict) -> "ToolCallContext":
        """Return a copy of this context with an updated payload."""
        return dataclasses.replace(self, payload=new_payload)

    def with_injected_secrets(self, secrets: dict) -> "ToolCallContext":
        """Return a copy of this context with injected secrets added."""
        return dataclasses.replace(self, injected_secrets={**self.injected_secrets, **secrets})


# ── VeraMiddleware ABC ─────────────────────────────────────────────────────
class VeraMiddleware(ABC):
    """
    Base class for all VERA middleware.

    Subclasses must set class-level `name` and `order` attributes.
    Lower order = runs first in the before_call chain.
    """
    name: str   # e.g. 'auth_guard', 'pii_masker'
    order: int  # See ORDER_* constants above

    @abstractmethod
    async def before_call(self, ctx: ToolCallContext) -> ToolCallContext:
        """
        Called before tool execution. May modify and return a new ctx.
        Raise an exception to abort the call (no after_call will run).
        """
        ...

    @abstractmethod
    async def after_call(self, ctx: ToolCallContext, result: Any) -> Any:
        """
        Called after successful tool execution. May transform the result.
        Return the (possibly modified) result.
        """
        ...

    async def on_error(self, ctx: ToolCallContext, error: Exception) -> None:
        """
        Called when any exception occurs during execution or middleware.
        Default is a no-op. Override to add error-specific behaviour.
        """
        pass
