"""
VeraBus — Abstract event bus interface.

All bus adapters implement this ABC.
Signal names follow the pattern: domain.event_name
  e.g. kernel.plugin_loaded, tool.call_failed, agent.task_completed

IMPORTANT: BlinkerBus handlers are SYNCHRONOUS. If you connect an async
handler, wrap it: bus.on('signal', lambda s, **kw: asyncio.ensure_future(coro(**kw)))
"""
from abc import ABC, abstractmethod
from typing import Callable
import asyncio
import os
from typing import Callable

import blinker

class VeraBus(ABC):
    """Pub/Sub event bus. Pluggable backend."""

    @abstractmethod
    async def emit(self, signal: str, payload: dict) -> None:
        """Emit a named signal with a dict payload."""
        ...

    @abstractmethod
    def on(self, signal: str, handler: Callable) -> None:
        """Subscribe handler to a named signal."""
        ...


class _StubBus(VeraBus):
    async def emit(self, signal, payload): raise NotImplementedError
    def on(self, signal, handler): raise NotImplementedError


def create_bus() -> VeraBus:
    """Factory: selects bus backend from VERA_BUS_BACKEND env var."""
    backend = os.getenv("VERA_BUS_BACKEND", "blinker")
    if backend == "blinker":
        return BlinkerBus()
    elif backend == "redis":
        raise NotImplementedError("RedisBus not yet implemented — set VERA_BUS_BACKEND=blinker")
    elif backend == "nats":
        raise NotImplementedError("NATSBus not yet implemented — set VERA_BUS_BACKEND=blinker")
    else:
        raise ValueError(f"Unknown bus backend: {backend}")

class BlinkerBus(VeraBus):
    """
    In-memory Pub/Sub using Blinker. Default for single-server deployments.

    IMPORTANT: Blinker dispatches synchronously. All handlers connected via .on()
    must be synchronous functions. For async handlers, use:
        bus.on('signal', lambda sender, **kw: asyncio.ensure_future(my_async_fn(**kw)))
    """

    def __init__(self):
        self._signals: dict[str, blinker.Signal] = {}

    def _get_or_create(self, signal: str) -> blinker.Signal:
        if signal not in self._signals:
            self._signals[signal] = blinker.Signal(signal)
        return self._signals[signal]

    async def emit(self, signal: str, payload: dict) -> None:
        """Emit signal. Blinker dispatch is synchronous — this returns immediately."""
        sig = self._get_or_create(signal)
        sig.send(self, **payload)

    def on(self, signal: str, handler: Callable) -> None:
        """Subscribe a synchronous handler to a signal."""
        self._get_or_create(signal).connect(handler, weak=False)

