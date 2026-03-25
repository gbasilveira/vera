---
title: "API Server Reference"
description: "Built-in REST and WebSocket routes, auth flow, and how to start the server."
tags: [api, rest, websocket, server, routes, auth]
---

# API Server Reference

**Entry point:** `interfaces/api/main.py` — FastAPI application

Start with:

```bash
vera api serve                           # dev: localhost:8000
vera api serve --host 0.0.0.0 --port 9000
vera api serve --reload                  # hot-reload (development)
vera api serve --workers 4               # production
```

Interactive docs available at `http://host:port/vera/docs` once running.

---

## Authentication

All routes except `/health` and `POST /vera/auth/login` require a session token.

Pass it as a Bearer token:

```
Authorization: Bearer <session_token>
```

For WebSocket connections, use a query parameter (browsers can't set headers):

```
ws://host/vera/ws/my-namespace?token=<session_token>
```

---

## Built-in routes

### System

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | ✗ | Liveness probe |
| `GET` | `/vera/info` | ✓ | Kernel metadata, plugins, middleware |
| `GET` | `/vera/docs` | ✗ | Swagger UI |
| `GET` | `/vera/redoc` | ✗ | ReDoc UI |

### Auth

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/vera/auth/login` | ✗ | Authenticate, returns `session_token` |
| `POST` | `/vera/auth/logout` | ✓ | Revoke the current token |

**Login request:**
```json
{"provider": "local", "username": "alice", "password": "secret"}
```

**Login response:**
```json
{
  "session_token": "...",
  "user_id": "alice",
  "user_role": "owner",
  "expires_at": "2026-03-26T10:00:00",
  "provider": "local"
}
```

### Tools

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/vera/tools` | ✓ | List tools (`?plugin=name` to filter) |
| `POST` | `/vera/tools/{tool_name}` | ✓ | Execute tool through middleware chain |

**Tool execution:**
```bash
curl -X POST http://localhost:8000/vera/tools/llm.generate \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"text": "hello world"}'
```

### WebSocket

```
WS /vera/ws/{namespace}?token=<session_token>
```

Send JSON messages to execute tools:
```json
{"tool": "my_plugin.do_thing", "text": "hello"}
```

Receive results:
```json
{"tool": "my_plugin.do_thing", "result": "processed: hello", "error": null}
```

---

## Plugin routes

Plugins contribute routes via the extension system:

```yaml
# manifest.yaml
contributes:
  - point: interfaces.api.routes
    type: router
    params:
      prefix: /my-plugin
      handler: "plugins.my_plugin.api:router"
```

Routes are mounted automatically at startup.  Use `vera api routes` to inspect
what will be mounted before starting the server.

---

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `VERA_API_CORS_ORIGINS` | `*` | Comma-separated allowed origins |

---

## CLI

```bash
vera api serve [--host H] [--port P] [--reload] [--workers N]
vera api routes      # list all routes (built-in + plugin contributions)
```
