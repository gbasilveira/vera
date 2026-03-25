---
title: "CLI Reference"
description: "Complete reference for every vera command and subcommand."
tags: [cli, commands, reference, typer]
---

# CLI Reference

Entry point: `vera` (installed via `pip install -e .`)

All commands except `init`, `doctor`, `auth login`, and `api serve` require an
active session (`vera auth login` first).

---

## Top-level commands

### `vera status`
Show kernel health, loaded plugins, middleware chain, and today's audit summary.

### `vera init`
Bootstrap a new VERA instance: create `data/` directories, validate Casbin files.

### `vera doctor`
Run diagnostics: Python version, env vars, file checks, key imports.

### `vera run-tool <tool> [key=value ...]`
Shortcut to execute a tool through the full middleware chain.

```bash
vera run-tool llm.generate text="hello world"
vera run-tool llm.generate --json '{"text":"hello","temperature":0.5}'
```

---

## `vera api`

| Subcommand | Description |
|---|---|
| `serve [--host H] [--port P] [--reload] [--workers N]` | Start the REST & WebSocket server |
| `routes` | List all routes (built-in + plugin contributions) |

```bash
vera api serve                          # dev: localhost:8000
vera api serve --host 0.0.0.0 --port 9000
vera api serve --reload                 # hot-reload (development)
vera api serve --workers 4              # production multi-process
vera api routes                         # preview mounted routes before starting
```

Once running, docs are available at `http://host:port/vera/docs`.

---

## `vera auth`

| Subcommand | Description |
|---|---|
| `login` | Authenticate (prompts for username + password) |
| `logout` | Clear local session token |
| `whoami` | Show current user ID and all roles |
| `providers` | List registered auth providers |
| `add-user <name> <role>` | Create user and assign initial role (owner only) |
| `list-users` | List all users with their Casbin roles (owner only) |
| `update-role <name> <role>` | Replace all user roles with one new role (owner only) |
| `delete-user <name>` | Remove user + all Casbin assignments + sessions (owner only) |
| `change-password` | Change the current user's password |

---

## `vera plugin`

| Subcommand | Description |
|---|---|
| `list` | Discover all plugins (loaded + available) |
| `info <name>` | Show full manifest including extension points and contributions |
| `new <name>` | Scaffold from `_template` |
| `verify <path>` | Run SDK contract tests |
| `load <name>` | Load plugin into running kernel |
| `unload <name>` | Unload non-core plugin |

`vera plugin info` displays the `extension_points` and `contributes` sections
from the manifest so you can see what a plugin exposes and where it hooks in.

---

## `vera middleware`

| Subcommand | Description |
|---|---|
| `list` | Show configured + discovered middleware |
| `init [--force]` | Create `data/middleware.json` with defaults |
| `enable <name> [--order N] [--class MODULE.CLASS]` | Add / re-enable |
| `disable <name>` | Disable (keep in config) |
| `set-order <name> <order>` | Change execution order |
| `info <name>` | Show details |

---

## `vera tool`

| Subcommand | Description |
|---|---|
| `list [--plugin NAME]` | List all registered tools |
| `info <name>` | Show signature, params, and docstring |
| `run <name> [key=value ...]` | Execute through middleware |

---

## `vera secrets`

| Subcommand | Description |
|---|---|
| `set <key> <value>` | Store a secret |
| `get <key>` | Retrieve a secret |
| `delete <key>` | Remove a secret |
| `list [--prefix P]` | List keys |

---

## `vera policy`

### Permission management

| Subcommand | Description |
|---|---|
| `define-permission <name> <obj> [action]` | Register a named permission (owner only) |
| `list-permissions` | Show all defined named permissions |
| `grant <role> <permission>` | Grant a permission to a role (owner only) |
| `revoke-permission <role> <permission>` | Revoke a permission from a role (owner only) |

### Role assignment

| Subcommand | Description |
|---|---|
| `assign-role <user_id> <role>` | Assign a role to a user (owner only) |
| `revoke-role <user_id> <role>` | Revoke a role from a user (owner only) |

### Inspection & advanced

| Subcommand | Description |
|---|---|
| `list` | Full state: named permissions + raw policies + role/user grants |
| `test <subject> <tool> [action]` | Dry-run check; subject can be a user ID or role name |
| `add <subject> <pattern> <action>` | Raw Casbin policy rule (advanced, owner only) |
| `remove <subject> <pattern> <action>` | Remove raw policy rule (advanced, owner only) |

`test` resolves the full chain — pass a user ID to check all their roles transitively:

```bash
vera policy test johndow agent.run_task execute    # resolves johndow → roles → perms
vera policy test manager llm.generate              # check role name directly
```

---

## `vera logs`

| Subcommand | Description |
|---|---|
| `audit [--date] [--user] [--status]` | View audit log |
| `costs [--user] [--date] [--by-tool]` | View cost aggregation |

---

## `vera memory`

| Subcommand | Description |
|---|---|
| `store <namespace> <content>` | Save a memory chunk |
| `retrieve <namespace> <query>` | Similarity search |
| `forget [--namespace NS] [--chunks ID ...]` | Delete memories |

---

## `vera config`

| Subcommand | Description |
|---|---|
| `show` | Display all settings with current values and defaults |
| `set <VAR> <value>` | Write a variable to `.env` |
| `export [--kind K] [-o file.yaml]` | Export current config as YAML resource(s) |
| `apply -f file.yaml [--dry-run]` | Apply a YAML resource file (idempotent) |
| `diff -f file.yaml` | Show what would change if a file were applied |
| `validate -f file.yaml` | Validate YAML structure without applying |

### Resource kinds

| Kind | Backed by | Contents |
|---|---|---|
| `MiddlewareChain` | `data/middleware.json` | Ordered middleware layers |
| `Policy` | `data/casbin/policy.csv` | RBAC policies + role assignments |
| `EnvConfig` | `.env` | Environment variables (secrets excluded) |

### Example workflow

```bash
vera config export -o infra/baseline.yaml
vera config diff   -f infra/baseline.yaml
vera config apply  -f infra/baseline.yaml
vera config apply  -f infra/prod-full.yaml   # multiple resources with ---
```

---

## `vera ext`

| Subcommand | Description |
|---|---|
| `points` | List all registered extension points with contribution counts |
| `contributions [--point P] [--plugin P]` | List contributions, optionally filtered |
| `show <point-id>` | Full detail: schema, all contributions, import paths |

### Built-in extension points

| ID | Type | Purpose |
|---|---|---|
| `interfaces.cli.commands` | `command_group` | Typer app added to `vera` |
| `interfaces.api.routes` | `router` | VeraRouter mounted in the API server |
| `interfaces.api.websocket` | `ws_namespace` | WebSocket namespace declaration |
| `interfaces.webui.pages` | `page` | Future WebUI page |
| `interfaces.webui.nav` | `nav_item` | Future WebUI navigation entry |
| `interfaces.webui.widgets` | `widget` | Future WebUI widget |
| `core.middleware.chain` | `middleware` | Extra middleware layer |

---

## `vera docs`

| Subcommand | Description |
|---|---|
| *(no subcommand)* | Interactive tree browser |
| `list [--source S]` | Flat list of all docs |
| `show <path>` | Render a doc (Markdown) |
| `search <query>` | Search by title, tags, description, path |

Docs are discovered from every `docs/` directory in the project tree — core,
plugins, interfaces — no registration needed.
