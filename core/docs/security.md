---
title: "SecurityManager — Permission-Centric RBAC"
description: "Casbin-based authorization with named permissions, multiple roles per user, and plugin-declared capabilities."
tags: [security, rbac, casbin, permissions, roles, policy]
---

# SecurityManager — Permission-Centric RBAC

**File:** `core/security.py`

Wraps PyCasbin to provide authorization. Every tool call is checked before
execution (`AuthGuardMiddleware` at order=10). The model has three layers:

```
permission  →  object pattern + action   (what a capability means)
role        →  set of permissions        (what a role grants)
user        →  set of roles              (who the user is)
```

Access is granted when **any** of the user's roles holds a permission that
allows the requested action, and **no** role explicitly denies it.

---

## Named permissions

Permissions are first-class. Each one maps to a Casbin subject named
`perm:<namespace>:<capability>` with one or more policy rules:

```
p, perm:llm:generate,  llm.*,  execute, allow
p, perm:agent:edit,    agent.*, write,   allow
p, perm:sys:all,       *,      *,       allow   # owner super-permission
```

### Register a permission (runtime)

```python
security.register_permission("perm:gmail:send", "gmail.*", "execute")
```

Idempotent — safe to call multiple times. Plugins call this in their
`register_tools()` hook (or it is called automatically from
`permissions.provides` in the manifest).

### Grant / revoke a permission from a role

```python
security.grant_permission_to_role("manager", "perm:gmail:send")
security.revoke_permission_from_role("manager", "perm:gmail:send")
```

### Inspect

```python
security.get_permissions_for_role("manager")
# → ["perm:llm:generate", "perm:memory:read", "perm:gmail:all", ...]

security.get_all_permissions()
# → [{"name": "perm:llm:generate", "obj": "llm.*", "action": "execute", "effect": "allow"}, ...]
```

---

## Built-in roles

| Role | Granted permissions |
|---|---|
| `owner` | `perm:sys:all` (wildcard — any object, any action) + all sys permissions |
| `manager` | `perm:llm:generate`, `perm:memory:read`, `perm:memory:autostore`, `perm:gmail:all`, `perm:agent:run` |
| `agent_editor` | `perm:agent:run`, `perm:agent:edit`, `perm:llm:generate`, `perm:memory:read` |
| `intern` | `perm:memory:read` |
| `guest` | *(none)* |

Roles have no automatic hierarchy — each role's permissions are explicit grants.
Users can hold **multiple roles** simultaneously.

---

## Role management

```python
security.assign_role("johndow", "manager")
security.assign_role("johndow", "agent_editor")   # multi-role
security.revoke_role("johndow", "manager")
security.get_roles_for_user("johndow")             # → ["agent_editor"]
security.get_users_for_role("manager")             # → ["alice", ...]
```

---

## Enforcement

```python
# By role name (used in middleware when user_roles list is available)
security.enforce("manager", "gmail.send", "execute")    # → True
security.enforce("agent_editor", "gmail.send", "execute")  # → False

# By user_id (resolves full user → role → permission chain)
security.enforce("johndow", "agent.run_task", "execute")  # → True

# Multi-role helper (any role grants = True)
security.enforce_any(["intern", "agent_editor"], "agent.run_task", "execute")  # → True
```

Object patterns use `keyMatch2` wildcards. Action also supports wildcards
(both `llm.*` and `*` for actions work in the matcher).

---

## Explicit deny

Add a deny directly on a role to override any allow:

```python
security.add_policy("manager", "restricted_tool.run", "execute", "deny")
```

Deny-wins: if any policy for the request resolves to `deny`, access is blocked
regardless of other allows.

---

## Raw policy management

```python
security.add_policy(subject, obj, action, effect="allow")
security.remove_policy(subject, obj, action, effect="allow")
security.reload_policy()    # hot-reload from data/casbin/policy.csv
```

---

## Casbin files

| File | Purpose |
|---|---|
| `data/casbin/rbac_model.conf` | Model — `g` DAG + `keyMatch2` on obj and action |
| `data/casbin/policy.csv` | `p` lines = permission rules; `g` lines = role grants + user assignments |

---

## CLI

```bash
vera policy define-permission perm:gmail:send "gmail.*" execute
vera policy grant manager perm:gmail:send
vera policy revoke-permission manager perm:gmail:send
vera policy assign-role johndow agent_editor
vera policy revoke-role johndow agent_editor
vera policy list                          # three tables: permissions / raw / grants
vera policy test johndow agent.run_task   # resolves full chain
```
