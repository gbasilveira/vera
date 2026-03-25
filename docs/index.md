---
title: "VERA — Overview"
description: "What VERA is and how its pieces fit together."
tags: [overview, architecture]
---

# VERA — Visible Edge Reasoning Architecture

VERA is a modular framework for building secure, observable AI-agent systems.
It provides a kernel that orchestrates plugins, a middleware chain that enforces
security and policy on every tool call, a CLI for operations, and a REST/WebSocket
API that plugins can extend without touching framework code.

## Core ideas

- **Everything is a tool.** Plugins expose async functions registered under a
  namespaced key (e.g. `llm.generate`, `gmail.send`). All execution goes
  through the kernel.
- **Middleware is the policy layer.** Auth, secrets injection, PII masking,
  retry, cost tracking, and audit happen automatically — plugins never see raw
  credentials or unmasked PII. This applies equally to CLI and API calls.
- **Extension points, not hard-wiring.** Plugins declare what they contribute
  (CLI commands, API routes, WebSocket namespaces, UI pages, dashboard widgets)
  in `manifest.yaml`. Hosts discover and wire them at startup with no code changes.
- **Decentralised documentation.** Every subsystem ships its own `docs/`
  directory. `vera docs` aggregates them all into one interactive tree.

## Top-level layout

```
vera/
├── core/          Kernel, deps, bus, VFS, secrets, security, observability,
│                  extension registry, config manager, API SDK
├── plugins/       First-party and user plugins (each is self-contained)
├── interfaces/
│   ├── cli/       Typer CLI — vera <command>
│   └── api/       FastAPI REST + WebSocket server — vera api serve
├── data/          Runtime state (VFS DB, audit logs, Casbin policies)
└── docs/          Project-level docs (this file)
```

## Quick navigation

| Area | Command |
|---|---|
| Getting started | `vera docs show quickstart` |
| Kernel reference | `vera docs show core/kernel` |
| Middleware chain | `vera docs show core/middleware/overview` |
| Extension system | `vera docs show core/extensions` |
| Plugin authoring | `vera docs show plugins/_template/authoring` |
| REST & WebSocket API | `vera docs show interfaces/api/reference` |
| API SDK for plugins | `vera docs show core/api` |
| Config import/export | `vera docs show core/config_manager` |
| CLI reference | `vera docs show interfaces/cli/reference` |
| Auth system | `vera docs show core/auth/overview` |

Run `vera docs` with no arguments to browse the full tree interactively.
