"""
CostRecorderMiddleware — record LLM token usage and cost (order=70).

After each tool execution, checks if the result contains a TokenUsage object.
If so, writes usage to VFS under key: cost:{agent_id}:{date}:{tool_name}
VFS data is read by the dashboard Cost & ROI page.

Non-fatal: write failures are logged to stderr, execution continues.
"""
import json
import sys
import time
from datetime import date
from typing import Any

from core.middleware.base import ORDER_COST, ToolCallContext, VeraMiddleware


class CostRecorderMiddleware(VeraMiddleware):
    name = "cost_recorder"
    order = ORDER_COST

    async def before_call(self, ctx: ToolCallContext) -> ToolCallContext:
        return ctx

    async def after_call(self, ctx: ToolCallContext, result: Any) -> Any:
        usage = self._extract_token_usage(result)
        if usage:
            await self._record(ctx, usage)
        return result

    def _extract_token_usage(self, result: Any):
        """
        Extract TokenUsage from a result.
        Handles: TokenUsage directly, tuple[BaseModel, TokenUsage], dict with usage key.
        """
        from plugins.llm_driver.adapters.base import TokenUsage

        if isinstance(result, TokenUsage):
            return result
        if isinstance(result, tuple) and len(result) == 2:
            _, second = result
            if isinstance(second, TokenUsage):
                return second
        if isinstance(result, dict) and "usage" in result:
            u = result["usage"]
            if isinstance(u, dict):
                try:
                    return TokenUsage(**u)
                except Exception:
                    pass
            if isinstance(u, TokenUsage):
                return u
        return None

    async def _record(self, ctx: ToolCallContext, usage) -> None:
        try:
            today = date.today().isoformat()
            vfs_key = f"cost:{ctx.agent_id}:{today}:{ctx.tool_name}"

            # Read existing aggregation
            existing_raw = await ctx.vfs.get(vfs_key)
            existing = json.loads(existing_raw.decode()) if existing_raw else {
                "agent_id": ctx.agent_id,
                "tool_name": ctx.tool_name,
                "date": today,
                "calls": 0,
                "total_tokens": 0,
                "total_cost_usd": 0.0,
            }

            existing["calls"] += 1
            existing["total_tokens"] += usage.total_tokens
            existing["total_cost_usd"] += usage.cost_usd

            await ctx.vfs.set(vfs_key, json.dumps(existing).encode())
        except Exception as e:
            print(f"[VERA] Warning: cost recording failed: {e}", file=sys.stderr)