import asyncio
import os
import time
from pathlib import Path
from typing import Optional

import aiosqlite

from core.vfs.base import VeraFileSystem


class LocalFS(VeraFileSystem):
    """
    SQLite-backed VFS. Default backend for single-server deployments.
    
    Thread safety: uses a single aiosqlite connection per instance.
    For concurrent access, use one LocalFS instance per coroutine or
    rely on SQLite's WAL mode (enabled by default here).
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or os.getenv("VERA_VFS_PATH", "data/vera_vfs.db")
        self._conn: Optional[aiosqlite.Connection] = None
        self._lock = asyncio.Lock()

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = await aiosqlite.connect(self._db_path)
            await self._conn.execute("PRAGMA journal_mode=WAL")
            await self._conn.execute("""
                CREATE TABLE IF NOT EXISTS kv_store (
                    key        TEXT PRIMARY KEY,
                    value      BLOB NOT NULL,
                    expires_at REAL
                )
            """)
            await self._conn.commit()
        return self._conn

    async def get(self, key: str) -> Optional[bytes]:
        async with self._lock:
            conn = await self._get_conn()
            now = time.time()
            async with conn.execute(
                "SELECT value, expires_at FROM kv_store WHERE key = ?", (key,)
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                return None
            value, expires_at = row
            if expires_at is not None and expires_at < now:
                await conn.execute("DELETE FROM kv_store WHERE key = ?", (key,))
                await conn.commit()
                return None
            return bytes(value)

    async def set(self, key: str, value: bytes, ttl: Optional[int] = None) -> None:
        async with self._lock:
            conn = await self._get_conn()
            expires_at = (time.time() + ttl) if ttl is not None else None
            await conn.execute(
                "INSERT OR REPLACE INTO kv_store (key, value, expires_at) VALUES (?, ?, ?)",
                (key, value, expires_at),
            )
            await conn.commit()

    async def delete(self, key: str) -> None:
        async with self._lock:
            conn = await self._get_conn()
            await conn.execute("DELETE FROM kv_store WHERE key = ?", (key,))
            await conn.commit()

    async def list_keys(self, prefix: str) -> list[str]:
        async with self._lock:
            conn = await self._get_conn()
            now = time.time()
            async with conn.execute(
                """SELECT key FROM kv_store
                   WHERE key LIKE ? AND (expires_at IS NULL OR expires_at > ?)""",
                (prefix + "%", now),
            ) as cursor:
                rows = await cursor.fetchall()
            return [row[0] for row in rows]

    async def close(self) -> None:
        """Close the database connection. Call during shutdown."""
        if self._conn:
            await self._conn.close()
            self._conn = None