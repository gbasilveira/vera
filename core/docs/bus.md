---
title: "VeraBus — Event Bus"
description: "Async event bus for decoupled communication between kernel, plugins, and middleware."
tags: [bus, events, signals, blinker]
---

# VeraBus — Event Bus

**File:** `core/bus.py`
**Default implementation:** `BlinkerBus` (in-process, Blinker signals)

## API

```python
await bus.emit("tool.call_failed", {"tool": "llm.generate", "error": "..."})
bus.on("tool.call_failed", my_handler)
```

## Signal naming convention

`<domain>.<event_name>` — e.g.:

| Signal | Emitted by |
|---|---|
| `tool.call_started` | VeraKernel |
| `tool.call_succeeded` | VeraKernel |
| `tool.call_failed` | VeraKernel |
| `tool.retry_attempt` | RetryMiddleware |
| `kernel.plugin_loaded` | VeraKernel |
| `kernel.plugin_unloaded` | VeraKernel |
| `security.permission_denied` | AuthGuardMiddleware |

## Important: BlinkerBus handlers are synchronous

Blinker dispatches synchronously.  If your handler is `async`, wrap it:

```python
import asyncio

def on_event(payload):
    asyncio.ensure_future(my_async_handler(payload))

bus.on("tool.call_failed", on_event)
```

## Registering listeners in a plugin

```python
class MyPlugin(VeraPlugin):
    def register_listeners(self, bus: VeraBus) -> None:
        bus.on("tool.call_failed", self._on_failure)
```

## Planned backends

- `RedisBus` — cross-process pub/sub via Redis Streams
- `NATSBus` — high-throughput distributed messaging
