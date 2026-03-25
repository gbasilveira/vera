"""
VERA Extension System — cross-plugin contribution model.

Any component (plugin, interface, future WebUI) can declare **extension
points** it accepts contributions into.  Any plugin can then **contribute**
to those points by listing them in its ``manifest.yaml``.  The kernel
aggregates everything into a single ``ExtensionRegistry`` that hosts query
at startup to wire themselves together.

Manifest shape
--------------

Declaring extension points (the host side)::

    extension_points:
      - id: plugins.dashboard.widgets       # globally unique across the system
        type: widget
        description: "Add a widget to the dashboard."
        schema:                              # optional — documents expected params
          title: {type: string, required: true}
          component: {type: import_path, required: true}
          size: {type: string, default: "1x1", values: [1x1, 2x1, 2x2]}

Contributing to an extension point (the contributor side)::

    contributes:
      - point: interfaces.cli.commands
        type: command_group
        params:
          name: my_plugin
          help: "My Plugin commands"
          handler: "plugins.my_plugin.cli:app"   # module:attribute

      - point: interfaces.webui.pages
        type: page
        params:
          path: /my-plugin
          title: "My Plugin"
          component: "plugins.my_plugin.webui:Page"
          nav_icon: puzzle
          nav_order: 50

      - point: plugins.dashboard.widgets
        type: widget
        params:
          id: my_plugin.stats
          title: "My Stats"
          component: "plugins.my_plugin.widgets:StatsWidget"
          size: "2x1"

Built-in extension points
-------------------------
These are always registered regardless of which plugins are loaded:

  interfaces.cli.commands       command_group   Typer app added to the CLI
  interfaces.webui.pages        page            Future WebUI page
  interfaces.webui.nav          nav_item        Future WebUI navigation entry
  interfaces.webui.widgets      widget          Future WebUI free-floating widget
  core.middleware.chain         middleware       Extra middleware layer

Handler import path format
--------------------------
``module.dotted.path:attribute``  —  e.g. ``plugins.my_plugin.cli:app``
The part before ``:`` is passed to ``importlib.import_module``; the part
after is retrieved with ``getattr``.  If no ``:`` is present, the whole
string is treated as a module and the module itself is returned.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Optional


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class ExtensionPoint:
    """A named slot that plugins can contribute objects into.

    Declared either by the system (built-ins) or by a plugin via
    its ``extension_points`` manifest section.
    """
    id: str               # globally unique  e.g. "interfaces.cli.commands"
    owner: str            # who declared this point  e.g. "interfaces.cli"
    type: str             # semantic tag  e.g. "command_group", "page", "widget"
    description: str = ""
    schema: dict = field(default_factory=dict)   # optional param documentation


@dataclass
class Contribution:
    """A single contribution from one plugin to one extension point."""
    point: str            # target ExtensionPoint.id
    plugin: str           # contributing plugin name
    type: str             # should match the point's expected type
    params: dict = field(default_factory=dict)

    def resolve_handler(self, param: str = "handler") -> Any:
        """Import and return the object at ``params[param]``.

        Expects the value to be an import path in the form
        ``module.dotted.path:attribute``.
        """
        path = self.params.get(param, "")
        return ExtensionRegistry.resolve_import(path)


# ── Built-in extension points ─────────────────────────────────────────────

#: Points that exist regardless of loaded plugins.
BUILTIN_POINTS: list[ExtensionPoint] = [
    ExtensionPoint(
        id="interfaces.cli.commands",
        owner="interfaces.cli",
        type="command_group",
        description="Contribute a Typer command group to the VERA CLI.",
        schema={
            "name":    {"type": "string",      "required": True,
                        "description": "Sub-command name shown in vera --help"},
            "help":    {"type": "string",      "required": False},
            "handler": {"type": "import_path", "required": True,
                        "description": "module.path:typer_app_instance"},
        },
    ),
    ExtensionPoint(
        id="interfaces.webui.pages",
        owner="interfaces.webui",
        type="page",
        description="Contribute a page to the VERA Web UI.",
        schema={
            "path":      {"type": "string",      "required": True},
            "title":     {"type": "string",      "required": True},
            "component": {"type": "import_path", "required": True},
            "nav_icon":  {"type": "string",      "required": False},
            "nav_order": {"type": "integer",     "required": False, "default": 100},
        },
    ),
    ExtensionPoint(
        id="interfaces.webui.nav",
        owner="interfaces.webui",
        type="nav_item",
        description="Contribute a navigation entry to the VERA Web UI.",
        schema={
            "label":  {"type": "string",  "required": True},
            "path":   {"type": "string",  "required": True},
            "icon":   {"type": "string",  "required": False},
            "order":  {"type": "integer", "required": False, "default": 100},
        },
    ),
    ExtensionPoint(
        id="interfaces.webui.widgets",
        owner="interfaces.webui",
        type="widget",
        description="Contribute a widget to the VERA Web UI dashboard.",
        schema={
            "id":        {"type": "string",      "required": True},
            "title":     {"type": "string",      "required": True},
            "component": {"type": "import_path", "required": True},
            "size":      {"type": "string",      "required": False, "default": "1x1",
                          "values": ["1x1", "2x1", "1x2", "2x2"]},
        },
    ),
    ExtensionPoint(
        id="core.middleware.chain",
        owner="core",
        type="middleware",
        description="Contribute an extra middleware layer to the execution chain.",
        schema={
            "class": {"type": "import_path", "required": True,
                      "description": "Fully-qualified VeraMiddleware subclass"},
            "order": {"type": "integer", "required": True},
        },
    ),
    ExtensionPoint(
        id="interfaces.api.routes",
        owner="interfaces.api",
        type="router",
        description="Contribute a VeraRouter to the VERA REST API.",
        schema={
            "prefix":  {"type": "string",      "required": True,
                        "description": "URL prefix, e.g. /my-plugin"},
            "handler": {"type": "import_path", "required": True,
                        "description": "module.path:VeraRouter instance"},
            "tags":    {"type": "list[string]", "required": False,
                        "description": "OpenAPI tags for grouping"},
        },
    ),
    ExtensionPoint(
        id="interfaces.api.websocket",
        owner="interfaces.api",
        type="ws_namespace",
        description="Declare a WebSocket namespace served by this plugin.",
        schema={
            "namespace": {"type": "string", "required": True,
                          "description": "Namespace passed to WebSocketManager"},
            "description": {"type": "string", "required": False},
        },
    ),
]


# ── ExtensionRegistry ─────────────────────────────────────────────────────

class ExtensionRegistry:
    """Central registry for extension points and contributions.

    One instance lives on the kernel (``kernel.extensions``).  It is
    populated in two ways:

    1. Built-in points are registered at construction time.
    2. ``kernel.load_plugin()`` calls ``register_from_manifest()`` for
       every loaded plugin.
    """

    def __init__(self) -> None:
        self._points: dict[str, ExtensionPoint] = {}
        self._contributions: dict[str, list[Contribution]] = {}  # point_id → list

        # Register built-ins
        for point in BUILTIN_POINTS:
            self.register_point(point)

    # ── Point management ────────────────────────────────────────────────────

    def register_point(self, point: ExtensionPoint) -> None:
        """Register an extension point.  Silently overwrites on re-register."""
        self._points[point.id] = point

    def get_point(self, point_id: str) -> Optional[ExtensionPoint]:
        return self._points.get(point_id)

    def list_points(self) -> list[ExtensionPoint]:
        return list(self._points.values())

    # ── Contribution management ──────────────────────────────────────────────

    def contribute(self, contribution: Contribution) -> None:
        """Record a contribution.  The target point need not exist yet."""
        self._contributions.setdefault(contribution.point, []).append(contribution)

    def get_contributions(self, point_id: str) -> list[Contribution]:
        """Return all contributions for a given extension point."""
        return list(self._contributions.get(point_id, []))

    def list_contributions(self) -> list[Contribution]:
        """Return every recorded contribution across all points."""
        result: list[Contribution] = []
        for contribs in self._contributions.values():
            result.extend(contribs)
        return result

    def contributions_by_plugin(self, plugin_name: str) -> list[Contribution]:
        return [c for c in self.list_contributions() if c.plugin == plugin_name]

    # ── Manifest ingestion ──────────────────────────────────────────────────

    def register_from_manifest(self, manifest: dict) -> None:
        """Parse ``extension_points`` and ``contributes`` from a plugin manifest."""
        plugin_name = manifest.get("name", "<unknown>")

        for ep_raw in manifest.get("extension_points", []):
            if not ep_raw.get("id"):
                continue
            self.register_point(ExtensionPoint(
                id=ep_raw["id"],
                owner=plugin_name,
                type=ep_raw.get("type", "unknown"),
                description=ep_raw.get("description", ""),
                schema=ep_raw.get("schema", {}),
            ))

        for contrib_raw in manifest.get("contributes", []):
            point_id = contrib_raw.get("point")
            if not point_id:
                continue
            self.contribute(Contribution(
                point=point_id,
                plugin=plugin_name,
                type=contrib_raw.get("type", "unknown"),
                params=contrib_raw.get("params", {}),
            ))

    # ── Handler resolution ───────────────────────────────────────────────────

    @staticmethod
    def resolve_import(path: str) -> Any:
        """Import an object from a ``module.path:attribute`` string.

        Examples::

            resolve_import("plugins.my_plugin.cli:app")   # returns the Typer app
            resolve_import("plugins.my_plugin.cli")        # returns the module
        """
        if not path:
            raise ValueError("Empty import path")
        if ":" in path:
            module_path, attr = path.rsplit(":", 1)
            mod = importlib.import_module(module_path)
            return getattr(mod, attr)
        return importlib.import_module(path)

    # ── Convenience: scan manifests without loading plugins ──────────────────

    @staticmethod
    def scan_manifests(plugins_dir: str = "plugins") -> list[dict]:
        """Lightweight scan: return raw manifest dicts without loading plugin code.

        Used by the CLI at startup to discover contributions before the
        kernel is fully initialised.
        """
        from pathlib import Path
        import yaml

        results: list[dict] = []
        plugins_path = Path(plugins_dir)
        if not plugins_path.exists():
            return results

        for plugin_dir in sorted(plugins_path.iterdir()):
            if not plugin_dir.is_dir() or plugin_dir.name.startswith("_"):
                continue
            manifest_file = plugin_dir / "manifest.yaml"
            if not manifest_file.exists():
                continue
            try:
                with open(manifest_file) as f:
                    manifest = yaml.safe_load(f)
                if manifest:
                    results.append(manifest)
            except Exception:
                pass
        return results
