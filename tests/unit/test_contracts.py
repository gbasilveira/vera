"""
Contract tests — verify all ABCs and schemas have the correct structure.
These tests run without any implementations.
"""
import inspect
import pytest
from abc import ABC


class TestVeraFileSystemContract:
    def test_is_abstract(self):
        from core.vfs.base import VeraFileSystem
        assert issubclass(VeraFileSystem, ABC)

    def test_cannot_instantiate(self):
        from core.vfs.base import VeraFileSystem
        with pytest.raises(TypeError):
            VeraFileSystem()

    def test_has_get_method(self):
        from core.vfs.base import VeraFileSystem
        sig = inspect.signature(VeraFileSystem.get)
        params = list(sig.parameters)
        assert 'key' in params

    def test_has_set_method(self):
        from core.vfs.base import VeraFileSystem
        sig = inspect.signature(VeraFileSystem.set)
        params = list(sig.parameters)
        assert 'key' in params
        assert 'value' in params
        assert 'ttl' in params

    def test_has_delete_method(self):
        from core.vfs.base import VeraFileSystem
        assert hasattr(VeraFileSystem, 'delete')

    def test_has_list_keys_method(self):
        from core.vfs.base import VeraFileSystem
        assert hasattr(VeraFileSystem, 'list_keys')


class TestVeraBusContract:
    def test_is_abstract(self):
        from core.bus import VeraBus
        assert issubclass(VeraBus, ABC)

    def test_cannot_instantiate(self):
        from core.bus import VeraBus
        with pytest.raises(TypeError):
            VeraBus()

    def test_has_emit(self):
        from core.bus import VeraBus
        sig = inspect.signature(VeraBus.emit)
        assert 'signal' in sig.parameters
        assert 'payload' in sig.parameters

    def test_has_on(self):
        from core.bus import VeraBus
        sig = inspect.signature(VeraBus.on)
        assert 'signal' in sig.parameters
        assert 'handler' in sig.parameters


class TestVeraMiddlewareContract:
    def test_is_abstract(self):
        from core.middleware.base import VeraMiddleware
        assert issubclass(VeraMiddleware, ABC)

    def test_cannot_instantiate(self):
        from core.middleware.base import VeraMiddleware
        with pytest.raises(TypeError):
            VeraMiddleware()

    def test_has_before_call(self):
        from core.middleware.base import VeraMiddleware
        sig = inspect.signature(VeraMiddleware.before_call)
        assert 'ctx' in sig.parameters

    def test_has_after_call(self):
        from core.middleware.base import VeraMiddleware
        sig = inspect.signature(VeraMiddleware.after_call)
        assert 'ctx' in sig.parameters
        assert 'result' in sig.parameters

    def test_has_on_error_with_default(self):
        """on_error is not abstract — it has a default no-op implementation."""
        from core.middleware.base import VeraMiddleware
        # Should not be in __abstractmethods__
        assert 'on_error' not in getattr(VeraMiddleware, '__abstractmethods__', set())

    def test_order_constants_defined(self):
        from core.middleware.base import ORDER_AUTH, ORDER_SECRETS, ORDER_PII, ORDER_RETRY, ORDER_COST, ORDER_AUDIT
        assert ORDER_AUTH < ORDER_SECRETS < ORDER_PII < ORDER_RETRY < ORDER_COST < ORDER_AUDIT


class TestToolCallContextContract:
    def test_is_frozen_dataclass(self):
        import dataclasses
        from core.middleware.base import ToolCallContext
        assert dataclasses.is_dataclass(ToolCallContext)
        assert ToolCallContext.__dataclass_params__.frozen

    def test_required_fields_exist(self):
        import dataclasses
        from core.middleware.base import ToolCallContext
        field_names = {f.name for f in dataclasses.fields(ToolCallContext)}
        required = {'call_id', 'tool_name', 'plugin_name', 'agent_id', 'user_role',
                    'user_id', 'tenant_id', 'payload', 'is_external', 'vfs', 'secrets',
                    'enforcer', 'bus', 'injected_secrets'}
        assert required.issubset(field_names)

    def test_with_payload_returns_copy(self):
        """Verify with_payload() creates a new instance (immutability)."""
        from core.middleware.base import ToolCallContext
        ctx = ToolCallContext(
            call_id='x', tool_name='t', plugin_name='p', agent_id='a',
            user_role='owner', user_id='u', tenant_id='default',
            payload={'key': 'old'}, is_external=False,
            vfs=None, secrets=None, enforcer=None, bus=None,
        )
        new_ctx = ctx.with_payload({'key': 'new'})
        assert new_ctx is not ctx
        assert new_ctx.payload == {'key': 'new'}
        assert ctx.payload == {'key': 'old'}  # Original unchanged


class TestVeraPluginContract:
    def test_is_abstract(self):
        from core.kernel import VeraPlugin
        assert issubclass(VeraPlugin, ABC)

    def test_register_tools_is_abstract(self):
        from core.kernel import VeraPlugin
        assert 'register_tools' in VeraPlugin.__abstractmethods__

    def test_register_listeners_has_default(self):
        from core.kernel import VeraPlugin
        assert 'register_listeners' not in VeraPlugin.__abstractmethods__


class TestLLMAdapterContract:
    def test_is_abstract(self):
        from plugins.llm_driver.adapters.base import LLMAdapter
        assert issubclass(LLMAdapter, ABC)

    def test_all_methods_abstract(self):
        from plugins.llm_driver.adapters.base import LLMAdapter
        for method in ('generate_structured', 'stream', 'embed'):
            assert method in LLMAdapter.__abstractmethods__

    def test_generate_structured_signature(self):
        from plugins.llm_driver.adapters.base import LLMAdapter
        sig = inspect.signature(LLMAdapter.generate_structured)
        params = set(sig.parameters)
        assert {'prompt', 'schema', 'model', 'temperature'}.issubset(params)


class TestTokenUsageContract:
    def test_is_dataclass(self):
        import dataclasses
        from plugins.llm_driver.adapters.base import TokenUsage
        assert dataclasses.is_dataclass(TokenUsage)

    def test_fields(self):
        import dataclasses
        from plugins.llm_driver.adapters.base import TokenUsage
        names = {f.name for f in dataclasses.fields(TokenUsage)}
        assert names == {'prompt_tokens', 'completion_tokens', 'total_tokens', 'cost_usd'}

    def test_instantiation(self):
        from plugins.llm_driver.adapters.base import TokenUsage
        t = TokenUsage(10, 20, 30, 0.001)
        assert t.total_tokens == 30


class TestVeraDepsContract:
    def test_is_pydantic_model(self):
        from pydantic import BaseModel
        from core.deps import VeraDeps
        assert issubclass(VeraDeps, BaseModel)

    def test_required_fields(self):
        from core.deps import VeraDeps
        fields = VeraDeps.model_fields
        for f in ('user_id', 'user_roles', 'session_id', 'kernel', 'bus', 'vfs', 'secrets', 'enforcer', 'tracer'):
            assert f in fields, f"Missing field: {f}"

    def test_has_run_tool_method(self):
        from core.deps import VeraDeps
        assert hasattr(VeraDeps, 'run_tool')
        assert inspect.iscoroutinefunction(VeraDeps.run_tool)

    def test_has_can_method(self):
        from core.deps import VeraDeps
        assert hasattr(VeraDeps, 'can')


class TestSchemas:
    def test_llm_schemas(self):
        from plugins.llm_driver.schemas import LLMGenerateRequest, LLMStreamRequest, LLMEmbedRequest
        r = LLMGenerateRequest(prompt="hello", schema_name="MySchema")
        assert r.temperature == 0.1
        s = LLMStreamRequest(prompt="hi")
        e = LLMEmbedRequest(text="text")
        assert e.text == "text"

    def test_memory_schemas(self):
        from plugins.memory_rag.schemas import MemoryChunk, StoreMemoryRequest, RetrieveContextRequest, ForgetRequest
        chunk = MemoryChunk(chunk_id="x", content="hello", namespace="ns", metadata={}, score=0.9)
        assert chunk.score == 0.9
        req = RetrieveContextRequest(query="q", namespace="ns")
        assert req.top_k == 5
        forget_by_ns = ForgetRequest(namespace="ns")
        forget_by_ids = ForgetRequest(chunk_ids=["a", "b"])

    def test_memory_chunk_score_range(self):
        from plugins.memory_rag.schemas import MemoryChunk
        chunk = MemoryChunk(chunk_id="x", content="c", namespace="n", metadata={}, score=0.75)
        assert 0 <= chunk.score <= 1


class TestCasbinPolicies:
    def test_files_exist(self):
        from pathlib import Path
        assert Path("data/casbin/rbac_model.conf").exists()
        assert Path("data/casbin/policy.csv").exists()

    def test_enforcer_loads(self):
        import casbin
        e = casbin.Enforcer("data/casbin/rbac_model.conf", "data/casbin/policy.csv")
        assert e is not None

    def test_owner_can_execute_all(self):
        import casbin
        e = casbin.Enforcer("data/casbin/rbac_model.conf", "data/casbin/policy.csv")
        assert e.enforce("owner", "gmail.check_inbox", "execute") is True
        assert e.enforce("owner", "llm.generate_structured", "execute") is True

    def test_guest_cannot_execute(self):
        import casbin
        e = casbin.Enforcer("data/casbin/rbac_model.conf", "data/casbin/policy.csv")
        assert e.enforce("guest", "gmail.check_inbox", "execute") is False
        assert e.enforce("guest", "memory.store_memory", "execute") is False

    def test_manager_can_execute_business_tools(self):
        import casbin
        e = casbin.Enforcer("data/casbin/rbac_model.conf", "data/casbin/policy.csv")
        assert e.enforce("manager", "gmail.check_inbox", "execute") is True
        assert e.enforce("manager", "llm.generate_structured", "execute") is True

    def test_intern_cannot_execute_external_tools(self):
        import casbin
        e = casbin.Enforcer("data/casbin/rbac_model.conf", "data/casbin/policy.csv")
        assert e.enforce("intern", "gmail.check_inbox", "execute") is False

    def test_role_inheritance(self):
        """Manager inherits intern permissions; intern inherits guest."""
        import casbin
        e = casbin.Enforcer("data/casbin/rbac_model.conf", "data/casbin/policy.csv")
        # manager inherits intern's memory.retrieve_context
        assert e.enforce("manager", "memory.retrieve_context", "execute") is True

class TestExceptions:
    def test_all_exceptions_importable(self):
        from core.middleware.base import (
            PermissionDenied, SecretNotFound, PIIMaskError,
            PIISwapError, MaxRetriesExceeded
        )

    def test_exceptions_are_exception_subclasses(self):
        from core.middleware.base import (
            PermissionDenied, SecretNotFound, PIIMaskError,
            PIISwapError, MaxRetriesExceeded
        )
        for exc in (PermissionDenied, SecretNotFound, PIIMaskError, PIISwapError, MaxRetriesExceeded):
            assert issubclass(exc, Exception)

    def test_exceptions_can_be_raised_and_caught(self):
        from core.middleware.base import PermissionDenied
        with pytest.raises(PermissionDenied):
            raise PermissionDenied("role 'guest' cannot execute 'gmail.send_email'")