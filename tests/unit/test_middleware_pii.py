"""Tests for PIIMaskerMiddleware."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from core.middleware.base import ToolCallContext
from core.middleware.pii_masker import PIIMaskerMiddleware, _mask_string, _unmask_string


class TestPIIHelpers:
    def test_mask_string_with_email(self):
        mapping = {}
        result = _mask_string("Contact john.doe@example.com for details", mapping)
        assert "john.doe@example.com" not in result
        assert len(mapping) == 1
        assert "john.doe@example.com" in mapping.values()

    def test_unmask_string(self):
        mapping = {"abc-123": "john@example.com"}
        result = _unmask_string("Contact <<PII:abc-123>> for details", mapping)
        assert result == "Contact john@example.com for details"

    def test_round_trip(self):
        mapping = {}
        original = "Email john@test.com or call +1-555-0123"
        masked = _mask_string(original, mapping)
        assert "john@test.com" not in masked or "+1-555-0123" not in masked
        unmasked = _unmask_string(masked, mapping)
        # All replaced items should be restored
        for original_value in mapping.values():
            assert original_value in unmasked

    def test_no_pii_passthrough(self):
        mapping = {}
        result = _mask_string("Hello, how are you today?", mapping)
        assert result == "Hello, how are you today?"
        assert mapping == {}


def make_external_ctx(payload: dict, vfs=None, bus=None) -> ToolCallContext:
    if vfs is None:
        vfs = MagicMock()
        vfs.get = AsyncMock(return_value=None)
        vfs.set = AsyncMock()
        vfs.delete = AsyncMock()
    if bus is None:
        bus = MagicMock()
        bus.emit = AsyncMock()
    return ToolCallContext(
        call_id="c1", tool_name="gmail.send_email", plugin_name="gmail_driver",
        agent_id="a", user_role="owner", user_id="u", tenant_id="default",
        payload=payload, is_external=True, vfs=vfs,
        secrets=MagicMock(), enforcer=MagicMock(), bus=bus,
    )


def make_internal_ctx(payload: dict) -> ToolCallContext:
    return ToolCallContext(
        call_id="c2", tool_name="memory.store", plugin_name="memory_rag",
        agent_id="a", user_role="owner", user_id="u", tenant_id="default",
        payload=payload, is_external=False, vfs=MagicMock(),
        secrets=MagicMock(), enforcer=MagicMock(), bus=MagicMock(),
    )


@pytest.mark.asyncio
async def test_internal_tool_skips_masking():
    mw = PIIMaskerMiddleware()
    ctx = make_internal_ctx({"content": "Call John at john@example.com"})
    result = await mw.before_call(ctx)
    assert result.payload == ctx.payload  # Unchanged


@pytest.mark.asyncio
async def test_external_tool_masks_email():
    vfs = MagicMock()
    vfs.set = AsyncMock()
    vfs.get = AsyncMock(return_value=None)
    vfs.delete = AsyncMock()
    bus = MagicMock()
    bus.emit = AsyncMock()

    mw = PIIMaskerMiddleware()
    ctx = make_external_ctx({"to": "secret@example.com", "body": "Hello"}, vfs=vfs, bus=bus)
    result = await mw.before_call(ctx)
    assert "secret@example.com" not in result.payload.get("to", "")
    vfs.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_after_call_restores_pii():
    import json
    mapping = {"uuid-1": "restored@example.com"}
    vfs = MagicMock()
    vfs.get = AsyncMock(return_value=json.dumps(mapping).encode())
    vfs.delete = AsyncMock()
    bus = MagicMock()
    bus.emit = AsyncMock()

    mw = PIIMaskerMiddleware()
    ctx = make_external_ctx({}, vfs=vfs, bus=bus)
    result = await mw.after_call(ctx, "Reply to <<PII:uuid-1>> asap")
    assert result == "Reply to restored@example.com asap"
    vfs.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_mapping_stored_when_no_pii():
    vfs = MagicMock()
    vfs.set = AsyncMock()
    bus = MagicMock()
    bus.emit = AsyncMock()

    mw = PIIMaskerMiddleware()
    ctx = make_external_ctx({"body": "No sensitive data here"}, vfs=vfs, bus=bus)
    await mw.before_call(ctx)
    vfs.set.assert_not_awaited()
