---
title: "Extension System — Points & Contributions"
description: "How plugins contribute CLI commands, API routes, UI pages, widgets, and more to each other."
tags: [extensions, contributions, plugins, cli, api, webui, widgets]
---

# Extension System — Points & Contributions

**File:** `core/extensions.py`

The extension system lets any plugin, interface, or component advertise
**extension points** it can accept contributions into, and lets any plugin
**contribute** objects to those points — all declared in `manifest.yaml`,
no code changes to the host required.

## Core concepts

```
Host (e.g. CLI, API server, dashboard plugin)
  declares → ExtensionPoint  (a named slot)
                ↑
Contributor plugin
  fills    → Contribution    (typed params + import path)
```

The kernel's `ExtensionRegistry` aggregates everything during plugin load
and is queried by hosts at startup.

## Manifest syntax

### Declaring extension points (host side)

```yaml
extension_points:
  - id: plugins.dashboard.widgets      # globally unique
    type: widget
    description: "Contribute a widget to the dashboard."
    schema:
      title:     {type: string,      required: true}
      component: {type: import_path, required: true}
      size:      {type: string,      required: false, default: "1x1",
                  values: [1x1, 2x1, 2x2]}
```

### Contributing to extension points (contributor side)

```yaml
contributes:
  # Add a Typer command group to the VERA CLI
  - point: interfaces.cli.commands
    type: command_group
    params:
      name: my_plugin
      help: "My Plugin commands"
      handler: "plugins.my_plugin.cli:app"

  # Mount a REST router in the API server
  - point: interfaces.api.routes
    type: router
    params:
      prefix: /my-plugin
      handler: "plugins.my_plugin.api:router"
      tags: [my-plugin]

  # Declare a WebSocket namespace
  - point: interfaces.api.websocket
    type: ws_namespace
    params:
      namespace: my-plugin
      description: "Real-time events from My Plugin"

  # Future WebUI page
  - point: interfaces.webui.pages
    type: page
    params:
      path: /my-plugin
      title: "My Plugin"
      component: "plugins.my_plugin.webui:Page"
      nav_icon: puzzle
      nav_order: 50

  # Widget for another plugin's dashboard
  - point: plugins.dashboard.widgets
    type: widget
    params:
      id: my_plugin.stats
      title: "My Stats"
      component: "plugins.my_plugin.widgets:StatsWidget"
      size: "2x1"
```

## Built-in extension points

| ID | Type | Owner | Purpose |
|---|---|---|---|
| `interfaces.cli.commands` | `command_group` | CLI | Typer app added to `vera` |
| `interfaces.api.routes` | `router` | API server | VeraRouter mounted at startup |
| `interfaces.api.websocket` | `ws_namespace` | API server | WebSocket namespace declaration |
| `interfaces.webui.pages` | `page` | WebUI | Full page with route |
| `interfaces.webui.nav` | `nav_item` | WebUI | Navigation entry |
| `interfaces.webui.widgets` | `widget` | WebUI | Free-floating widget |
| `core.middleware.chain` | `middleware` | core | Extra middleware layer |

## Handler import path format

`module.dotted.path:attribute` — e.g. `plugins.my_plugin.cli:app`

- Everything before `:` is passed to `importlib.import_module()`
- Everything after is retrieved with `getattr(module, attr)`
- If no `:` is present, the module itself is returned

## ExtensionRegistry API

```python
# On the kernel
kernel.extensions.list_points()
kernel.extensions.get_contributions("interfaces.api.routes")   # → list[Contribution]
kernel.extensions.list_contributions()
kernel.extensions.contributions_by_plugin("my_plugin")

# Resolve a handler import path
obj = ExtensionRegistry.resolve_import("plugins.my_plugin.api:router")

# Scan manifests without booting the kernel (used by CLI and API at startup)
manifests = ExtensionRegistry.scan_manifests("plugins")
```

## Programmatic registration (plugin.py)

For dynamic cases that can't be expressed in YAML:

```python
class MyPlugin(VeraPlugin):
    def register_extensions(self, registry):
        from core.extensions import ExtensionPoint
        registry.register_point(ExtensionPoint(
            id=f"plugins.{self.name}.tenant_slots",
            owner=self.name,
            type="slot",
            description="Per-tenant dynamic slot",
        ))
```

## How the CLI wires contributions

At import time (`interfaces/cli/main.py`), before any command runs:

1. `ExtensionRegistry.scan_manifests()` reads all `manifest.yaml` files
   (no plugin code imported, no kernel booted — fast)
2. For each `contributes` entry targeting `interfaces.cli.commands`:
   - Imports the Typer app via `resolve_import(handler)`
   - Calls `app.add_typer(handler, name=..., help=...)`
3. Contributed commands appear in `vera --help` alongside first-party ones

## How the API server wires contributions

During the FastAPI `lifespan` (after full kernel boot):

1. Queries `kernel.extensions.get_contributions("interfaces.api.routes")`
2. For each contribution, imports the `VeraRouter` and calls
   `app.include_router(router._fastapi_router, prefix=..., tags=...)`
3. Plugin routes are live at their declared prefix

## CLI

```bash
vera ext points                                    # list all extension points
vera ext contributions                             # all contributions
vera ext contributions --point interfaces.api.routes
vera ext contributions --plugin my_plugin
vera ext show interfaces.api.routes                # schema + contributions
```
