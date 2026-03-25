"""
RetryMiddleware — exponential backoff for transient errors (order=40).

Reads retry config from the plugin manifest:
  retry.max_attempts (default: 3)
  retry.backoff_factor (default: 2)
  retry.retryable_errors (default: [NetworkError, TimeoutError])

Emits tool.retry_attempt signal on each retry.
Raises MaxRetriesExceeded after all attempts are exhausted.

Note: RetryMiddleware wraps execution differently from other middleware.
It does not use before_call/after_call directly — instead the kernel's
execute() logic calls the tool inside a retry loop in Phase 3.
For Phase 3A, we implement the retry logic as a standalone function
that the kernel will call.
"""
import asyncio
import time
from typing import Any, Callable

from core.middleware.base import ORDER_RETRY, MaxRetriesExceeded, ToolCallContext, VeraMiddleware


# Default retryable exception types (by name, since we can't import them all)
DEFAULT_RETRYABLE_ERRORS = {"NetworkError", "TimeoutError", "ConnectionError", "ServiceUnavailableError",
                             "RateLimitError", "OSError"}


class RetryMiddleware(VeraMiddleware):
    """
    Retry wrapper. Configured per-plugin via manifest.yaml retry: section.

    In Phase 3B, the kernel reads the retry config from the manifest and
    wraps tool execution in retry_with_backoff().
    """
    name = "retry"
    order = ORDER_RETRY

    def __init__(self, kernel):
        self._kernel = kernel

    async def before_call(self, ctx: ToolCallContext) -> ToolCallContext:
        return ctx  # Retry logic is in Phase 3B kernel execute()

    async def after_call(self, ctx: ToolCallContext, result: Any) -> Any:
        return result

    @staticmethod
    def get_retry_config(manifest: dict) -> dict:
        """Extract retry config from manifest with defaults."""
        retry = manifest.get("retry", {})
        return {
            "max_attempts": retry.get("max_attempts", 3),
            "backoff_factor": retry.get("backoff_factor", 2),
            "retryable_errors": set(retry.get("retryable_errors", list(DEFAULT_RETRYABLE_ERRORS))),
        }

    @staticmethod
    def is_retryable(error: Exception, retryable_names: set) -> bool:
        """Check if an error type is in the retryable set."""
        error_type = type(error).__name__
        return error_type in retryable_names


async def retry_with_backoff(
    fn: Callable,
    ctx: ToolCallContext,
    deps: Any,
    max_attempts: int,
    backoff_factor: float,
    retryable_errors: set,
) -> Any:
    """
    Execute fn with exponential backoff retry.
    Used by VeraKernel.execute() in Phase 3B.
    """
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn(deps, **ctx.payload)
        except Exception as e:
            last_error = e
            if not RetryMiddleware.is_retryable(e, retryable_errors):
                raise  # Non-retryable: propagate immediately

            if attempt < max_attempts:
                delay = backoff_factor ** (attempt - 1)
                await ctx.bus.emit("tool.retry_attempt", {
                    "call_id": ctx.call_id,
                    "tool_name": ctx.tool_name,
                    "attempt_n": attempt,
                    "next_delay_s": delay,
                    "error": str(e),
                })
                await asyncio.sleep(delay)

    raise MaxRetriesExceeded(
        f"Tool '{ctx.tool_name}' failed after {max_attempts} attempts. "
        f"Last error: {last_error}"
    ) from last_error