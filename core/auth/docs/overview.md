---
title: "Auth System — Overview"
description: "Authentication manager, providers, session lifecycle, and role enrichment from Casbin."
tags: [auth, login, session, providers, roles]
---

# Auth System — Overview

**Directory:** `core/auth/`

## Components

| File | Purpose |
|---|---|
| `manager.py` | `AuthManager` — provider registry, session issuance, role enrichment |
| `base.py` | `VeraAuthProvider` ABC, `AuthResult`, `SessionInfo` |
| `local.py` | `LocalAuthProvider` — username/password (built-in) |
| `session.py` | VFS-backed session token storage and validation |

---

## AuthManager

`AuthManager` is constructed with the `SecurityManager` so it can enrich
sessions with Casbin roles after every login:

```python
auth_manager = AuthManager(vfs, security=security)
auth_manager.register_provider(LocalAuthProvider())
await auth_manager.setup(secrets)
```

On every `authenticate()` call:
1. The provider verifies credentials and returns an `AuthResult` with an empty
   `user_roles` list (and the DB role in the `user_role` hint field).
2. `AuthManager` looks up the user's Casbin roles via
   `security.get_roles_for_user(user_id)`.
3. If Casbin has no roles yet (first login / migration from old schema), it
   **auto-migrates**: assigns the DB `role` column value to Casbin and uses it.
4. The session is saved with the populated `user_roles` list.

Plugins can register custom providers in `register_auth_providers(auth_manager)`.

---

## AuthResult & SessionInfo

Both carry `user_roles: list[str]` (authoritative, from Casbin) and a
`user_role: str` hint (from the provider, kept for display and migration):

```python
@dataclass
class AuthResult:
    user_id:       str
    session_token: str
    expires_at:    datetime
    provider:      str
    user_roles:    list[str]   # authoritative — populated by AuthManager
    user_role:     str         # provider hint (DB column) — migration fallback

    @property
    def primary_role(self) -> str:
        """First role or 'guest'. For display only."""
```

`SessionInfo` has the same structure and is returned by `verify_session()`.

---

## VeraAuthProvider ABC

```python
class MyAuthProvider(VeraAuthProvider):
    name = "my_provider"

    async def authenticate(self, credentials: dict) -> AuthResult:
        # Verify identity, return AuthResult with user_roles=[]
        # AuthManager enriches user_roles from Casbin after this call.
        return AuthResult(
            user_id=user_id,
            user_role=db_role,   # hint for migration; AuthManager overrides
            user_roles=[],
            session_token=token,
            expires_at=expires_at,
            provider=self.name,
        )
```

---

## Session lifecycle

1. `vera auth login` → `AuthManager.authenticate()` → `AuthResult` with `user_roles`
2. Token saved to `~/.config/vera/session.json` (mode 0o600) with `user_roles` list
3. Every CLI command calls `require_session()` which loads and validates the token
4. `vera auth logout` → deletes `session.json`

Session JSON format:

```json
{
  "session_token": "...",
  "user_id": "johndow",
  "user_roles": ["admin", "agent_editor"],
  "user_role": "admin",
  "expires_at": "2026-03-25T18:00:00",
  "provider": "local"
}
```

Old sessions that only contain `user_role` are transparently upgraded to
`user_roles: [user_role]` on read.

---

## CLI

```bash
vera auth login                         # prompt for username + password
vera auth logout
vera auth whoami                        # shows all roles
vera auth providers                     # list registered providers
vera auth add-user bob manager          # creates user + assigns role in Casbin
vera auth list-users                    # shows Casbin roles per user (owner only)
vera auth update-role bob agent_editor  # replaces all Casbin roles (owner only)
vera auth delete-user bob               # removes user + all Casbin assignments
```

For fine-grained multi-role control use `vera policy assign-role` /
`vera policy revoke-role` instead of `update-role`.
