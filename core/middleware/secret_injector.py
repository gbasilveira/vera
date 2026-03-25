"""
SecretsInjectorMiddleware — inject API keys into context (order=20).

Reads secrets_required from the plugin manifest.
Injects values into ctx.injected_secrets (not into payload or logs).
Raises SecretNotFound if any required secret is missing.

Plugins access injected secrets via ctx.injected_secrets['plugin.key']
in their tool implementation — NOT via ctx.deps.secrets (which is for
plugins that want to fetch secrets lazily at call time).
"""
from typing import Any

from core.middleware.base import ORDER_SECRETS, SecretNotFound, ToolCallContext, VeraMiddleware


class SecretsInjectorMiddleware(VeraMiddleware):
    name = "secrets_injector"
    order = ORDER_SECRETS

    def __init__(self, kernel):
        """kernel is VeraKernel — used to look up plugin manifests."""
        self._kernel = kernel

    async def before_call(self, ctx: ToolCallContext) -> ToolCallContext:
        manifest = self._kernel.get_plugin_manifest(ctx.plugin_name)
        required_secrets = manifest.get("secrets_required", [])

        injected = {}
        missing = []
        for key in required_secrets:
            value = await ctx.secrets.get_optional(key)
            if value is None:
                missing.append(key)
            else:
                injected[key] = value

        if missing:
            raise SecretNotFound(
                f"Plugin '{ctx.plugin_name}' requires secrets that are not set: {missing}. "
                f"Run: vera secrets set <key> <value>"
            )

        return ctx.with_injected_secrets(injected)

    async def after_call(self, ctx: ToolCallContext, result: Any) -> Any:
        return result