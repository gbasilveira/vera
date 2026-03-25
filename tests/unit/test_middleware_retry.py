"""Tests for RetryMiddleware and retry_with_backoff."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.middleware.retry import RetryMiddleware, retry_with_backoff
from core.middleware.base import MaxRetriesExceeded, ToolCallContext


def make_ctx(tool_name="test.tool"):
    bus = MagicMock()
    bus.emit = AsyncMock()
    return ToolCallContext(
        call_id="c1", tool_name=tool_name, plugin_name="p", agent_id="a",
        user_role="owner", user_id="u", tenant_id="default",
        payload={"value": "x"}, is_external=False, vfs=MagicMock(),
        secrets=MagicMock(), enforcer=MagicMock(), bus=bus,
    )


@pytest.mark.asyncio
async def test_success_on_first_attempt():
    ctx = make_ctx()
    async def fn(deps, **kw): return "ok"
    result = await retry_with_backoff(fn, ctx, MagicMock(), 3, 2, {"NetworkError"})
    assert result == "ok"


@pytest.mark.asyncio
async def test_retry_on_retryable_error():
    ctx = make_ctx()
    calls = [0]
    async def fn(deps, **kw):
        calls[0] += 1
        if calls[0] < 3:
            raise ConnectionError("temporary")
        return "recovered"

    with patch("asyncio.sleep", new_callable=AsyncMock):
        result = await retry_with_backoff(fn, ctx, MagicMock(), 3, 2, {"ConnectionError"})
    assert result == "recovered"
    assert calls[0] == 3


@pytest.mark.asyncio
async def test_non_retryable_error_raises_immediately():
    ctx = make_ctx()
    async def fn(deps, **kw): raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        await retry_with_backoff(fn, ctx, MagicMock(), 3, 2, {"NetworkError"})


@pytest.mark.asyncio
async def test_max_retries_exceeded():
    ctx = make_ctx()
    async def fn(deps, **kw): raise ConnectionError("always fails")

    with patch("asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(MaxRetriesExceeded):
            await retry_with_backoff(fn, ctx, MagicMock(), 3, 2, {"ConnectionError"})


@pytest.mark.asyncio
async def test_retry_emits_signal():
    ctx = make_ctx()
    async def fn(deps, **kw): raise ConnectionError("fail")

    with patch("asyncio.sleep", new_callable=AsyncMock):
        try:
            await retry_with_backoff(fn, ctx, MagicMock(), 2, 2, {"ConnectionError"})
        except MaxRetriesExceeded:
            pass

    # Should have emitted tool.retry_attempt once (first attempt fails, emits, second fails, exhausted)
    assert ctx.bus.emit.await_count >= 1
    signal_name = ctx.bus.emit.call_args_list[0][0][0]
    assert signal_name == "tool.retry_attempt"


def test_get_retry_config_defaults():
    config = RetryMiddleware.get_retry_config({})
    assert config["max_attempts"] == 3
    assert config["backoff_factor"] == 2


def test_get_retry_config_from_manifest():
    manifest = {"retry": {"max_attempts": 5, "backoff_factor": 3, "retryable_errors": ["MyError"]}}
    config = RetryMiddleware.get_retry_config(manifest)
    assert config["max_attempts"] == 5
    assert "MyError" in config["retryable_errors"]
