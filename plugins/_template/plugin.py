"""
VERA Plugin Template.

Copy this directory to plugins/my_plugin/ and rename accordingly.
See docs/PLUGIN_DEV.md for step-by-step guide.
"""
from core.bus import VeraBus
from core.kernel import VeraPlugin, VeraKernel


class TemplatePlugin(VeraPlugin):
    """Minimal working plugin. Replace all 'template'/'my_plugin' references."""
    name = "my_plugin"
    version = "1.0.0"

    def register_tools(self, kernel: VeraKernel) -> None:
        kernel.register_tool(
            tool_name="my_plugin.do_thing",
            fn=self._do_thing,
            plugin_name=self.name,
            is_external=False,   # True for tools that call external APIs
        )

    def register_listeners(self, bus: VeraBus) -> None:
        bus.on("agent.task_completed", self._on_task_completed)

    async def _do_thing(self, deps, **kwargs):
        """Replace with your tool implementation."""
        from plugins._template.tools import do_thing
        return await do_thing(deps, **kwargs)

    def _on_task_completed(self, sender, **payload):
        pass  # React to signals here