"""
VERA Middleware Configuration.

Manages the user-defined middleware chain persisted in data/middleware.json.

Discovery: scans core/middleware/ for all VeraMiddleware subclasses so that
any file a user drops into that package is immediately visible via the CLI.

Config format — a JSON array of objects:
  [
    {"name": "auth_guard",
     "class": "core.middleware.auth.AuthGuardMiddleware",
     "order": 10,
     "enabled": true},
    ...
  ]

`order` is the only constraint on execution sequence; lower = earlier.
"""
from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
from pathlib import Path

_DEFAULT_PATH = "data/middleware.json"

# Canonical defaults — used when no config file exists yet.
_BUILTIN_CHAIN: list[dict] = [
    {
        "name": "auth_guard",
        "class": "core.middleware.auth.AuthGuardMiddleware",
        "order": 10,
        "enabled": True,
    },
    {
        "name": "secrets_injector",
        "class": "core.middleware.secret_injector.SecretsInjectorMiddleware",
        "order": 20,
        "enabled": True,
    },
    {
        "name": "pii_masker",
        "class": "core.middleware.pii_masker.PIIMaskerMiddleware",
        "order": 30,
        "enabled": True,
    },
    {
        "name": "retry",
        "class": "core.middleware.retry.RetryMiddleware",
        "order": 40,
        "enabled": True,
    },
    {
        "name": "cost_recorder",
        "class": "core.middleware.cost_recorder.CostRecorderMiddleware",
        "order": 70,
        "enabled": True,
    },
    {
        "name": "audit_logger",
        "class": "core.middleware.auditor.AuditLoggerMiddleware",
        "order": 80,
        "enabled": True,
    },
]


def discover() -> list[dict]:
    """
    Scan core/middleware/ for VeraMiddleware subclasses.

    Returns a list of dicts:
      name        — middleware.name class attribute (or class name)
      class       — fully-qualified import path  e.g. core.middleware.auth.AuthGuardMiddleware
      description — first line of the class docstring
      order_hint  — default order from the class attribute
    """
    import core.middleware as _mw_pkg
    from core.middleware.base import VeraMiddleware

    found: list[dict] = []
    pkg_prefix = _mw_pkg.__name__ + "."

    for _, modname, _ in pkgutil.iter_modules(_mw_pkg.__path__):
        full_module = pkg_prefix + modname
        try:
            mod = importlib.import_module(full_module)
        except Exception:
            continue
        for cls_name, cls in inspect.getmembers(mod, inspect.isclass):
            if (
                issubclass(cls, VeraMiddleware)
                and cls is not VeraMiddleware
                and cls.__module__ == full_module
            ):
                raw_doc = inspect.getdoc(cls) or ""
                found.append({
                    "name": getattr(cls, "name", cls_name),
                    "class": f"{full_module}.{cls_name}",
                    "description": raw_doc.splitlines()[0] if raw_doc else "",
                    "order_hint": getattr(cls, "order", 50),
                })

    return found


def load(path: str = _DEFAULT_PATH) -> list[dict] | None:
    """
    Load the middleware chain config from *path*.
    Returns None if the file does not exist (caller decides what to do).
    """
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text())


def save(chain: list[dict], path: str = _DEFAULT_PATH) -> None:
    """Write *chain* to *path* as pretty-printed JSON."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(chain, indent=2) + "\n")


def default_chain() -> list[dict]:
    """Return a fresh copy of the built-in default middleware chain."""
    return [dict(e) for e in _BUILTIN_CHAIN]
