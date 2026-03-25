---
title: "SecretsManager"
description: "Secure storage for API keys and credentials with keyring and SQLite backends."
tags: [secrets, credentials, keyring, security]
---

# SecretsManager

**File:** `core/secrets.py`

Provides a uniform async API for storing and retrieving secrets.  Plugins
declare required secrets in their manifest; `SecretsInjectorMiddleware`
retrieves them automatically before each tool call.

## API

```python
await secrets.set("llm_driver.openai_api_key", "sk-...")
value = await secrets.get("llm_driver.openai_api_key")         # raises SecretNotFound
value = await secrets.get_optional("llm_driver.openai_api_key")  # returns None
await secrets.delete("llm_driver.openai_api_key")
keys  = await secrets.list_keys("llm_driver.")
```

## Key naming convention

`<plugin_name>.<secret_name>` — e.g. `gmail.oauth_token`, `llm_driver.openai_api_key`

## Backends

| Backend | Env var | Notes |
|---|---|---|
| `keyring` | `VERA_SECRETS_BACKEND=keyring` | OS keychain (default) |
| `sqlite` | `VERA_SECRETS_BACKEND=sqlite` | Encrypted with `VERA_MASTER_KEY` |

## Declaring required secrets in a plugin

```yaml
# manifest.yaml
storage:
  secrets_required:
    - openai_api_key
    - slack_webhook
```

`SecretsInjectorMiddleware` will look these up as
`<plugin_name>.<secret_name>` and inject them into `ctx.injected_secrets`
before calling the tool.  If a secret is missing the call is rejected.
