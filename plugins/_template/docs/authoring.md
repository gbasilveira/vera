---
title: "Plugin Authoring Guide"
description: "How to create, structure, test, and load a VERA plugin."
tags: [plugin, authoring, manifest, sdk, tools]
---

# Plugin Authoring Guide

## 1 — Scaffold

```bash
vera plugin new my_plugin          # copies plugins/_template → plugins/my_plugin
```

## 2 — Directory structure

```
plugins/my_plugin/
├── manifest.yaml      metadata + capabilities declaration
├── plugin.py          VeraPlugin subclass (register_tools / register_listeners)
├── tools.py           async tool implementations
├── schemas.py         Pydantic request/response models
└── docs/              ← put YOUR plugin's docs here
    └── authoring.md
```

## 3 — manifest.yaml

```yaml
name: my_plugin           # REQUIRED — must match directory name
version: 1.0.0            # REQUIRED
description: "What it does"
author: "Name <email>"
external: false           # REQUIRED — true = calls external APIs (triggers PII masking)
core: false               # REQUIRED — true = cannot be unloaded
roles_required: [intern]
tools:
  - my_plugin.do_thing    # REQUIRED — list every tool registered
storage:
  namespace: my_plugin
  backend: local
  ttl_seconds: null
  secrets_required:
    - api_key             # looked up as my_plugin.api_key
retry:
  max_attempts: 3
  backoff_factor: 2
  retryable_errors: [NetworkError]
dependencies: []

# ── Permissions ────────────────────────────────────────────────────────────
# Declare capabilities your plugin introduces and what it depends on.
# `provides` entries are registered as named Casbin permissions at load time.
# Operators grant them to roles via `vera policy grant`.
# `requires` is documentation — use it to communicate dependencies to operators.
permissions:
  provides:
    - name: perm:my_plugin:do_thing
      obj: my_plugin.*
      action: execute
      description: "Execute my_plugin's main tool"
  requires:
    - perm:llm:generate   # if your tools call LLM
    - perm:memory:read    # if your tools read memory
```

### Assigning permissions to roles after installation

```bash
vera policy grant manager perm:my_plugin:do_thing
vera policy grant intern  perm:my_plugin:do_thing
```

Plugins **cannot self-grant** — they only declare. This prevents privilege
escalation through plugin installation.

## 4 — plugin.py

```python
from core.kernel import VeraPlugin, VeraKernel
from core.bus import VeraBus

class MyPlugin(VeraPlugin):
    name = "my_plugin"
    version = "1.0.0"

    def register_tools(self, kernel: VeraKernel) -> None:
        from plugins.my_plugin.tools import do_thing
        kernel.register_tool("my_plugin.do_thing", do_thing, "my_plugin", is_external=False)

    def register_listeners(self, bus: VeraBus) -> None:
        bus.on("tool.call_failed", self._on_failure)
```

## 5 — tools.py

```python
async def do_thing(deps, text: str) -> str:
    # deps is a VeraDeps — use it for all service access
    stored = await deps.vfs.get(f"my_plugin:cache:{text}")
    if stored:
        return stored.decode()
    result = f"processed: {text}"
    await deps.vfs.set(f"my_plugin:cache:{text}", result.encode(), ttl=300)
    return result
```

Rules:
- Tools must be **async**
- First argument is always `deps: VeraDeps`
- **Never import from `core/`** directly — use `deps.*`
- Use `deps.can("tool.name")` for pre-flight permission checks without execution
- Use `deps.user_roles` to inspect all roles; `deps.user_role` for the primary one (display only)

## 6 — Verify & load

```bash
vera plugin verify plugins/my_plugin    # run SDK contract tests
vera plugin load my_plugin              # load into running kernel
vera plugin info my_plugin              # show manifest
```

## 7 — Extension system

Plugins can integrate with other parts of VERA (CLI, WebUI, other plugins)
without those hosts knowing about them.

### Expose a slot for others to fill

```yaml
# manifest.yaml
extension_points:
  - id: plugins.my_plugin.widgets
    type: widget
    description: "Contribute a widget to my_plugin's view."
    schema:
      title:     {type: string,      required: true}
      component: {type: import_path, required: true}
```

### Contribute to an existing slot

```yaml
# manifest.yaml
contributes:
  # Add commands to the VERA CLI
  - point: interfaces.cli.commands
    type: command_group
    params:
      name: my_plugin
      help: "My Plugin commands"
      handler: "plugins.my_plugin.cli:app"   # ← typer.Typer() instance

  # Add a page to the Web UI
  - point: interfaces.webui.pages
    type: page
    params:
      path: /my-plugin
      title: "My Plugin"
      component: "plugins.my_plugin.webui:Page"

  # Push a widget to another plugin's dashboard
  - point: plugins.dashboard.widgets
    type: widget
    params:
      id: my_plugin.stats
      title: "My Stats"
      component: "plugins.my_plugin.widgets:StatsWidget"
      size: "2x1"
```

Create `plugins/my_plugin/cli.py` with a `app = typer.Typer(...)` and your
commands there.  The CLI will auto-discover and wire it at startup.

Run `vera ext points` to see all available extension points.

## SDK contract tests

Located in `tests/plugin_sdk/`.  They check:

- All required manifest fields are present
- Plugin class inherits from `VeraPlugin`
- All declared tools exist and are `async`
- Tool files do not import directly from `core/`
