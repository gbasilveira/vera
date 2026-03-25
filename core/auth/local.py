"""
LocalAuthProvider — username + password authentication backed by SQLite.

Passwords are hashed with PBKDF2-HMAC-SHA256 (260 000 iterations).
Sessions are created by the AuthManager after a successful authenticate().

This is the built-in provider for single-server / development deployments.
For production multi-tenant setups, build an auth plugin (OAuth, LDAP, etc.)
that implements VeraAuthProvider and registers itself via register_auth_providers().

Role storage note:
    The users table keeps a `role` column for display and migration purposes.
    Authorization is enforced via Casbin (managed by SecurityManager), not this
    column.  On authenticate(), user_role is set to the DB value so AuthManager
    can auto-migrate it to Casbin on first login if no Casbin roles exist yet.
"""
from __future__ import annotations

import hashlib
import os
import secrets as _secrets
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

import aiosqlite

from core.auth.base import (
    AuthResult,
    AuthenticationFailed,
    UserAlreadyExists,
    UserNotFound,
    VeraAuthProvider,
)

if TYPE_CHECKING:
    from core.secrets import SecretsManager
    from core.vfs.base import VeraFileSystem

_DEFAULT_DB = "data/vera_auth.db"
_ITERATIONS = 260_000


# ── Password hashing ──────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    salt = _secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), _ITERATIONS
    )
    return f"pbkdf2:sha256:{_ITERATIONS}:{salt}:{dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    try:
        _, alg, iters, salt, hashed = stored.split(":", 4)
        dk = hashlib.pbkdf2_hmac(
            alg, password.encode("utf-8"), salt.encode("utf-8"), int(iters)
        )
        return _secrets.compare_digest(dk.hex(), hashed)
    except Exception:
        return False


# ── User registry ─────────────────────────────────────────────────────────────

class UserRegistry:
    """
    SQLite-backed user store: user_id, hashed password, role (display/migration), created_at.

    The `role` column is kept for display and migration; Casbin is the source
    of truth for authorization.
    """

    _TABLE = "users"

    def __init__(self, db_path: str = _DEFAULT_DB) -> None:
        self._db_path = db_path

    async def setup(self) -> None:
        """Create the users table if it does not already exist."""
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(f"""
                CREATE TABLE IF NOT EXISTS {self._TABLE} (
                    user_id       TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    role          TEXT NOT NULL DEFAULT '',
                    created_at    TEXT NOT NULL
                )
            """)
            await db.commit()

    async def add_user(self, user_id: str, password: str, role: str = "") -> None:
        """
        Create a user record.  `role` is stored for display / migration but
        not used for authorization — assign roles via SecurityManager instead.
        """
        if await self.get_user(user_id):
            raise UserAlreadyExists(f"User '{user_id}' already exists.")
        pw_hash = _hash_password(password)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                f"INSERT INTO {self._TABLE} (user_id, password_hash, role, created_at)"
                " VALUES (?, ?, ?, ?)",
                (user_id, pw_hash, role, datetime.utcnow().isoformat()),
            )
            await db.commit()

    async def verify_password(self, user_id: str, password: str) -> bool:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                f"SELECT password_hash FROM {self._TABLE} WHERE user_id = ?", (user_id,)
            ) as cur:
                row = await cur.fetchone()
        return bool(row and _verify_password(password, row[0]))

    async def get_user(self, user_id: str) -> Optional[dict]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                f"SELECT user_id, role, created_at FROM {self._TABLE} WHERE user_id = ?",
                (user_id,),
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return None
        return {"user_id": row[0], "role": row[1], "created_at": row[2]}

    async def list_users(self) -> list[dict]:
        async with aiosqlite.connect(self._db_path) as db:
            async with db.execute(
                f"SELECT user_id, role, created_at FROM {self._TABLE} ORDER BY user_id"
            ) as cur:
                rows = await cur.fetchall()
        return [{"user_id": r[0], "role": r[1], "created_at": r[2]} for r in rows]

    async def delete_user(self, user_id: str) -> None:
        if not await self.get_user(user_id):
            raise UserNotFound(f"User '{user_id}' not found.")
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                f"DELETE FROM {self._TABLE} WHERE user_id = ?", (user_id,)
            )
            await db.commit()

    async def change_password(self, user_id: str, old_password: str, new_password: str) -> None:
        if not await self.verify_password(user_id, old_password):
            raise AuthenticationFailed("Current password is incorrect.")
        pw_hash = _hash_password(new_password)
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                f"UPDATE {self._TABLE} SET password_hash = ? WHERE user_id = ?",
                (pw_hash, user_id),
            )
            await db.commit()

    async def update_role(self, user_id: str, role: str) -> None:
        """Update the display role column. Does NOT change Casbin assignments."""
        if not await self.get_user(user_id):
            raise UserNotFound(f"User '{user_id}' not found.")
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                f"UPDATE {self._TABLE} SET role = ? WHERE user_id = ?", (role, user_id)
            )
            await db.commit()


# ── Provider ──────────────────────────────────────────────────────────────────

class LocalAuthProvider(VeraAuthProvider):
    """
    Built-in username/password auth provider.

    Expected credentials dict:
        {"username": str, "password": str}

    Session TTL is 8 hours by default; override via session_ttl_hours.
    """

    name = "local"

    def __init__(
        self,
        db_path: str = _DEFAULT_DB,
        session_ttl_hours: int = 8,
    ) -> None:
        self._registry = UserRegistry(db_path)
        self._session_ttl_hours = session_ttl_hours

    @property
    def registry(self) -> UserRegistry:
        """Direct access to the UserRegistry for admin operations."""
        return self._registry

    async def setup(self, vfs: "VeraFileSystem", secrets: "SecretsManager") -> None:
        await self._registry.setup()

    async def authenticate(self, credentials: dict) -> AuthResult:
        username = credentials.get("username") or credentials.get("user_id", "")
        password = credentials.get("password", "")

        user = await self._registry.get_user(username)
        if not user or not await self._registry.verify_password(username, password):
            raise AuthenticationFailed("Invalid username or password.")

        token = _secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=self._session_ttl_hours)

        return AuthResult(
            user_id=user["user_id"],
            user_role=user["role"],   # DB column — AuthManager enriches user_roles from Casbin
            user_roles=[],
            session_token=token,
            expires_at=expires_at,
            provider=self.name,
        )
