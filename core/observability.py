"""
VERA Observability — OpenTelemetry tracing + Prometheus metrics.

Call setup_observability() once during kernel initialisation.
The returned tracer is injected into VeraDeps.

Prometheus metrics are auto-incremented by listening to bus signals.
Expose /metrics endpoint via FastAPI in Phase 5.
"""
import os
from typing import Optional

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from prometheus_client import Counter, Histogram

# ── Prometheus metrics ─────────────────────────────────────────────────────
TOOL_CALLS_TOTAL = Counter(
    "vera_tool_calls_total",
    "Total tool calls",
    ["tool_name", "plugin_name", "status"],
)
TOOL_DURATION_MS = Histogram(
    "vera_tool_duration_ms",
    "Tool call duration in milliseconds",
    ["tool_name"],
    buckets=[10, 50, 100, 250, 500, 1000, 2500, 5000],
)
LLM_TOKENS_TOTAL = Counter(
    "vera_llm_tokens_total",
    "Total LLM tokens consumed",
    ["provider", "model"],
)
LLM_COST_USD_TOTAL = Counter(
    "vera_llm_cost_usd_total",
    "Total LLM cost in USD",
    ["provider", "model"],
)


def setup_observability() -> trace.Tracer:
    """
    Initialise OpenTelemetry. Call once during kernel startup.
    Returns a tracer to inject into VeraDeps.
    """
    provider = TracerProvider()

    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint))
    else:
        # Console exporter for development (no external service required)
        processor = BatchSpanProcessor(ConsoleSpanExporter())

    provider.add_span_processor(processor)
    trace.set_tracer_provider(provider)
    return trace.get_tracer("vera")


def wire_metrics_to_bus(bus) -> None:
    """
    Connect Prometheus metric updates to bus signals.
    Call after bus is initialised and before plugins are loaded.
    """
    def on_tool_succeeded(sender, **payload):
        TOOL_CALLS_TOTAL.labels(
            tool_name=payload.get("tool_name", "unknown"),
            plugin_name=payload.get("plugin_name", "unknown"),
            status="success",
        ).inc()
        if "duration_ms" in payload:
            TOOL_DURATION_MS.labels(tool_name=payload.get("tool_name", "unknown")).observe(
                payload["duration_ms"]
            )

    def on_tool_failed(sender, **payload):
        TOOL_CALLS_TOTAL.labels(
            tool_name=payload.get("tool_name", "unknown"),
            plugin_name=payload.get("plugin_name", "unknown"),
            status="failure",
        ).inc()

    def on_llm_completed(sender, **payload):
        LLM_TOKENS_TOTAL.labels(
            provider=payload.get("provider", "unknown"),
            model=payload.get("model", "unknown"),
        ).inc(payload.get("total_tokens", 0))
        LLM_COST_USD_TOTAL.labels(
            provider=payload.get("provider", "unknown"),
            model=payload.get("model", "unknown"),
        ).inc(payload.get("cost_usd", 0.0))

    bus.on("tool.call_succeeded", on_tool_succeeded)
    bus.on("tool.call_failed", on_tool_failed)
    bus.on("llm.call_completed", on_llm_completed)