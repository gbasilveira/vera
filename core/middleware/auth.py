"""
AuthGuardMiddleware — Casbin permission check (order=10).

Runs first. Raises PermissionDenied if NONE of the user's roles can execute
the tool.  Access is granted when at least one role allows it and no role
explicitly denies it (deny-wins semantics from the Casbin policy effect).
Emits security.permission_denied signal on failure (for audit/notifications).
"""
from typing import Any

from core.middleware.base import ORDER_AUTH, PermissionDenied, ToolCallContext, VeraMiddleware


class AuthGuardMiddleware(VeraMiddleware):
    name = "auth_guard"
    order = ORDER_AUTH

    async def before_call(self, ctx: ToolCallContext) -> ToolCallContext:
        roles = ctx.user_roles if ctx.user_roles else ([ctx.user_role] if ctx.user_role else [])
        allowed = any(
            ctx.enforcer.enforce(role, ctx.tool_name, "execute")
            for role in roles
        )
        if not allowed:
            await ctx.bus.emit("security.permission_denied", {
                "user_roles": roles,
                "user_role":  ctx.user_role,
                "tool_name":  ctx.tool_name,
                "user_id":    ctx.user_id,
            })
            raise PermissionDenied(
                f"User '{ctx.user_id}' with roles {roles} is not permitted "
                f"to execute '{ctx.tool_name}'"
            )
        return ctx

    async def after_call(self, ctx: ToolCallContext, result: Any) -> Any:
        return result  # Auth has nothing to do after execution

    async def on_error(self, ctx: ToolCallContext, error: Exception) -> None:
        pass  # PermissionDenied is already signalled in before_call
