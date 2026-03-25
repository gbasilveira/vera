
# VERA Contracts Reference

> Auto-generated reference for Claude Code. Read this instead of scanning source files.

---

## Core ABCs — quick reference

### VeraFileSystem (`core/vfs/base.py`)
```python
async def get(key: str) -> Optional[bytes]
async def set(key: str, value: bytes, ttl: Optional[int] = None) -> None
async def delete(key: str) -> None
async def list_keys(prefix: str) -> list[str]
```
Key pattern: `plugin:entity:id` — e.g. `pii:mapping:call_abc`, `cost:agent1:2024-01-15:llm.generate`

### VeraBus (`core/bus.py`)
```python
async def emit(signal: str, payload: dict) -> None
def on(signal: str, handler: Callable) -> None
```
Signal pattern: `domain.event_name` — e.g. `tool.call_failed`, `agent.task_completed`
**WARNING**: BlinkerBus handlers are SYNC. Wrap async handlers with `asyncio.ensure_future`.

### VeraMiddleware (`core/middleware/base.py`)
```python
async def before_call(ctx: ToolCallContext) -> ToolCallContext
async def after_call(ctx: ToolCallContext, result: Any) -> Any
async def on_error(ctx: ToolCallContext, error: Exception) -> None  # default no-op
```
Order constants: ORDER_AUTH=10, ORDER_SECRETS=20, ORDER_PII=30, ORDER_RETRY=40, ORDER_COST=70, ORDER_AUDIT=80

### VeraPlugin (`core/kernel.py`)
```python
def register_tools(kernel: VeraKernel) -> None   # REQUIRED
def register_listeners(bus: VeraBus) -> None      # optional, default no-op
```
Class attrs: `name: str`, `version: str`

### LLMAdapter (`plugins/llm_driver/adapters/base.py`)
```python
async def generate_structured(prompt, schema, model, temperature) -> tuple[BaseModel, TokenUsage]
async def stream(prompt, model) -> AsyncIterator[str]
async def embed(text, model) -> list[float]
```

---

## ToolCallContext fields
```
call_id, tool_name, plugin_name, agent_id, user_role, user_id, tenant_id,
payload (dict), is_external (bool), vfs, secrets, enforcer, bus, injected_secrets (dict)
```
Immutable (frozen dataclass). Use `.with_payload(new_dict)` or `dataclasses.replace()`.

---

## VeraDeps fields
```
user_id, user_role, session_id, tenant_id (str, default='default')
kernel (VeraKernel), bus (VeraBus), vfs (VeraFileSystem),
secrets (SecretsManager), enforcer (casbin.Enforcer), tracer (OTel Tracer)
llm_provider (str), llm_model (str), llm_temperature (float)
memory_namespace (str, default='default')
```
Methods: `await run_tool(tool_name, **kwargs)`, `can(tool_name) -> bool`

---

## Exceptions (all in `core/middleware/base.py`)
- `PermissionDenied` — raised by AuthGuard
- `SecretNotFound` — raised by SecretsInjector
- `PIIMaskError` — raised by PIIMasker on outbound failure
- `PIISwapError` — raised by PIIMasker on inbound failure
- `MaxRetriesExceeded` — raised by RetryWrapper

---

## TokenUsage dataclass (`plugins/llm_driver/adapters/base.py`)
```
prompt_tokens: int, completion_tokens: int, total_tokens: int, cost_usd: float
```

---

## Schemas summary

### plugins/llm_driver/schemas.py
- `LLMGenerateRequest(prompt, schema_name, temperature=0.1)`
- `LLMGenerateResponse(result: dict, usage: TokenUsage)`
- `LLMStreamRequest(prompt)`
- `LLMEmbedRequest(text)`

### plugins/memory_rag/schemas.py
- `MemoryChunk(chunk_id, content, namespace, metadata, score)`
- `StoreMemoryRequest(content, namespace, metadata={})`
- `RetrieveContextRequest(query, namespace, top_k=5)`
- `ForgetRequest(chunk_ids | namespace)`

---

## Middleware execution order
```
before_call:  AUTH(10) → SECRETS(20) → PII_MASK(30) → RETRY(40) → [EXECUTE] →
after_call:   AUTH(10) → SECRETS(20) → PII_SWAP(30) → RETRY(40) → COST(70) → AUDIT(80)
on_error:     all middleware.on_error() called in order
```

---

## Casbin roles
owner > manager > intern > guest (inheritance via g rules)
Policy format: `p, subject, object_pattern, action, effect`
Model: RBAC with keyMatch2 wildcard matching on object

---

## Environment variables
```
VERA_BUS_BACKEND       blinker | redis | nats        (default: blinker)
VERA_LLM_PROVIDER      ollama | openai | anthropic   (default: ollama)
VERA_LLM_MODEL         model string                  (default: llama3)
VERA_VECTOR_BACKEND    chroma | lancedb | pgvector   (default: chroma)
VERA_SECRETS_BACKEND   keyring | sqlite              (default: keyring)
VERA_MASTER_KEY        master key for sqlite backend
VERA_VFS_PATH          path to SQLite VFS db         (default: data/vera_vfs.db)
VERA_CASBIN_MODEL      path to model.conf            (default: data/casbin/rbac_model.conf)
VERA_CASBIN_POLICY     path to policy.csv            (default: data/casbin/policy.csv)
VERA_PLUGINS_DIR       plugins directory             (default: plugins)
```

---

## Plugin manifest required fields
`name, version, external (bool), core (bool), tools (list[str])`
Optional: `roles_required, storage{namespace,backend,ttl_seconds}, retry{max_attempts,backoff_factor,retryable_errors}, listeners, dependencies`

## Plugin template location
`plugins/_template/` — copy this entire directory to start a new plugin.

## Plugin SDK contract tests
`pytest tests/plugin_sdk/ --plugin=plugins/my_plugin`
Checks: manifest structure, class inheritance, async tools, no forbidden imports.

---
### LocalFS (`core/vfs/local_fs.py`)
Implements VeraFileSystem with aiosqlite.
Constructor: `LocalFS(db_path=None)` — path from VERA_VFS_PATH or arg.
Factory: `from core.vfs import create_vfs` — returns LocalFS or RedisFS.
Call `await vfs.close()` during shutdown.

### BlinkerBus (`core/bus.py`)
Implements VeraBus with blinker.
Factory: `from core.bus import create_bus` — returns BlinkerBus (default).
**Handlers must be synchronous.** Async handlers: `bus.on('sig', lambda s, **kw: asyncio.ensure_future(coro(**kw)))`

### SecretsManager (`core/secrets.py`)
Constructor: `SecretsManager(backend='keyring'|'sqlite')` — from VERA_SECRETS_BACKEND.
- `await get(key)` — raises SecretNotFound
- `await get_optional(key)` — returns None
- `await set(key, value)`, `await delete(key)`, `await list_keys(prefix)`
SQLite backend requires VERA_MASTER_KEY env var.

### SecurityManager (`core/security.py`)
Constructor: `SecurityManager(model_path, policy_path, bus=None)`.
- `enforce(role, tool, action) -> bool`
- `add_policy(subject, obj, action, effect)` / `remove_policy(subject, obj, action)`
- `assign_role(user_id, role)` / `revoke_role(user_id, role)`
- `.enforcer` property — raw casbin.Enforcer (used in ToolCallContext)

### VeraKernel (`core/kernel.py`)
Singleton: `VeraKernel.get_instance()` / `VeraKernel.reset()` (test only)
Init: `await kernel.initialise(bus, vfs)`
Plugin lifecycle: `load_all_plugins()`, `load_plugin(name)`, `unload_plugin(name)`
Tool registry: `register_tool(name, fn, plugin_name, is_external)`, `has_tool(name)`, `list_tools()`
Execution: `await execute(tool_name, deps, **kwargs)` — Phase 2 = direct call, no middleware
Middleware: `add_middleware(mw)` — populates sorted `_middleware` list (Phase 3 will use it)

### VeraDepsFactory (`core/deps.py`)
Constructor: `VeraDepsFactory(kernel, bus, vfs, secrets, security)`
Usage: `factory.create(user_id, user_role, session_id=None, tenant_id='default')`

### Phase 3 note
Phase 3 will replace `VeraKernel.execute()` with the full middleware chain.
The Phase 2 implementation calls tools directly and must NOT be changed — Phase 3 
replaces the method body only, keeping the same signature.

### AuthGuardMiddleware (`core/middleware/auth.py`) — order=10
Raises PermissionDenied if Casbin denies. Emits security.permission_denied.

### SecretsInjectorMiddleware (`core/middleware/secrets_injector.py`) — order=20
Reads manifest secrets_required. Injects into ctx.injected_secrets. Raises SecretNotFound.

### PIIMaskerMiddleware (`core/middleware/pii_masker.py`) — order=30
external=True only. before_call: mask + persist to VFS. after_call: restore + delete.
VFS key: pii:mapping:{call_id}, TTL 3600s.

### RetryMiddleware / retry_with_backoff (`core/middleware/retry.py`) — order=40
retry_with_backoff(fn, ctx, deps, max_attempts, backoff_factor, retryable_errors) — used directly by kernel.
Emits tool.retry_attempt. Raises MaxRetriesExceeded.

### AuditLoggerMiddleware (`core/middleware/auditor.py`) — order=80
Writes to data/logs/audit.jsonl. Non-fatal. Records: timestamp, call_id, tool_name, 
plugin_name, user_id, user_role, tenant_id, status, duration_ms, error.
NEVER logs payload or result.

### CostRecorderMiddleware (`core/middleware/cost_recorder.py`) — order=70
Checks result for TokenUsage. Aggregates to VFS: cost:{agent_id}:{date}:{tool_name}. Non-fatal.

### Observability (`core/observability.py`)
setup_observability() -> tracer. wire_metrics_to_bus(bus) for Prometheus counters.
Metrics: vera_tool_calls_total, vera_tool_duration_ms, vera_llm_tokens_total, vera_llm_cost_usd_total.

### Phase 3B note
Phase 3B replaces VeraKernel.execute() with the full middleware chain.
It imports all middleware from this phase and wires them in order.


### VeraKernel.execute() — full chain
Chain: AUTH → SECRETS → PII_MASK → retry_with_backoff(EXECUTE) → COST → AUDIT
Signals emitted: tool.call_started, tool.call_succeeded | tool.call_failed
All middleware on_error() called on any exception.

### setup_kernel() (`core/kernel.py`)
One-call setup for production. Returns (kernel, bus, vfs, secrets, security, tracer, factory).
Called inside asyncio.run() in main.py (Phase 5).

### Phase 3 complete. Ready for Phase 4: Core Plugins.
Phase 4 builds: llm_driver (OpenAI + Anthropic + Ollama adapters),
memory_rag (Chroma backend), notifications stub, gmail_driver reference plugin.
All will be loaded via kernel.load_plugin() and execute through this chain.