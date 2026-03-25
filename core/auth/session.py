"""
SessionStore — VFS-backed session persistence.

Tokens are stored at key  auth:session:{token}  with TTL = session duration.
The VFS handles expiry automatically; we do a belt-and-suspenders datetime
check on read so callers always get a SessionExpired rather than stale data.

Session payload stores user_roles (list).  Old sessions that only have the
scalar user_role field are transparently upgraded on read.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import TYPE_CHECKING

from core.auth.base import AuthResult, SessionExpired, SessionInfo, SessionNotFound

if TYPE_CHECKING:
    from core.vfs.base import VeraFileSystem

_PREFIX = "auth:session:"
_TTL_GRACE = 60  # extra VFS TTL seconds beyond session.expires_at


class SessionStore:
    """Stores and retrieves session tokens in the VFS."""

    def __init__(self, vfs: "VeraFileSystem") -> None:
        self._vfs = vfs

    # ── write ──────────────────────────────────────────────────────────────

    async def save(self, result: AuthResult) -> None:
        data = {
            "user_id":       result.user_id,
            "user_roles":    result.user_roles,
            "user_role":     result.primary_role,   # kept for display / legacy
            "session_token": result.session_token,
            "expires_at":    result.expires_at.isoformat(),
            "provider":      result.provider,
            "metadata":      result.metadata,
        }
        ttl = max(
            int((result.expires_at - datetime.utcnow()).total_seconds()) + _TTL_GRACE,
            1,
        )
        await self._vfs.set(
            f"{_PREFIX}{result.session_token}",
            json.dumps(data).encode(),
            ttl=ttl,
        )

    # ── read ───────────────────────────────────────────────────────────────

    async def get(self, token: str) -> SessionInfo:
        raw = await self._vfs.get(f"{_PREFIX}{token}")
        if raw is None:
            raise SessionNotFound("Session not found or already expired.")
        data = json.loads(raw)
        expires_at = datetime.fromisoformat(data["expires_at"])

        # Normalize: old sessions may only have the scalar user_role field.
        user_roles = data.get("user_roles")
        if not user_roles:
            legacy = data.get("user_role", "")
            user_roles = [legacy] if legacy else []

        info = SessionInfo(
            user_id=data["user_id"],
            user_roles=user_roles,
            user_role=user_roles[0] if user_roles else "",
            session_token=token,
            expires_at=expires_at,
            provider=data["provider"],
        )
        if info.is_expired:
            await self.revoke(token)
            raise SessionExpired("Session has expired. Please log in again.")
        return info

    # ── delete ─────────────────────────────────────────────────────────────

    async def revoke(self, token: str) -> None:
        await self._vfs.delete(f"{_PREFIX}{token}")

    async def revoke_all_for_user(self, user_id: str) -> int:
        """Delete every active session belonging to user_id. Returns count."""
        keys = await self._vfs.list_keys(_PREFIX)
        count = 0
        for key in keys:
            raw = await self._vfs.get(key)
            if raw:
                try:
                    if json.loads(raw).get("user_id") == user_id:
                        await self._vfs.delete(key)
                        count += 1
                except Exception:
                    continue
        return count
