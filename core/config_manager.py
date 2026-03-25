"""
VERA Configuration Manager — import, apply, export and diff YAML resources.

Inspired by kubectl, configuration is expressed as typed **resources** that
can be serialised to / deserialised from YAML files and applied idempotently
to a running VERA installation.

Resource structure (kubectl-style)::

    apiVersion: vera/v1
    kind: MiddlewareChain        # or Policy | EnvConfig
    metadata:
      name: production
      description: "..."         # optional
    spec:
      ...                        # kind-specific payload

Multiple resources can live in one file separated by ``---``.

Supported kinds
---------------
MiddlewareChain
    The ordered list of middleware layers.  Mapped to ``data/middleware.json``.

Policy
    Casbin RBAC policies (p-lines) and role-inheritance assignments (g-lines).
    Mapped to ``data/casbin/policy.csv``.

EnvConfig
    Environment variables written to ``.env``.
    ``VERA_MASTER_KEY`` is intentionally excluded from export.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except ImportError as _e:  # pragma: no cover
    raise ImportError("PyYAML is required: pip install pyyaml") from _e


# ── Public constants ────────────────────────────────────────────────────────

API_VERSION = "vera/v1"
VALID_KINDS = {"MiddlewareChain", "Policy", "EnvConfig"}

# Env vars that must never appear in an export
_REDACTED_VARS = {"VERA_MASTER_KEY"}


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class VeraResource:
    """A single typed configuration resource."""

    api_version: str
    kind: str
    metadata: dict
    spec: dict

    @classmethod
    def from_dict(cls, d: dict) -> "VeraResource":
        missing = [k for k in ("apiVersion", "kind", "spec") if k not in d]
        if missing:
            raise ValueError(f"Resource missing required fields: {missing}")
        if d["apiVersion"] != API_VERSION:
            raise ValueError(
                f"Unsupported apiVersion {d['apiVersion']!r}.  Expected {API_VERSION!r}."
            )
        if d["kind"] not in VALID_KINDS:
            raise ValueError(
                f"Unknown kind {d['kind']!r}.  Valid kinds: {sorted(VALID_KINDS)}"
            )
        return cls(
            api_version=d["apiVersion"],
            kind=d["kind"],
            metadata=d.get("metadata", {}),
            spec=d["spec"],
        )

    def to_dict(self) -> dict:
        return {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": self.metadata,
            "spec": self.spec,
        }

    @property
    def name(self) -> str:
        return self.metadata.get("name", "default")


@dataclass
class ApplyResult:
    """Outcome of applying a single resource."""

    kind: str
    name: str
    status: str              # "created" | "updated" | "unchanged"
    changes: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.status != "unchanged"


# ── ConfigManager ────────────────────────────────────────────────────────────

class ConfigManager:
    """Import, apply, export and diff VERA configuration resources.

    Parameters
    ----------
    project_root:
        Root of the VERA project.  All relative paths (middleware.json,
        policy.csv, .env) are resolved from here.  Defaults to the
        directory two levels above this file (the project root).
    """

    API_VERSION = API_VERSION

    def __init__(self, project_root: Optional[Path] = None) -> None:
        if project_root is None:
            project_root = Path(__file__).parent.parent
        self._root = Path(project_root).resolve()

    # ── Internal path helpers ────────────────────────────────────────────────

    def _mw_path(self) -> Path:
        return self._root / "data" / "middleware.json"

    def _policy_path(self) -> Path:
        env = os.getenv("VERA_CASBIN_POLICY")
        if env:
            return Path(env)
        return self._root / "data" / "casbin" / "policy.csv"

    def _env_path(self) -> Path:
        return self._root / ".env"

    # ── Export (current state → VeraResource) ───────────────────────────────

    def export_middleware(self) -> VeraResource:
        """Snapshot the current middleware chain."""
        from core.middleware_config import load, default_chain
        chain = load(str(self._mw_path())) or default_chain()
        return VeraResource(
            api_version=self.API_VERSION,
            kind="MiddlewareChain",
            metadata={"name": "default"},
            spec={"middlewares": chain},
        )

    def export_policy(self) -> VeraResource:
        """Snapshot Casbin policies and role assignments."""
        policies: list[dict] = []
        role_assignments: list[dict] = []

        path = self._policy_path()
        if path.exists():
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split(",")]
                if parts[0] == "p" and len(parts) >= 5:
                    policies.append({
                        "role":     parts[1],
                        "resource": parts[2],
                        "action":   parts[3],
                        "effect":   parts[4],
                    })
                elif parts[0] == "g" and len(parts) >= 3:
                    role_assignments.append({
                        "user":     parts[1],
                        "inherits": parts[2],
                    })

        return VeraResource(
            api_version=self.API_VERSION,
            kind="Policy",
            metadata={"name": "default"},
            spec={"policies": policies, "role_assignments": role_assignments},
        )

    def export_env(self) -> VeraResource:
        """Snapshot environment variables (redacted vars excluded)."""
        from interfaces.cli.commands.config import _VARS

        vars_out: dict[str, str] = {}
        for var, default, _ in _VARS:
            if var in _REDACTED_VARS:
                continue
            val = os.environ.get(var)
            vars_out[var] = val if val is not None else default

        return VeraResource(
            api_version=self.API_VERSION,
            kind="EnvConfig",
            metadata={"name": "default"},
            spec={"vars": vars_out},
        )

    def export_all(self, kinds: Optional[list[str]] = None) -> list[VeraResource]:
        """Export one or more resource kinds.  Defaults to all."""
        exporters: dict[str, Any] = {
            "MiddlewareChain": self.export_middleware,
            "Policy":          self.export_policy,
            "EnvConfig":       self.export_env,
        }
        targets = kinds if kinds else list(exporters)
        unknown = [k for k in targets if k not in exporters]
        if unknown:
            raise ValueError(f"Unknown kind(s): {unknown}.  Valid: {sorted(exporters)}")
        return [exporters[k]() for k in targets]

    # ── Apply (VeraResource → disk) ─────────────────────────────────────────

    def apply(self, resource: VeraResource) -> ApplyResult:
        """Apply a resource idempotently.  Returns what changed."""
        handlers = {
            "MiddlewareChain": self._apply_middleware,
            "Policy":          self._apply_policy,
            "EnvConfig":       self._apply_env,
        }
        handler = handlers.get(resource.kind)
        if handler is None:
            raise ValueError(f"Unknown kind: {resource.kind!r}")
        return handler(resource)

    def apply_all(self, resources: list[VeraResource]) -> list[ApplyResult]:
        return [self.apply(r) for r in resources]

    def _apply_middleware(self, resource: VeraResource) -> ApplyResult:
        from core.middleware_config import load, save, default_chain

        new_chain = resource.spec.get("middlewares", [])
        current   = load(str(self._mw_path())) or default_chain()
        changes   = _diff_list_of_dicts(current, new_chain, key="name")

        if not changes:
            return ApplyResult(resource.kind, resource.name, "unchanged")

        existed = self._mw_path().exists()
        save(new_chain, str(self._mw_path()))
        return ApplyResult(
            resource.kind, resource.name,
            "updated" if existed else "created",
            changes,
        )

    def _apply_policy(self, resource: VeraResource) -> ApplyResult:
        path = self._policy_path()
        current_text = path.read_text(encoding="utf-8") if path.exists() else ""

        lines: list[str] = []
        for p in resource.spec.get("policies", []):
            effect = p.get("effect", "allow")
            lines.append(f"p, {p['role']}, {p['resource']}, {p['action']}, {effect}")
        for r in resource.spec.get("role_assignments", []):
            lines.append(f"g, {r['user']}, {r['inherits']}")

        new_text = "\n".join(lines) + "\n" if lines else ""
        if new_text == current_text:
            return ApplyResult(resource.kind, resource.name, "unchanged")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_text, encoding="utf-8")
        return ApplyResult(
            resource.kind, resource.name,
            "updated" if current_text else "created",
            [f"Wrote {len(lines)} policy line(s)"],
        )

    def _apply_env(self, resource: VeraResource) -> ApplyResult:
        path = self._env_path()
        existing: dict[str, str] = {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    existing[k.strip()] = v.strip()

        new_vars = resource.spec.get("vars", {})
        changes: list[str] = []
        for k, v in new_vars.items():
            v_str = str(v)
            if existing.get(k) != v_str:
                old = existing.get(k, "<unset>")
                changes.append(f"{k}: {old!r} → {v_str!r}")
                existing[k] = v_str

        if not changes:
            return ApplyResult(resource.kind, resource.name, "unchanged")

        new_lines = [f"{k}={v}" for k, v in existing.items()]
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        return ApplyResult(
            resource.kind, resource.name,
            "updated" if path.exists() else "created",
            changes,
        )

    # ── Diff (file vs current state) ────────────────────────────────────────

    def diff(self, resource: VeraResource) -> list[str]:
        """Return human-readable diff lines for what *apply* would change.

        Lines are prefixed with ``[+]`` (added), ``[-]`` (removed), or
        ``[~]`` (changed).  An empty list means no changes.
        """
        exporters = {
            "MiddlewareChain": self.export_middleware,
            "Policy":          self.export_policy,
            "EnvConfig":       self.export_env,
        }
        exporter = exporters.get(resource.kind)
        if exporter is None:
            raise ValueError(f"Unknown kind: {resource.kind!r}")
        current = exporter()
        return _diff_specs(current.spec, resource.spec)

    def diff_all(self, resources: list[VeraResource]) -> dict[str, list[str]]:
        """Run diff for each resource; returns ``{kind/name: [lines]}``."""
        return {
            f"{r.kind}/{r.name}": self.diff(r)
            for r in resources
        }

    # ── YAML serialisation ──────────────────────────────────────────────────

    @staticmethod
    def to_yaml(resources: list[VeraResource]) -> str:
        """Serialise resources to a multi-document YAML string."""
        docs = [r.to_dict() for r in resources]
        return yaml.dump_all(
            docs,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )

    @staticmethod
    def from_yaml(text: str) -> list[VeraResource]:
        """Parse one or more YAML documents into VeraResource objects."""
        resources: list[VeraResource] = []
        for doc in yaml.safe_load_all(text):
            if doc is None:
                continue
            resources.append(VeraResource.from_dict(doc))
        return resources

    def load_file(self, path: Path) -> list[VeraResource]:
        """Load resources from a YAML file on disk."""
        return self.from_yaml(Path(path).read_text(encoding="utf-8"))


# ── Private diff utilities ───────────────────────────────────────────────────

def _diff_specs(current: dict, new: dict, prefix: str = "") -> list[str]:
    """Recursively diff two spec dicts; return annotated change lines."""
    lines: list[str] = []
    all_keys = sorted(set(current) | set(new))
    for key in all_keys:
        path = f"{prefix}{key}"
        if key not in current:
            lines.append(f"  [+] {path}: {new[key]!r}")
        elif key not in new:
            lines.append(f"  [-] {path}: {current[key]!r}")
        elif isinstance(current[key], dict) and isinstance(new[key], dict):
            lines.extend(_diff_specs(current[key], new[key], prefix=f"{path}."))
        elif isinstance(current[key], list) and isinstance(new[key], list):
            if current[key] != new[key]:
                lines.append(f"  [~] {path}: list changed ({len(current[key])} → {len(new[key])} items)")
        elif current[key] != new[key]:
            lines.append(f"  [~] {path}: {current[key]!r} → {new[key]!r}")
    return lines


def _diff_list_of_dicts(current: list[dict], new: list[dict], key: str) -> list[str]:
    """Diff two lists of dicts keyed on *key*; return change labels."""
    cur_map = {item[key]: item for item in current if key in item}
    new_map = {item[key]: item for item in new if key in item}
    changes: list[str] = []
    for k in sorted(set(cur_map) | set(new_map)):
        if k not in cur_map:
            changes.append(f"[+] {k}")
        elif k not in new_map:
            changes.append(f"[-] {k}")
        elif cur_map[k] != new_map[k]:
            changes.append(f"[~] {k}")
    return changes
