---
title: "Observability — OTel & Prometheus"
description: "OpenTelemetry tracing and Prometheus metrics wired to the event bus."
tags: [observability, opentelemetry, prometheus, metrics, tracing]
---

# Observability — OTel & Prometheus

**File:** `core/observability.py`

## OpenTelemetry

A tracer is created during `setup_kernel()` and injected into every `VeraDeps`
instance.  Plugins receive it and can create spans:

```python
with deps.tracer.start_as_current_span("my_plugin.do_work") as span:
    span.set_attribute("tool", tool_name)
    result = await do_work()
```

Configure the OTLP exporter via standard OTel env vars:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
OTEL_SERVICE_NAME=vera
```

## Prometheus metrics

Metrics are wired to the bus via `wire_metrics_to_bus(bus)`.  Each metric
listens to a bus signal and increments automatically.

| Metric | Type | Signal |
|---|---|---|
| `vera_tool_calls_total` | Counter | `tool.call_started` |
| `vera_tool_duration_ms` | Histogram | `tool.call_succeeded` |
| `vera_llm_tokens_total` | Counter | `tool.call_succeeded` (TokenUsage) |
| `vera_llm_cost_usd_total` | Counter | `tool.call_succeeded` (TokenUsage) |

Expose metrics by running a Prometheus HTTP server (not started by default):

```python
from prometheus_client import start_http_server
start_http_server(9090)
```
