---
title: "Quickstart"
description: "Install, initialise, and run your first tool in five minutes."
tags: [quickstart, install, setup]
---

# Quickstart

## 1 — Install

```bash
pip install -e .        # from the project root
vera doctor             # check prerequisites
```

## 2 — Initialise

```bash
vera init               # creates data/ directories and validates Casbin files
```

## 3 — Create the first user

```bash
vera auth add-user admin owner
vera auth login         # enter username + password
```

## 4 — Check status

```bash
vera status             # loaded plugins, middleware chain, audit summary
```

## 5 — Run a tool via CLI

```bash
vera tool list                          # see all registered tools
vera tool run llm.generate text="hi"    # execute through the full middleware chain
```

## 6 — Start the REST & WebSocket API

```bash
vera api serve                          # http://localhost:8000
vera api serve --reload                 # hot-reload for development
```

Once running:

```bash
# Obtain a session token
curl -s -X POST http://localhost:8000/vera/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<pw>","provider":"local"}' \
  | jq .session_token

# Call a tool over HTTP
curl -X POST http://localhost:8000/vera/tools/llm.generate \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"text":"hello"}'

# Browse auto-generated docs
open http://localhost:8000/vera/docs
```

Connect a WebSocket client:
```
ws://localhost:8000/vera/ws/my-namespace?token=<session_token>
```

Send `{"tool": "llm.generate", "text": "hi"}`, receive `{"tool": "...", "result": "..."}`.

## 7 — Browse documentation

```bash
vera docs                               # interactive tree browser
vera docs show core/kernel              # read a specific doc
vera docs search websocket              # search across all docs
```

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `VERA_LLM_PROVIDER` | `ollama` | LLM backend |
| `VERA_LLM_MODEL` | `llama3` | Model name |
| `VERA_BUS_BACKEND` | `blinker` | Event bus |
| `VERA_VFS_BACKEND` | `local` | KV store |
| `VERA_SECRETS_BACKEND` | `keyring` | Secrets backend |
| `VERA_PLUGINS_DIR` | `plugins` | Plugin discovery root |
| `VERA_VFS_PATH` | `data/vera_vfs.db` | SQLite path for LocalFS |
| `VERA_API_CORS_ORIGINS` | `*` | Allowed CORS origins for the API server |

Copy `.env.example` to `.env` and adjust as needed.
