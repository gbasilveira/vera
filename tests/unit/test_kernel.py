"""Tests for VeraKernel."""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock

from core.kernel import VeraKernel, VeraPlugin
from core.bus import BlinkerBus
from core.vfs.local_fs import LocalFS


@pytest.fixture(autouse=True)
def reset_kernel():
    """Reset the singleton before and after each test."""
    VeraKernel.reset()
    yield
    VeraKernel.reset()


@pytest_asyncio.fixture
async def kernel(tmp_path):
    k = VeraKernel.get_instance()
    vfs = LocalFS(db_path=str(tmp_path / "vfs.db"))
    bus = BlinkerBus()
    await k.initialise(bus=bus, vfs=vfs)
    return k


class TestSingleton:
    def test_same_instance(self):
        k1 = VeraKernel.get_instance()
        k2 = VeraKernel.get_instance()
        assert k1 is k2

    def test_reset_creates_new_instance(self):
        k1 = VeraKernel.get_instance()
        VeraKernel.reset()
        k2 = VeraKernel.get_instance()
        assert k1 is not k2


class TestToolRegistry:
    @pytest.mark.asyncio
    async def test_register_and_list_tool(self, kernel):
        async def my_tool(deps, **kw): return "result"
        kernel.register_tool("test.my_tool", my_tool, "test_plugin", is_external=False)
        assert "test.my_tool" in kernel.list_tools()

    @pytest.mark.asyncio
    async def test_duplicate_tool_raises(self, kernel):
        async def fn(deps, **kw): pass
        kernel.register_tool("dup.tool", fn, "plugin_a", is_external=False)
        with pytest.raises(ValueError, match="already registered"):
            kernel.register_tool("dup.tool", fn, "plugin_b", is_external=False)

    @pytest.mark.asyncio
    async def test_has_tool(self, kernel):
        async def fn(deps, **kw): pass
        kernel.register_tool("exists.tool", fn, "p", is_external=False)
        assert kernel.has_tool("exists.tool") is True
        assert kernel.has_tool("missing.tool") is False


class TestExecution:
    @pytest.mark.asyncio
    async def test_execute_registered_tool(self, kernel):
        async def my_tool(deps, value: str) -> str:
            return f"got: {value}"
        kernel.register_tool("exec.tool", my_tool, "plugin", is_external=False)
        result = await kernel.execute("exec.tool", deps=MagicMock(), value="hello")
        assert result == "got: hello"

    @pytest.mark.asyncio
    async def test_execute_unregistered_raises(self, kernel):
        with pytest.raises(KeyError, match="not registered"):
            await kernel.execute("missing.tool", deps=MagicMock())


class TestPluginLoading:
    @pytest.mark.asyncio
    async def test_load_template_plugin(self, kernel):
        """The _template plugin skipped by load_all_plugins but can be loaded directly."""
        # Direct load bypasses the _ prefix skip
        kernel.load_plugin("_template")
        assert "my_plugin.do_thing" in kernel.list_tools()

    @pytest.mark.asyncio
    async def test_unload_non_core_plugin(self, kernel):
        kernel.load_plugin("_template")
        assert kernel.has_tool("my_plugin.do_thing")
        # _template has core=false so it can be unloaded
        kernel.unload_plugin("my_plugin")
        assert not kernel.has_tool("my_plugin.do_thing")

    @pytest.mark.asyncio
    async def test_list_plugins(self, kernel):
        kernel.load_plugin("_template")
        plugins = kernel.list_plugins()
        names = [p["name"] for p in plugins]
        assert "my_plugin" in names


class TestVeraDeps:
    @pytest.mark.asyncio
    async def test_run_tool_calls_kernel(self, kernel, tmp_path):
        from core.deps import VeraDeps
        from core.secrets import SecretsManager
        from core.security import SecurityManager
        from unittest.mock import patch
        from opentelemetry import trace

        async def echo(deps, msg: str) -> str:
            return msg

        kernel.register_tool("echo.tool", echo, "test", is_external=False)

        sm = SecretsManager(backend="sqlite")
        sm._sqlite_path = str(tmp_path / "sec.db")
        sec = SecurityManager()

        deps = VeraDeps.model_construct(
            user_id="u1", user_roles=["owner"], session_id="s1",
            kernel=kernel, bus=kernel._bus, vfs=kernel._vfs,
            secrets=sm, enforcer=sec.enforcer,
            tracer=trace.get_tracer("test"),
        )

        result = await deps.run_tool("echo.tool", msg="hello")
        assert result == "hello"

    def test_can_method(self, tmp_path):
        from core.deps import VeraDeps
        from core.secrets import SecretsManager
        from core.security import SecurityManager
        from opentelemetry import trace
        from unittest.mock import MagicMock

        sec = SecurityManager()
        deps = VeraDeps.model_construct(
            user_id="u1", user_roles=["owner"], session_id="s1",
            kernel=MagicMock(), bus=MagicMock(), vfs=MagicMock(),
            secrets=MagicMock(), enforcer=sec.enforcer,
            tracer=trace.get_tracer("test"),
        )
        assert deps.can("gmail.check_inbox") is True

        deps_guest = deps.model_copy(update={"user_roles": ["guest"]})
        assert deps_guest.can("gmail.check_inbox") is False
