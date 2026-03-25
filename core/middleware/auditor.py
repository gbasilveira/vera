"""
AuditLoggerMiddleware — write every tool call to audit.jsonl (order=80).

Writes one JSON object per line to data/logs/audit.jsonl.
Fields: timestamp, call_id, tool_name, plugin_name, user_id, user_role,
        tenant_id, status (success|failure), duration_ms, error (on failure).

Non-fatal: if the file write fails, logs to stderr and continues.
Does NOT include payload or result data (PII safety).
"""
import json
import sys
import time
from pathlib import Path
from typing import Any

from core.middleware.base import ORDER_AUDIT, ToolCallContext, VeraMiddleware


class AuditLoggerMiddleware(VeraMiddleware):
    name = "audit_logger"
    order = ORDER_AUDIT

    def __init__(self, log_path: str = "data/logs/audit.jsonl"):
        self._log_path = Path(log_path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._start_times: dict[str, float] = {}

    async def before_call(self, ctx: ToolCallContext) -> ToolCallContext:
        self._start_times[ctx.call_id] = time.monotonic()
        return ctx

    async def after_call(self, ctx: ToolCallContext, result: Any) -> Any:
        duration_ms = self._elapsed_ms(ctx.call_id)
        self._write({
            "timestamp": time.time(),
            "call_id": ctx.call_id,
            "tool_name": ctx.tool_name,
            "plugin_name": ctx.plugin_name,
            "user_id": ctx.user_id,
            "user_role": ctx.user_role,
            "tenant_id": ctx.tenant_id,
            "status": "success",
            "duration_ms": duration_ms,
        })
        return result

    async def on_error(self, ctx: ToolCallContext, error: Exception) -> None:
        duration_ms = self._elapsed_ms(ctx.call_id)
        self._write({
            "timestamp": time.time(),
            "call_id": ctx.call_id,
            "tool_name": ctx.tool_name,
            "plugin_name": ctx.plugin_name,
            "user_id": ctx.user_id,
            "user_role": ctx.user_role,
            "tenant_id": ctx.tenant_id,
            "status": "failure",
            "duration_ms": duration_ms,
            "error": str(error),
            "error_type": type(error).__name__,
        })

    def _elapsed_ms(self, call_id: str) -> int:
        start = self._start_times.pop(call_id, None)
        if start is None:
            return 0
        return int((time.monotonic() - start) * 1000)

    def _write(self, record: dict) -> None:
        try:
            with open(self._log_path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            print(f"[VERA] Warning: audit log write failed: {e}", file=sys.stderr)