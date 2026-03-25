"""
SecretsManager — API key storage with two backends.

Backend 1: OS keyring (primary, recommended for dev/prod)
Backend 2: AES-256 encrypted SQLite (fallback for servers without keyring)

Key naming convention: plugin_name.secret_name
  e.g. gmail.oauth_token, llm_driver.openai_api_key

Plugins MUST use ctx.deps.secrets.get('plugin.key') — never os.environ directly.
"""
import json
import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

from core.middleware.base import SecretNotFound


class SecretsManager:
    """
    Unified secrets API. Backend is transparent to callers.
    """

    def __init__(self, backend: Optional[str] = None):
        self._backend = backend or os.getenv("VERA_SECRETS_BACKEND", "keyring")
        self._fernet: Optional[Fernet] = None
        self._sqlite_path = "data/secrets.db"

    # ── Public API ─────────────────────────────────────────────────────────

    async def get(self, key: str) -> str:
        """Return secret value. Raises SecretNotFound if missing."""
        value = await self._get(key)
        if value is None:
            raise SecretNotFound(f"Secret not found: '{key}'. Set it with: vera secrets set {key} <value>")
        return value

    async def get_optional(self, key: str) -> Optional[str]:
        """Return secret value or None if missing (no exception)."""
        return await self._get(key)

    async def set(self, key: str, value: str) -> None:
        """Store a secret."""
        if self._backend == "keyring":
            await self._keyring_set(key, value)
        else:
            await self._sqlite_set(key, value)

    async def delete(self, key: str) -> None:
        """Delete a secret. No-op if missing."""
        if self._backend == "keyring":
            await self._keyring_delete(key)
        else:
            await self._sqlite_delete(key)

    async def list_keys(self, prefix: str = "") -> list[str]:
        """List all secret keys with the given prefix."""
        if self._backend == "keyring":
            return await self._keyring_list(prefix)
        else:
            return await self._sqlite_list(prefix)

    # ── Keyring backend ────────────────────────────────────────────────────

    async def _get(self, key: str) -> Optional[str]:
        if self._backend == "keyring":
            return await self._keyring_get(key)
        else:
            return await self._sqlite_get(key)

    async def _keyring_get(self, key: str) -> Optional[str]:
        import keyring
        return keyring.get_password("vera", key)

    async def _keyring_set(self, key: str, value: str) -> None:
        import keyring
        keyring.set_password("vera", key, value)

    async def _keyring_delete(self, key: str) -> None:
        import keyring
        try:
            keyring.delete_password("vera", key)
        except Exception:
            pass

    async def _keyring_list(self, prefix: str) -> list[str]:
        # keyring has no list API — return empty list (limitation of keyring backend)
        # For full listing, use sqlite backend
        return []

    # ── SQLite backend (encrypted) ─────────────────────────────────────────

    def _get_fernet(self) -> Fernet:
        if self._fernet is None:
            master_key = os.getenv("VERA_MASTER_KEY")
            if not master_key:
                # Generate and warn — first-time setup
                import keyring
                master_key = keyring.get_password("vera", "_master_key")
                if not master_key:
                    master_key = Fernet.generate_key().decode()
                    try:
                        keyring.set_password("vera", "_master_key", master_key)
                    except Exception:
                        raise RuntimeError(
                            "Cannot store master key. Set VERA_MASTER_KEY env var for sqlite secrets backend."
                        )
            self._fernet = Fernet(master_key.encode() if isinstance(master_key, str) else master_key)
        return self._fernet

    def _sqlite_conn(self):
        import aiosqlite
        Path(self._sqlite_path).parent.mkdir(parents=True, exist_ok=True)
        return aiosqlite.connect(self._sqlite_path)

    async def _sqlite_ensure_table(self, conn):
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS secrets (
                key   TEXT PRIMARY KEY,
                value BLOB NOT NULL
            )
        """)
        await conn.commit()

    async def _sqlite_get(self, key: str) -> Optional[str]:
        fernet = self._get_fernet()
        async with self._sqlite_conn() as conn:
            await self._sqlite_ensure_table(conn)
            async with conn.execute("SELECT value FROM secrets WHERE key = ?", (key,)) as cur:
                row = await cur.fetchone()
        if row is None:
            return None
        return fernet.decrypt(bytes(row[0])).decode()

    async def _sqlite_set(self, key: str, value: str) -> None:
        fernet = self._get_fernet()
        encrypted = fernet.encrypt(value.encode())
        async with self._sqlite_conn() as conn:
            await self._sqlite_ensure_table(conn)
            await conn.execute(
                "INSERT OR REPLACE INTO secrets (key, value) VALUES (?, ?)", (key, encrypted)
            )
            await conn.commit()

    async def _sqlite_delete(self, key: str) -> None:
        async with self._sqlite_conn() as conn:
            await self._sqlite_ensure_table(conn)
            await conn.execute("DELETE FROM secrets WHERE key = ?", (key,))
            await conn.commit()

    async def _sqlite_list(self, prefix: str) -> list[str]:
        async with self._sqlite_conn() as conn:
            await self._sqlite_ensure_table(conn)
            async with conn.execute(
                "SELECT key FROM secrets WHERE key LIKE ?", (prefix + "%",)
            ) as cur:
                rows = await cur.fetchall()
        return [row[0] for row in rows]