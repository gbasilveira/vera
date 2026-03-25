"""
Full middleware chain integration test.

Tests the complete before_call → execute → after_call → signals pipeline
using a real kernel with all middleware wired in.
No external services required (mocked LLM, real SQLite VFS).
"""
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import casbin
from opentelemetry import trace

from core.bus import BlinkerBus
from core.deps import VeraDeps, VeraDepsFactory
from core.kernel import VeraKernel
from core.middleware.auth import AuthGuardMiddleware
from core.middleware.auditor import AuditLoggerMiddleware
from core.middleware.base import PermissionDenied, SecretNotFound
from core.middleware.cost_recorder import CostRecorderMiddleware
from core.middleware.pii_masker import PIIMaskerMiddleware
from core.middleware.retry import RetryMiddleware
from core.middleware.secret_injector import SecretsInjectorMiddleware
from core.secrets import SecretsManager
from core.security import SecurityManager
from core.vfs.local_fs import LocalFS


@pytest.fixture(autouse=True)
def reset_kernel():
    VeraKernel.reset()
    yield
    VeraKernel.reset()


import pytest_asyncio

@pytest_asyncio.fixture
async def full_setup(tmp_path):
    """Complete kernel setup with all middleware. Returns (kernel, factory, audit_log)."""
    from cryptography.fernet import Fernet
    import os

    bus = BlinkerBus()
    vfs = LocalFS(db_path=str(tmp_path / "vfs.db"))
    secrets = SecretsManager(backend="sqlite")
    secrets._sqlite_path = str(tmp_path / "secrets.db")
    os.environ["VERA_MASTER_KEY"] = Fernet.generate_key().decode()
    security = SecurityManager()
    audit_log = str(tmp_path / "audit.jsonl")

    kernel = VeraKernel.get_instance()
    await kernel.initialise(bus=bus, vfs=vfs)

    kernel.add_middleware(AuthGuardMiddleware())
    kernel.add_middleware(SecretsInjectorMiddleware(kernel))
    kernel.add_middleware(PIIMaskerMiddleware())
    kernel.add_middleware(RetryMiddleware(kernel))
    kernel.add_middleware(AuditLoggerMiddleware(log_path=audit_log))
    kernel.add_middleware(CostRecorderMiddleware())

    factory = VeraDepsFactory(kernel, bus, vfs, secrets, security)
    return kernel, factory, audit_log, vfs


@pytest.fixture
def owner_deps(full_setup):
    _, factory, _, _ = full_setup
    return factory.create(user_id="owner@test.com", user_roles=["owner"], session_id="s1")


@pytest.fixture
def guest_deps(full_setup):
    _, factory, _, _ = full_setup
    return factory.create(user_id="guest@test.com", user_roles=["guest"], session_id="s2")


class TestAuthIntegration:
    @pytest.mark.asyncio
    async def test_owner_can_execute_any_tool(self, full_setup, owner_deps):
        kernel, _, _, _ = full_setup
        async def my_tool(deps, **kw): return "ok"
        kernel.register_tool("test.my_tool", my_tool, "test_plugin", is_external=False)
        # Also register in manifest registry
        kernel._plugin_manifests["test_plugin"] = {"name": "test_plugin", "external": False, "core": False, "tools": []}
        result = await owner_deps.run_tool("test.my_tool")
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_guest_cannot_execute(self, full_setup, guest_deps):
        kernel, _, _, _ = full_setup
        async def my_tool(deps, **kw): return "ok"
        kernel.register_tool("test.guest_tool", my_tool, "test_plugin", is_external=False)
        kernel._plugin_manifests["test_plugin"] = {"name": "test_plugin", "external": False, "core": False, "tools": []}
        with pytest.raises(PermissionDenied):
            await guest_deps.run_tool("test.guest_tool")


class TestAuditIntegration:
    @pytest.mark.asyncio
    async def test_successful_call_writes_audit(self, full_setup, owner_deps):
        kernel, _, audit_log, _ = full_setup
        async def tool(deps, **kw): return "done"
        kernel.register_tool("audit.tool", tool, "test_plugin", is_external=False)
        kernel._plugin_manifests["test_plugin"] = {"name": "test_plugin", "external": False, "core": False, "tools": []}
        await owner_deps.run_tool("audit.tool")
        lines = Path(audit_log).read_text().strip().split("\n")
        record = json.loads(lines[-1])
        assert record["status"] == "success"
        assert record["tool_name"] == "audit.tool"

    @pytest.mark.asyncio
    async def test_failed_call_writes_audit(self, full_setup, owner_deps):
        kernel, _, audit_log, _ = full_setup
        async def bad_tool(deps, **kw): raise ValueError("intentional failure")
        kernel.register_tool("audit.bad_tool", bad_tool, "test_plugin", is_external=False)
        kernel._plugin_manifests["test_plugin"] = {"name": "test_plugin", "external": False, "core": False, "tools": []}
        with pytest.raises(ValueError):
            await owner_deps.run_tool("audit.bad_tool")
        lines = Path(audit_log).read_text().strip().split("\n")
        record = json.loads(lines[-1])
        assert record["status"] == "failure"
        assert record["error_type"] == "ValueError"


class TestPIIIntegration:
    @pytest.mark.asyncio
    async def test_pii_masked_before_external_tool(self, full_setup, owner_deps):
        kernel, _, _, vfs = full_setup
        received_payload = {}
        async def external_tool(deps, **kw):
            received_payload.update(kw)
            return "done"
        kernel.register_tool("ext.tool", external_tool, "ext_plugin", is_external=True)
        kernel._plugin_manifests["ext_plugin"] = {
            "name": "ext_plugin", "external": True, "core": False, "tools": [],
            "retry": {"max_attempts": 1, "backoff_factor": 1, "retryable_errors": []}
        }
        await owner_deps.run_tool("ext.tool", message="Contact john@secret.com for help")
        # The payload received by the tool function should have PII masked
        message = received_payload.get("message", "")
        assert "john@secret.com" not in message or "<<PII:" in message

    @pytest.mark.asyncio
    async def test_pii_mapping_cleaned_after_call(self, full_setup, owner_deps):
        kernel, _, _, vfs = full_setup
        async def external_tool(deps, **kw): return "response"
        kernel.register_tool("ext.clean_tool", external_tool, "ext_plugin", is_external=True)
        kernel._plugin_manifests["ext_plugin"] = {
            "name": "ext_plugin", "external": True, "core": False, "tools": [],
            "retry": {"max_attempts": 1, "backoff_factor": 1, "retryable_errors": []}
        }
        await owner_deps.run_tool("ext.clean_tool", email="private@test.com")
        # After call, no pii:mapping keys should remain in VFS
        keys = await vfs.list_keys("pii:mapping:")
        assert len(keys) == 0


class TestSignalIntegration:
    @pytest.mark.asyncio
    async def test_signals_emitted_on_success(self, full_setup, owner_deps):
        kernel, _, _, _ = full_setup
        received_signals = []
        kernel._bus.on("tool.call_started", lambda s, **kw: received_signals.append("started"))
        kernel._bus.on("tool.call_succeeded", lambda s, **kw: received_signals.append("succeeded"))

        async def tool(deps, **kw): return "ok"
        kernel.register_tool("sig.tool", tool, "test_plugin", is_external=False)
        kernel._plugin_manifests["test_plugin"] = {"name": "test_plugin", "external": False, "core": False, "tools": []}
        await owner_deps.run_tool("sig.tool")
        assert "started" in received_signals
        assert "succeeded" in received_signals

    @pytest.mark.asyncio
    async def test_failed_signal_emitted_on_error(self, full_setup, owner_deps):
        kernel, _, _, _ = full_setup
        received_signals = []
        kernel._bus.on("tool.call_failed", lambda s, **kw: received_signals.append("failed"))

        async def bad_tool(deps, **kw): raise RuntimeError("boom")
        kernel.register_tool("sig.bad_tool", bad_tool, "test_plugin", is_external=False)
        kernel._plugin_manifests["test_plugin"] = {"name": "test_plugin", "external": False, "core": False, "tools": []}
        with pytest.raises(RuntimeError):
            await owner_deps.run_tool("sig.bad_tool")
        assert "failed" in received_signals


class TestRetryIntegration:
    @pytest.mark.asyncio
    async def test_retries_on_transient_error(self, full_setup, owner_deps):
        kernel, _, _, _ = full_setup
        calls = [0]
        async def flaky_tool(deps, **kw):
            calls[0] += 1
            if calls[0] < 3:
                raise ConnectionError("temporary")
            return "recovered"

        kernel.register_tool("retry.tool", flaky_tool, "retry_plugin", is_external=False)
        kernel._plugin_manifests["retry_plugin"] = {
            "name": "retry_plugin", "external": False, "core": False, "tools": [],
            "retry": {"max_attempts": 3, "backoff_factor": 0, "retryable_errors": ["ConnectionError"]}
        }

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await owner_deps.run_tool("retry.tool")
        assert result == "recovered"
        assert calls[0] == 3
