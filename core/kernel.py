"""
VERA Kernel module.

VeraPlugin ABC is defined here so plugins can import it without
importing the full kernel implementation.

"""
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import asyncio
import importlib
import inspect
import os
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from core.bus import VeraBus
from core.middleware.base import VeraMiddleware
from core.vfs.base import VeraFileSystem

if TYPE_CHECKING:
    from core.bus import VeraBus


class VeraPlugin(ABC):
    """
    Abstract base class for all VERA plugins (Drivers).

    Every plugin must:
    1. Set class-level `name` and `version` attributes.
    2. Implement register_tools() to register tools with the kernel.
    3. Optionally implement register_listeners() to subscribe to bus signals.

    Plugin directories must contain a manifest.yaml. Required manifest fields:
      name, version, external (bool), core (bool), tools (list[str])
    Optional:  roles_required, storage, retry, listeners, dependencies
    """
    name: str
    version: str

    @abstractmethod
    def register_tools(self, kernel: "VeraKernel") -> None:  # noqa: F821
        """Register this plugin's tools with the kernel tool registry."""
        ...

    def register_listeners(self, bus: "VeraBus") -> None:
        """
        Subscribe to bus signals. Override in plugins that react to events.
        Default: no-op (most plugins don't need this).
        """
        pass

    def register_auth_providers(self, auth_manager: "AuthManager") -> None:  # noqa: F821
        """
        Register one or more VeraAuthProvider instances with the AuthManager.
        Override this in auth plugins to plug in new identity providers.

        Example:
            def register_auth_providers(self, auth_manager):
                auth_manager.register_provider(GitHubOAuthProvider(...))

        Default: no-op (most plugins do not supply auth providers).
        """
        pass

    def register_extensions(self, registry: "ExtensionRegistry") -> None:  # noqa: F821
        """
        Programmatically register extension points or contributions that
        cannot be expressed in the manifest (e.g. dynamic point IDs).

        This is called after the manifest's ``extension_points`` and
        ``contributes`` sections are already processed, so it supplements
        rather than replaces manifest-driven registration.

        Example::

            def register_extensions(self, registry):
                registry.register_point(ExtensionPoint(
                    id=f"plugins.{self.name}.slots",
                    owner=self.name,
                    type="slot",
                    description="Dynamic per-tenant slot",
                ))

        Default: no-op.
        """
        pass

class VeraKernel:
    """
    VERA Kernel singleton. Plugin loader, tool registry, and middleware executor.

    Usage:
        kernel = VeraKernel.get_instance()
        await kernel.initialise(bus=bus, vfs=vfs)
        kernel.load_all_plugins()
    """

    _instance: Optional["VeraKernel"] = None

    def __init__(self):
        self._tool_registry: dict[str, dict] = {}
        self._plugins: dict[str, VeraPlugin] = {}       # name -> plugin instance
        self._plugin_manifests: dict[str, dict] = {}    # name -> parsed manifest
        self._active_plugins: set[str] = set()
        self._middleware: list[VeraMiddleware] = []     # Populated in Phase 3
        self._bus: Optional[VeraBus] = None
        self._vfs: Optional[VeraFileSystem] = None
        self._plugins_dir: str = os.getenv("VERA_PLUGINS_DIR", "plugins")
        self._auth_manager: Optional[Any] = None        # AuthManager, set by setup_kernel()
        self._security: Optional[Any] = None            # SecurityManager, set by setup_kernel()

        from core.extensions import ExtensionRegistry
        self.extensions = ExtensionRegistry()
        self._deps_factory = None   # set by setup_kernel()
        self._ws_manager = None     # set by setup_kernel()

    @classmethod
    def get_instance(cls) -> "VeraKernel":
        """Return the singleton kernel instance (creates it if needed)."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton. For testing only — never call in production."""
        cls._instance = None

    async def initialise(self, bus: VeraBus, vfs: VeraFileSystem) -> None:
        """Wire in the bus and VFS. Must be called before load_all_plugins()."""
        self._bus = bus
        self._vfs = vfs

    # ── Plugin lifecycle ───────────────────────────────────────────────────

    def load_all_plugins(self) -> None:
        """
        Discover and load all plugins in the plugins directory.
        A valid plugin directory must contain a manifest.yaml.
        Skips _* and any directory without manifest.yaml.
        Resolves dependencies iteratively according to two-phase load.
        """
        plugins_path = Path(self._plugins_dir)
        plugins_to_load = {}

        if not plugins_path.exists():
            return

        # Phase 1: Discover all manifests
        for plugin_dir in sorted(plugins_path.iterdir()):
            if not plugin_dir.is_dir():
                continue
            if plugin_dir.name.startswith("_"):
                continue  # Skip _template and similar
            manifest_file = plugin_dir / "manifest.yaml"
            if not manifest_file.exists():
                continue

            try:
                with open(manifest_file) as f:
                    manifest = yaml.safe_load(f)
                plugins_to_load[plugin_dir.name] = manifest
            except Exception as e:
                print(f"[VERA] Warning: failed to parse manifest for '{plugin_dir.name}': {e}")
                continue

        # Phase 2: Load plugins iteratively until no progress
        remaining = set(plugins_to_load.keys())
        loaded_in_pass = True

        while remaining and loaded_in_pass:
            loaded_in_pass = False

            for plugin_name in list(remaining):
                manifest = plugins_to_load[plugin_name]
                deps = manifest.get("dependencies", [])

                deps_satisfied = True
                for dep in deps:
                    dep_name = dep.split(">=")[0].strip()
                    if dep_name not in self._active_plugins:
                        deps_satisfied = False
                        break

                if deps_satisfied:
                    try:
                        self.load_plugin(plugin_name)
                    except Exception as e:
                        print(f"[VERA] Warning: failed to load plugin '{plugin_name}': {e}")
                    
                    # Remove from remaining whether it succeeded or failed
                    # to prevent infinite loop on failure
                    remaining.remove(plugin_name)
                    loaded_in_pass = True

        if remaining:
            unresolved = []
            for p in remaining:
                manifest = plugins_to_load[p]
                deps = [d.split(">=")[0].strip() for d in manifest.get("dependencies", [])]
                missing = [d for d in deps if d not in self._active_plugins]
                unresolved.append(f"{p} (missing: {', '.join(missing)})")
            raise RuntimeError(f"Unresolved plugin dependencies: {', '.join(unresolved)}")

    def load_plugin(self, plugin_name: str) -> None:
        """Load a single plugin by directory name."""
        manifest_path = Path(self._plugins_dir) / plugin_name / "manifest.yaml"
        if not manifest_path.exists():
            raise FileNotFoundError(f"No manifest.yaml for plugin '{plugin_name}'")

        with open(manifest_path) as f:
            manifest = yaml.safe_load(f)

        # Validate required manifest fields
        for field in ("name", "version", "external", "core", "tools"):
            if field not in manifest:
                raise ValueError(f"Plugin '{plugin_name}' manifest missing required field: {field}")

        # Check dependencies
        for dep in manifest.get("dependencies", []):
            dep_name = dep.split(">=")[0].strip()
            if dep_name not in self._active_plugins:
                raise RuntimeError(
                    f"Plugin '{plugin_name}' requires '{dep_name}' which is not loaded."
                )

        # Register extension points and contributions declared in this manifest
        self.extensions.register_from_manifest(manifest)

        # Register permissions declared in this plugin's manifest
        self._register_plugin_permissions(manifest)

        # Import and instantiate the plugin class
        module = importlib.import_module(f"plugins.{plugin_name}.plugin")
        plugin_classes = [
            cls for name, cls in vars(module).items()
            if isinstance(cls, type) and issubclass(cls, VeraPlugin) and cls is not VeraPlugin
        ]
        if not plugin_classes:
            raise RuntimeError(f"No VeraPlugin subclass found in plugins/{plugin_name}/plugin.py")

        plugin_instance = plugin_classes[0]()
        plugin_instance.register_tools(self)
        if self._bus:
            plugin_instance.register_listeners(self._bus)
        if self._auth_manager is not None:
            plugin_instance.register_auth_providers(self._auth_manager)
        plugin_instance.register_extensions(self.extensions)

        self._plugins[manifest["name"]] = plugin_instance
        self._plugin_manifests[manifest["name"]] = manifest
        self._active_plugins.add(manifest["name"])

        if self._bus:
            asyncio.get_event_loop().create_task(
                self._bus.emit("kernel.plugin_loaded", {
                    "plugin_name": manifest["name"],
                    "version": manifest["version"],
                    "tools": manifest.get("tools", []),
                })
            )

    def unload_plugin(self, plugin_name: str) -> None:
        """Unload a plugin. Raises RuntimeError if plugin is core=true."""
        if plugin_name not in self._plugins:
            raise KeyError(f"Plugin '{plugin_name}' is not loaded.")
        manifest = self._plugin_manifests.get(plugin_name, {})
        if manifest.get("core", False):
            raise RuntimeError(f"Cannot unload core plugin '{plugin_name}'.")

        # Deregister tools
        tools_to_remove = [
            name for name, meta in self._tool_registry.items()
            if meta["plugin"] == plugin_name
        ]
        for tool_name in tools_to_remove:
            del self._tool_registry[tool_name]

        del self._plugins[plugin_name]
        del self._plugin_manifests[plugin_name]
        self._active_plugins.discard(plugin_name)

        if self._bus:
            asyncio.get_event_loop().create_task(
                self._bus.emit("kernel.plugin_unloaded", {"plugin_name": plugin_name})
            )

    def get_plugin_manifest(self, plugin_name: str) -> dict:
        return self._plugin_manifests.get(plugin_name, {})

    def list_plugins(self) -> list[dict]:
        return [
            {
                "name": name,
                "version": self._plugin_manifests[name]["version"],
                "active": name in self._active_plugins,
                "core": self._plugin_manifests[name].get("core", False),
                "external": self._plugin_manifests[name].get("external", False),
                "tools": self._plugin_manifests[name].get("tools", []),
                "description": self._plugin_manifests[name].get("description", ""),
            }
            for name in self._plugins
        ]

    def discover_plugins(self) -> list[dict]:
        """
        Scan the plugins directory and return manifest data for all valid plugin
        directories (including those not yet loaded). Skips _* directories.
        Does not import or instantiate any plugin code.
        """
        plugins_path = Path(self._plugins_dir)
        discovered = []
        if not plugins_path.exists():
            return discovered
        for plugin_dir in sorted(plugins_path.iterdir()):
            if not plugin_dir.is_dir() or plugin_dir.name.startswith("_"):
                continue
            manifest_file = plugin_dir / "manifest.yaml"
            if not manifest_file.exists():
                continue
            try:
                with open(manifest_file) as f:
                    manifest = yaml.safe_load(f)
                manifest["_dir"] = plugin_dir.name
                manifest["_loaded"] = manifest.get("name") in self._active_plugins
                discovered.append(manifest)
            except Exception as e:
                discovered.append({"_dir": plugin_dir.name, "_error": str(e), "_loaded": False})
        return discovered

    def scaffold_plugin(self, name: str) -> Path:
        """
        Create a new plugin directory by copying _template and substituting
        the placeholder name. Returns the new plugin directory path.
        Raises FileExistsError if the directory already exists.
        """
        import shutil
        template_dir = Path(self._plugins_dir) / "_template"
        dest_dir = Path(self._plugins_dir) / name

        if not template_dir.exists():
            raise FileNotFoundError(f"Template not found at {template_dir}")
        if dest_dir.exists():
            raise FileExistsError(f"plugins/{name} already exists")

        shutil.copytree(template_dir, dest_dir)

        manifest_file = dest_dir / "manifest.yaml"
        manifest_file.write_text(manifest_file.read_text().replace("my_plugin", name))

        plugin_py = dest_dir / "plugin.py"
        if plugin_py.exists():
            class_name = "".join(w.capitalize() for w in name.split("_")) + "Plugin"
            content = plugin_py.read_text()
            content = content.replace("my_plugin", name).replace("TemplatePlugin", class_name)
            plugin_py.write_text(content)

        return dest_dir

    def _register_plugin_permissions(self, manifest: dict) -> None:
        """
        Register named permissions declared in manifest['permissions']['provides'].

        Each entry must have: name, obj, action.
        Optional: effect (default 'allow'), description.

        Example manifest section:
            permissions:
              provides:
                - name: perm:gmail:send
                  obj: gmail.*
                  action: execute
                  description: Send emails via Gmail
              requires:
                - perm:llm:generate
        """
        if self._security is None:
            return
        permissions = manifest.get("permissions", {})
        provides = permissions.get("provides", []) if isinstance(permissions, dict) else []
        for entry in provides:
            name   = entry.get("name", "")
            obj    = entry.get("obj", "")
            action = entry.get("action", "execute")
            effect = entry.get("effect", "allow")
            if name and obj:
                self._security.register_permission(name, obj, action, effect)

    def list_tool_details(self) -> list[dict]:
        """Return name, plugin, is_external, and one-line doc for all registered tools."""
        return [
            {
                "name": tool_name,
                "plugin": meta["plugin"],
                "is_external": meta["is_external"],
                "doc": (meta.get("doc") or "").splitlines()[0] if meta.get("doc") else "",
            }
            for tool_name, meta in self._tool_registry.items()
        ]

    def get_tool_info(self, tool_name: str) -> dict:
        """
        Return full introspection data for a registered tool.

        Returns a dict with keys: name, plugin, is_external, doc, params.
        params is a list of dicts with keys: name, type (optional),
        default (optional), required (bool).
        Raises KeyError if the tool is not registered.
        """
        if tool_name not in self._tool_registry:
            raise KeyError(f"Tool '{tool_name}' is not registered.")
        meta = self._tool_registry[tool_name]
        return {
            "name": tool_name,
            "plugin": meta["plugin"],
            "is_external": meta["is_external"],
            "doc": meta.get("doc", ""),
            "params": meta.get("params", []),
        }

    # ── Tool registry ──────────────────────────────────────────────────────

    def register_tool(
        self,
        tool_name: str,
        fn: Callable,
        plugin_name: str,
        is_external: bool,
    ) -> None:
        """
        Register a tool function. Called by plugins during load_plugin().
        tool_name must be unique across all loaded plugins.

        Docstring and parameter signature are captured automatically from fn
        so they can be surfaced via get_tool_info() and the CLI.
        """
        import inspect
        if tool_name in self._tool_registry:
            raise ValueError(
                f"Tool '{tool_name}' already registered by '{self._tool_registry[tool_name]['plugin']}'. "
                f"Cannot register again for '{plugin_name}'."
            )
        # Capture introspection data at registration time so the fn reference
        # is not needed later for discovery.
        params = []
        try:
            sig = inspect.signature(fn)
            for pname, p in sig.parameters.items():
                if pname in ("self", "deps", "ctx"):
                    continue
                entry: dict = {"name": pname}
                if p.annotation is not inspect.Parameter.empty:
                    entry["type"] = getattr(p.annotation, "__name__", str(p.annotation))
                if p.default is not inspect.Parameter.empty:
                    entry["default"] = repr(p.default)
                entry["required"] = (
                    p.default is inspect.Parameter.empty
                    and p.kind not in (
                        inspect.Parameter.VAR_POSITIONAL,
                        inspect.Parameter.VAR_KEYWORD,
                    )
                )
                params.append(entry)
        except (ValueError, TypeError):
            pass

        self._tool_registry[tool_name] = {
            "fn": fn,
            "plugin": plugin_name,
            "is_external": is_external,
            "doc": (inspect.getdoc(fn) or "").strip(),
            "params": params,
        }
        if self._bus:
            asyncio.get_event_loop().create_task(
                self._bus.emit("kernel.tool_registered", {
                    "tool_name": tool_name,
                    "plugin_name": plugin_name,
                })
            )

    def list_tools(self) -> list[str]:
        return list(self._tool_registry.keys())

    def has_tool(self, tool_name: str) -> bool:
        return tool_name in self._tool_registry

    # ── Middleware management ──────────────────────────────────────────────

    def add_middleware(self, middleware: VeraMiddleware) -> None:
        """Register a middleware layer and keep the chain sorted by order."""
        self._middleware.append(middleware)
        self._middleware.sort(key=lambda m: m.order)

    def discover_middlewares(self) -> list[dict]:
        """
        Scan core/middleware/ and return metadata for every VeraMiddleware
        subclass found there — whether configured or not.
        """
        from core.middleware_config import discover
        return discover()

    def get_middleware_config(self, path: str = "data/middleware.json") -> list[dict] | None:
        """
        Load the middleware chain config from *path*.
        Returns None when the file does not exist yet.
        """
        from core.middleware_config import load
        return load(path)

    def save_middleware_config(self, chain: list[dict], path: str = "data/middleware.json") -> None:
        """Persist *chain* to *path* as JSON."""
        from core.middleware_config import save
        save(chain, path)

    def default_middleware_config(self) -> list[dict]:
        """Return the built-in default chain (does not read any file)."""
        from core.middleware_config import default_chain
        return default_chain()

    def load_middlewares_from_config(self, path: str = "data/middleware.json") -> None:
        """
        Read the middleware config at *path*, instantiate each enabled
        class, override its order with the configured value, and register
        it with add_middleware().

        Falls back to the built-in default chain when no config file exists.
        Middlewares whose constructor accepts a ``kernel`` parameter are
        auto-wired with ``self``.
        """
        from core.middleware_config import load, default_chain

        chain = load(path)
        if chain is None:
            chain = default_chain()

        for entry in sorted(chain, key=lambda e: e.get("order", 50)):
            if not entry.get("enabled", True):
                continue
            class_path = entry.get("class", "")
            if not class_path:
                continue
            try:
                module_path, cls_name = class_path.rsplit(".", 1)
                mod = importlib.import_module(module_path)
                cls = getattr(mod, cls_name)
            except Exception as exc:
                print(f"[VERA] Warning: could not load middleware '{entry['name']}': {exc}")
                continue

            sig = inspect.signature(cls.__init__)
            params = list(sig.parameters.keys())
            instance = cls(self) if "kernel" in params else cls()
            instance.order = entry["order"]
            self.add_middleware(instance)

    # ── Auth manager ───────────────────────────────────────────────────────

    def set_auth_manager(self, auth_manager: Any) -> None:
        """
        Attach the AuthManager to the kernel.
        Called by setup_kernel() after AuthManager is initialised.
        Auth plugins reach it via kernel.get_auth_manager() inside
        register_auth_providers().
        """
        self._auth_manager = auth_manager

    def get_auth_manager(self) -> Optional[Any]:
        """Return the active AuthManager, or None if auth is not configured."""
        return self._auth_manager

    def set_security(self, security: Any) -> None:
        """Attach the SecurityManager to the kernel (called by setup_kernel)."""
        self._security = security

    def get_security(self) -> Optional[Any]:
        """Return the active SecurityManager, or None if not configured."""
        return self._security

    # ── Execution ──────────────────────────────────────────────────────────

    async def execute(self, tool_name: str, deps: Any, **kwargs) -> Any:
        """
        Execute a registered tool through the full middleware chain.

        Chain order (before_call):
          AUTH(10) → SECRETS(20) → PII_MASK(30) → RETRY(40) → [EXECUTE]
        Chain order (after_call):
          [reverse of above, then] COST(70) → AUDIT(80)

        Errors: on_error() called on all middleware. Exception re-raised.
        """
        import time
        import uuid as _uuid

        if tool_name not in self._tool_registry:
            raise KeyError(f"Tool '{tool_name}' is not registered. Available: {self.list_tools()}")

        tool_meta = self._tool_registry[tool_name]
        manifest = self._plugin_manifests.get(tool_meta["plugin"], {})
        call_id = str(_uuid.uuid4())

        from core.middleware.base import ToolCallContext
        _user_roles = getattr(deps, "user_roles", None) or []
        _user_role  = getattr(deps, "user_role", None) or (_user_roles[0] if _user_roles else "guest")
        ctx = ToolCallContext(
            call_id=call_id,
            tool_name=tool_name,
            plugin_name=tool_meta["plugin"],
            agent_id=getattr(deps, "session_id", "unknown"),
            user_role=_user_role,
            user_roles=_user_roles,
            user_id=getattr(deps, "user_id", "unknown"),
            tenant_id=getattr(deps, "tenant_id", "default"),
            payload=kwargs,
            is_external=tool_meta["is_external"],
            vfs=getattr(deps, "vfs", None),
            secrets=getattr(deps, "secrets", None),
            enforcer=getattr(deps, "enforcer", None),
            bus=getattr(deps, "bus", None),
        )

        start_time = time.monotonic()
        if self._bus:
            await self._bus.emit("tool.call_started", {
                "call_id": call_id, "tool_name": tool_name,
                "agent_id": ctx.agent_id, "plugin_name": ctx.plugin_name,
            })

        # ── before_call chain ──────────────────────────────────────────────────
        sorted_mw = sorted(self._middleware, key=lambda m: m.order)
        for mw in sorted_mw:
            try:
                ctx = await mw.before_call(ctx)
            except Exception as e:
                for mw2 in sorted_mw:
                    await mw2.on_error(ctx, e)
                if self._bus:
                    await self._bus.emit("tool.call_failed", {
                        "call_id": call_id, "tool_name": tool_name, "error": str(e),
                        "error_type": type(e).__name__, "retries": 0,
                    })
                raise

        # ── execution (with retry) ─────────────────────────────────────────────
        from core.middleware.retry import RetryMiddleware, retry_with_backoff

        retry_config = RetryMiddleware.get_retry_config(manifest)

        try:
            result = await retry_with_backoff(
                fn=tool_meta["fn"],
                ctx=ctx,
                deps=deps,
                max_attempts=retry_config["max_attempts"],
                backoff_factor=retry_config["backoff_factor"],
                retryable_errors=retry_config["retryable_errors"],
            )
        except Exception as e:
            for mw in sorted_mw:
                await mw.on_error(ctx, e)
            if self._bus:
                await self._bus.emit("tool.call_failed", {
                    "call_id": call_id, "tool_name": tool_name, "error": str(e),
                    "error_type": type(e).__name__,
                })
            raise

        # ── after_call chain ───────────────────────────────────────────────────
        for mw in sorted_mw:
            result = await mw.after_call(ctx, result)

        duration_ms = int((time.monotonic() - start_time) * 1000)
        if self._bus:
            await self._bus.emit("tool.call_succeeded", {
                "call_id": call_id, "tool_name": tool_name,
                "plugin_name": ctx.plugin_name, "duration_ms": duration_ms,
            })

        return result