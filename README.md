```markdown
# VERA — Visible Edge Reasoning Architecture

**The secure, observable kernel for production-grade AI agents.**

[![License](https://img.shields.io/badge/license-AGPL_3.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org)
[![Stars](https://img.shields.io/github/stars/gbasilveira/vera.svg?style=social)](https://github.com/gbasilveira/vera)

> **"Build agents that are powerful, auditable, and controllable — not black boxes."**

## Why VERA?

In 2026, building AI agents is easy.  
Building **production-ready**, **secure**, and **observable** agents is still hard.

Most frameworks give you orchestration or nice UIs — but leave security, secrets management, audit trails, permissions, and operational control as an afterthought.

**VERA flips that.**

It is a **lightweight, code-first kernel** that enforces policy on *every* tool call through a strict middleware pipeline, while giving plugins and developers full extensibility.

### What Makes VERA Different

- **Non-bypassable Security Middleware Chain**  
  Every tool call (CLI or API) flows through:  
  **AuthGuard → Secrets Injection → PII Masking → Retry → Execution → Cost Recording → Audit**  
  Secrets never touch the payload. PII is automatically masked for external calls. Audit logs never contain raw data.

- **Deep Casbin-based RBAC**  
  Multi-role support per user, named permissions (`perm:gmail:send`), explicit deny rules, and fine-grained control. Roles are enriched automatically on login.

- **Manifest-Driven Plugin System**  
  Plugins declare tools, required secrets, retry policies, permissions, and contributions (CLI commands, REST routes, WebSockets) in `manifest.yaml`.  
  No core forking needed — true decentralized ecosystem.

- **GitOps-Ready Configuration**  
  Export, diff, validate, and apply middleware chains, policies, and env config as clean YAML (kubectl-style).

- **Unified Runtime Experience**  
  Same `VeraDeps` object and full middleware pipeline whether you call tools from CLI, REST, or WebSocket.

- **Built-in Observability & State**  
  OpenTelemetry tracing, Prometheus metrics, structured audit + cost logs, and a virtual KV store (LocalFS SQLite or RedisFS).

- **Local-First by Default, Production-Ready**  
  No external services required for development. Swap to Redis for multi-process/multi-tenant deployments.

While **Dify** excels at visual workflows, **LangGraph** at complex state machines, and **Agentgateway/ContextForge** at protocol-level connectivity, **VERA** is the **secure, ops-friendly kernel** you run *underneath* your agents.

## What Can You Build with VERA?

- Secure internal company agents (with strict role-based access)
- Multi-tenant SaaS agent platforms
- Regulated-industry agents (finance, legal, healthcare) needing audit & PII controls
- Personal AI assistants with memory, email, calendar, browsing, etc.
- Vertical agent ecosystems where community plugins plug in safely

## Quickstart (5 minutes)

```bash
# 1. Install (using uv)
uv sync
source .venv/bin/activate

# 2. Initialise
vera init

# 3. Create admin user & login
vera auth add-user admin owner
vera auth login

# 4. Run your first tool
vera tool run llm.generate text="Hello from VERA!"

# 5. Start the API server
vera api serve
```

Open http://localhost:8000/vera/docs for interactive Swagger.

Full quickstart → [`docs/quickstart.md`](docs/quickstart.md)

## Key Features

- **VeraKernel** — Plugin loader, tool registry, execution engine
- **Middleware System** — Extensible ordered pipeline (add rate limiting, quotas, validation, circuit breakers easily)
- **VeraFileSystem (VFS)** — Persistent + TTL-aware KV store (SQLite or Redis)
- **SecretsManager** — Keyring or encrypted SQLite backend
- **Auth & Security** — Local provider + Casbin RBAC
- **Extension Points** — Plugins can contribute CLI commands, API routes, WebSocket namespaces, and more
- **CLI Power Tools** — `vera policy`, `vera config apply`, `vera logs`, `vera ext`, `vera docs`, etc.
- **Observability** — OTel tracing + Prometheus metrics wired to the event bus

## Project Structure

```
vera/
├── core/          # Kernel, middleware, deps, bus, vfs, security, etc.
├── plugins/       # First-party & community plugins (llm_driver, memory_rag, ...)
├── interfaces/
│   ├── cli/       # `vera` command
│   └── api/       # FastAPI REST + WebSocket server
├── data/          # Runtime state (VFS DB, audit logs, Casbin policy)
└── docs/          # Decentralized documentation
```

## Who is VERA for?

- **Developers & Teams** who want code-first control without reinventing security and ops plumbing
- **Enterprises & Regulated Organizations** needing strong audit, permissions, and PII protection
- **Plugin Authors** who want to publish secure, reusable tools that integrate cleanly
- **Anyone tired** of bolting security onto LangGraph or Dify after the fact

## Comparison (2026 Landscape)

| Framework          | Visual Builder | Stateful Orchestration | Security Middleware | GitOps Config | Plugin Extensibility | Best For                     |
|--------------------|----------------|------------------------|----------------------------|---------------|----------------------|------------------------------|
| **VERA**           | **No**         | **Via plugins**        | **Mandatory chain**| **Yes**       | **Manifest-driven**      | **Secure production kernels**    |
| Dify               | Yes            | Good                   | Basic                      | Partial       | Marketplace          | Rapid prototyping & teams    |
| LangGraph          | No             | Excellent              | You build it               | No            | Good                 | Complex agent workflows      |
| Agentgateway       | No             | No                     | Excellent (gateway)        | Partial       | Protocol-focused     | MCP/A2A connectivity         |
| Semantic Kernel    | No             | Good                   | Enterprise (Azure)         | Partial       | Skills/plugins       | .NET & Microsoft ecosystems  |

## Roadmap Highlights

- Redis-backed VFS & Bus for horizontal scaling
- More first-party plugins (Gmail, Calendar, Browser, Code Interpreter)
- WebUI dashboard (with plugin-contributed widgets)
- Rate limiting, quota, and consent middleware
- MCP / A2A gateway integration

## Contributing

We welcome contributions! See [`CONTRIBUTING.md`](CONTRIBUTING.md) and the [Plugin Authoring Guide](plugins/_template/docs/authoring.md).

Key ways to help:
- Write new plugins
- Add middleware layers
- Improve documentation
- Test in real multi-tenant scenarios

## License

This repository (the core kernel and core plugins) is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).

**Note on Plugins:** 
External plugins developed by users that interface with VERA are not considered part of the core project. As such, they are not governed by the AGPL and you are free to license your external plugins however you wish.

---

**VERA — Making the edge of AI reasoning visible, secure, and controllable.**

Ready to build the next generation of trustworthy agents?

→ [`Quickstart`](docs/quickstart.md) | [`Core Concepts`](docs/index.md) | [`vera docs`](https://github.com/gbasilveira/vera#running-the-docs-browser)
```