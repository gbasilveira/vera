"""Tests for BlinkerBus implementation."""
import asyncio
import pytest
from core.bus import BlinkerBus


@pytest.fixture
def bus():
    return BlinkerBus()


@pytest.mark.asyncio
async def test_emit_and_receive(bus):
    received = []
    bus.on("test.event", lambda sender, **kw: received.append(kw))
    await bus.emit("test.event", {"key": "value"})
    assert received == [{"key": "value"}]


@pytest.mark.asyncio
async def test_multiple_subscribers(bus):
    results = []
    bus.on("multi.event", lambda s, **kw: results.append("handler1"))
    bus.on("multi.event", lambda s, **kw: results.append("handler2"))
    await bus.emit("multi.event", {})
    assert len(results) == 2


@pytest.mark.asyncio
async def test_emit_unknown_signal_is_noop(bus):
    """Emitting with no subscribers should not raise."""
    await bus.emit("unknown.signal", {"data": "x"})


@pytest.mark.asyncio
async def test_signal_isolation(bus):
    received_a, received_b = [], []
    bus.on("signal.a", lambda s, **kw: received_a.append(kw))
    bus.on("signal.b", lambda s, **kw: received_b.append(kw))
    await bus.emit("signal.a", {"x": 1})
    assert received_a == [{"x": 1}]
    assert received_b == []


@pytest.mark.asyncio
async def test_payload_forwarded_as_kwargs(bus):
    received = {}
    bus.on("kw.event", lambda sender, **kw: received.update(kw))
    await bus.emit("kw.event", {"tool_name": "gmail.check_inbox", "duration_ms": 42})
    assert received["tool_name"] == "gmail.check_inbox"
    assert received["duration_ms"] == 42


@pytest.mark.asyncio
async def test_create_bus_factory_default():
    import os
    os.environ.pop("VERA_BUS_BACKEND", None)
    from core.bus import create_bus
    bus = create_bus()
    assert isinstance(bus, BlinkerBus)


@pytest.mark.asyncio
async def test_create_bus_unknown_backend_raises():
    import os
    os.environ["VERA_BUS_BACKEND"] = "unknown"
    from core.bus import create_bus
    with pytest.raises(ValueError):
        create_bus()
    os.environ.pop("VERA_BUS_BACKEND", None)
