---
title: "VeraKernel"
description: "Singleton kernel: plugin loader, tool registry, and execution engine."
tags: [kernel, plugins, tools, execution]
---

# VeraKernel

**File:** `core/kernel.py`

The kernel is the central coordinator.  It is a singleton initialised once at
startup via `setup_kernel()` and shared by all components through `VeraDeps`.

## Lifecycle

```python
kernel = VeraKernel.get_instance()
await kernel.initialise(bus, vfs)
kernel.load_middlewares_from_config()   # reads data/middleware.json
kernel.load_all_plugins()               # discovers + loads plugins/
```

## Plugin management

| Method | Description |
|---|---|
| `load_all_plugins()` | Scan `plugins/`, resolve deps, load in order |
| `load_plugin(name)` | Load a single plugin by directory name |
| `unload_plugin(name)` | Unload (non-core only) |
| `discover_plugins()` | Scan without loading — returns manifest dicts |
| `scaffold_plugin(name)` | Copy `_template` to create a new plugin |
| `list_plugins()` | Return info dicts for all loaded plugins |

## Tool registry

| Method | Description |
|---|---|
| `register_tool(name, fn, plugin, is_external)` | Called by plugins during load |
| `list_tools()` | All registered tool names |
| `has_tool(name)` | Existence check |
| `list_tool_details()` | Name + plugin + is_external + docstring |
| `get_tool_info(name)` | Full introspection: params, types, doc |

## Execution

```python
result = await kernel.execute(tool_name, deps, **kwargs)
```

Runs the full middleware chain:

```
before_call (sorted by order ASC)
  → AuthGuard → SecretsInjector → PIIMasker → Retry
    → [tool fn]
  → PIIMasker → CostRecorder → AuditLogger
after_call (sorted by order ASC)
```

Emits `tool.call_started`, `tool.call_succeeded`, or `tool.call_failed` on
the bus.  On exception every middleware's `on_error()` is called.

## Middleware management

| Method | Description |
|---|---|
| `add_middleware(mw)` | Register + auto-sort by `mw.order` |
| `discover_middlewares()` | Scan `core/middleware/` for implementations |
| `load_middlewares_from_config(path)` | Instantiate from `data/middleware.json` |
| `save_middleware_config(chain, path)` | Persist chain to JSON |
| `default_middleware_config()` | Return built-in default list |
