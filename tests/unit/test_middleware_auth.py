"""Tests for AuthGuardMiddleware — multi-role permission model."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from core.middleware.auth import AuthGuardMiddleware
from core.middleware.base import PermissionDenied, ToolCallContext


def make_ctx(
    user_roles,
    tool_name: str,
    enforcer=None,
    user_id: str = "test_user",
) -> ToolCallContext:
    """
    Build a ToolCallContext for testing.
    user_roles can be a list or a single string (converted to [str]).
    """
    if isinstance(user_roles, str):
        user_roles = [user_roles]
    if enforcer is None:
        import casbin
        enforcer = casbin.Enforcer("data/casbin/rbac_model.conf", "data/casbin/policy.csv")
    bus = MagicMock()
    bus.emit = AsyncMock()
    return ToolCallContext(
        call_id="c1", tool_name=tool_name, plugin_name="p", agent_id="a",
        user_role=user_roles[0] if user_roles else "guest",
        user_roles=user_roles,
        user_id=user_id,
        tenant_id="default",
        payload={}, is_external=True, vfs=MagicMock(),
        secrets=MagicMock(), enforcer=enforcer, bus=bus,
    )


@pytest.mark.asyncio
async def test_owner_allowed():
    mw = AuthGuardMiddleware()
    ctx = make_ctx(["owner"], "gmail.check_inbox")
    result = await mw.before_call(ctx)
    assert result is ctx


@pytest.mark.asyncio
async def test_guest_denied():
    mw = AuthGuardMiddleware()
    ctx = make_ctx(["guest"], "gmail.check_inbox")
    with pytest.raises(PermissionDenied):
        await mw.before_call(ctx)


@pytest.mark.asyncio
async def test_manager_allowed_gmail():
    mw = AuthGuardMiddleware()
    ctx = make_ctx(["manager"], "gmail.check_inbox")
    result = await mw.before_call(ctx)
    assert result is ctx


@pytest.mark.asyncio
async def test_intern_allowed_memory():
    mw = AuthGuardMiddleware()
    ctx = make_ctx(["intern"], "memory.retrieve_context")
    result = await mw.before_call(ctx)
    assert result is ctx


@pytest.mark.asyncio
async def test_intern_denied_gmail():
    mw = AuthGuardMiddleware()
    ctx = make_ctx(["intern"], "gmail.check_inbox")
    with pytest.raises(PermissionDenied):
        await mw.before_call(ctx)


@pytest.mark.asyncio
async def test_multi_role_grants_access():
    """User with [intern, agent_editor] can run agent tools (from agent_editor)."""
    mw = AuthGuardMiddleware()
    ctx = make_ctx(["intern", "agent_editor"], "agent.run_task")
    result = await mw.before_call(ctx)
    assert result is ctx


@pytest.mark.asyncio
async def test_multi_role_still_denied_without_permission():
    """User with [intern, agent_editor] cannot send gmail (neither role has perm:gmail:all)."""
    mw = AuthGuardMiddleware()
    ctx = make_ctx(["intern", "agent_editor"], "gmail.send")
    with pytest.raises(PermissionDenied):
        await mw.before_call(ctx)


@pytest.mark.asyncio
async def test_empty_roles_denied():
    mw = AuthGuardMiddleware()
    ctx = make_ctx([], "gmail.check_inbox")
    with pytest.raises(PermissionDenied):
        await mw.before_call(ctx)


@pytest.mark.asyncio
async def test_denied_emits_signal():
    mw = AuthGuardMiddleware()
    ctx = make_ctx(["guest"], "gmail.check_inbox")
    try:
        await mw.before_call(ctx)
    except PermissionDenied:
        pass
    ctx.bus.emit.assert_awaited_once()
    call_args = ctx.bus.emit.call_args
    assert call_args[0][0] == "security.permission_denied"
    payload = call_args[0][1]
    assert "user_roles" in payload


@pytest.mark.asyncio
async def test_after_call_passes_through():
    mw = AuthGuardMiddleware()
    ctx = make_ctx(["owner"], "gmail.check_inbox")
    result = await mw.after_call(ctx, {"emails": []})
    assert result == {"emails": []}
