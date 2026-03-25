---
title: "ConfigManager — Import / Apply / Export"
description: "kubectl-style YAML resource system for exporting and applying VERA configuration."
tags: [config, yaml, import, export, apply, diff, resources]
---

# ConfigManager — Import / Apply / Export

**File:** `core/config_manager.py`

Inspired by `kubectl`, VERA configuration is expressed as typed **resources**
serialised to YAML.  Resources can be exported from a live installation,
edited, diffed, and re-applied — enabling GitOps workflows and reproducible
environments.

## Resource structure

```yaml
apiVersion: vera/v1
kind: MiddlewareChain        # MiddlewareChain | Policy | EnvConfig
metadata:
  name: production
  description: "optional human note"
spec:
  # kind-specific payload
```

Multiple resources can live in one file separated by `---`.

## Supported kinds

### MiddlewareChain

Maps to `data/middleware.json`.

```yaml
apiVersion: vera/v1
kind: MiddlewareChain
metadata:
  name: default
spec:
  middlewares:
    - name: auth_guard
      class: core.middleware.auth.AuthGuardMiddleware
      order: 10
      enabled: true
    - name: retry
      class: core.middleware.retry.RetryMiddleware
      order: 40
      enabled: true
```

### Policy

Maps to `data/casbin/policy.csv`.

```yaml
apiVersion: vera/v1
kind: Policy
metadata:
  name: default-rbac
spec:
  policies:
    - role: owner
      resource: "*"
      action: execute
      effect: allow
    - role: intern
      resource: "llm.*"
      action: execute
      effect: allow
  role_assignments:
    - user: manager
      inherits: intern
```

### EnvConfig

Maps to `.env`.  `VERA_MASTER_KEY` is intentionally excluded from export.

```yaml
apiVersion: vera/v1
kind: EnvConfig
metadata:
  name: default
spec:
  vars:
    VERA_LLM_PROVIDER: openai
    VERA_LLM_MODEL: gpt-4o
    VERA_BUS_BACKEND: blinker
```

## ConfigManager API

```python
from core.config_manager import ConfigManager

mgr = ConfigManager()

# Export current state
resources = mgr.export_all()                          # all kinds
resources = mgr.export_all(["MiddlewareChain"])       # specific kinds
yaml_text = ConfigManager.to_yaml(resources)

# Load from file
resources = mgr.load_file(Path("infra/prod.yaml"))

# Diff (what would change)
diff_lines = mgr.diff(resources[0])                   # list of annotated strings

# Apply (idempotent)
result = mgr.apply(resources[0])
print(result.status)   # "created" | "updated" | "unchanged"
print(result.changes)  # list[str] of human-readable changes

# Apply multiple
results = mgr.apply_all(resources)
```

## ApplyResult

```python
@dataclass
class ApplyResult:
    kind:    str
    name:    str
    status:  str          # "created" | "updated" | "unchanged"
    changes: list[str]
    changed: bool         # property — True unless unchanged
```

## Diff format

Lines are prefixed with:

- `[+]` — field / entry added
- `[-]` — field / entry removed
- `[~]` — field / entry changed

## CLI

```bash
vera config export                                  # print all as YAML
vera config export --kind MiddlewareChain -o mw.yaml
vera config apply  -f infra/prod.yaml
vera config apply  -f infra/prod.yaml --dry-run
vera config diff   -f infra/prod.yaml
vera config validate -f infra/prod.yaml
```
