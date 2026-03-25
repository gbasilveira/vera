"""
AuthManager — orchestrates authentication across providers.

The manager is stored on the kernel (kernel.get_auth_manager()) so any
part of the system that has a kernel reference can reach it without
importing it directly.

Provider registration:
  - core: setup_kernel() registers LocalAuthProvider automatically.
  - plugins: override VeraPlugin.register_auth_providers(manager) and call
    manager.register_provider(MyProvider()).  The kernel calls this hook
    automatically during load_plugin().

Role enrichment:
  AuthManager is constructed with an optional SecurityManager reference.
  After every successful authenticate() call it:
    1. Looks up the user's roles in Casbin.
    2. If none exist yet (first login / migration), assigns the provider's
       suggested user_role to Casbin and uses that.
  This means authorization is always driven by Casbin, with the DB role
  column serving as a one-time bootstrap hint.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from core.auth.base import (
    AuthProviderNotFound,
    AuthResult,
    SessionInfo,
    SessionNotFound,
    SessionExpired,
    VeraAuthProvider,
)
from core.auth.session import SessionStore

if TYPE_CHECKING:
    from core.secrets import SecretsManager
    from core.security import SecurityManager
    from core.vfs.base import VeraFileSystem


class AuthManager:
    """
    Central authentication coordinator.

    Typical lifecycle:
        manager = AuthManager(vfs, security=security)
        manager.register_provider(LocalAuthProvider())
        await manager.setup(secrets)

        # at login:
        result = await manager.authenticate("local", {"username": …, "password": …})
        # result.user_roles is populated from Casbin

        # on each request:
        session = await manager.verify_session(token)
        deps = factory.create(user_id=session.user_id, user_roles=session.user_roles)
    """

    def __init__(self, vfs: "VeraFileSystem", security: Optional["SecurityManager"] = None) -> None:
        self._providers: dict[str, VeraAuthProvider] = {}
        self._sessions = SessionStore(vfs)
        self._security = security

    # ── Provider registry ──────────────────────────────────────────────────

    def register_provider(self, provider: VeraAuthProvider) -> None:
        """
        Register an auth provider.
        Called during setup_kernel() for built-in providers and from
        VeraPlugin.register_auth_providers() for plugin-supplied providers.
        """
        self._providers[provider.name] = provider

    def get_provider(self, name: str) -> Optional[VeraAuthProvider]:
        return self._providers.get(name)

    def list_providers(self) -> list[str]:
        return list(self._providers.keys())

    # ── Lifecycle ─────────────────────────────────────────────────────────

    async def setup(self, secrets: "SecretsManager") -> None:
        """Initialise all registered providers (create tables, load config, etc.)."""
        vfs = self._sessions._vfs
        for provider in self._providers.values():
            await provider.setup(vfs, secrets)

    async def teardown(self) -> None:
        """Gracefully shut down all providers."""
        for provider in self._providers.values():
            await provider.teardown()

    # ── Authentication ─────────────────────────────────────────────────────

    async def authenticate(self, provider_name: str, credentials: dict) -> AuthResult:
        """
        Authenticate using the named provider.
        Enriches user_roles from Casbin (with auto-migration fallback).
        Creates and persists a session on success.
        Raises: AuthProviderNotFound, AuthenticationFailed.
        """
        if provider_name not in self._providers:
            raise AuthProviderNotFound(
                f"Auth provider '{provider_name}' not registered. "
                f"Available: {self.list_providers()}"
            )
        result = await self._providers[provider_name].authenticate(credentials)
        result = self._enrich_roles(result)
        await self._sessions.save(result)
        return result

    def _enrich_roles(self, result: AuthResult) -> AuthResult:
        """
        Fill result.user_roles from Casbin.
        If Casbin has no roles for this user yet (first login / migration),
        fall back to result.user_role and assign it in Casbin automatically.
        Returns a new AuthResult with user_roles populated.
        """
        import dataclasses

        if self._security is None:
            # No security manager — use provider hint as-is
            roles = [result.user_role] if result.user_role else []
            return dataclasses.replace(result, user_roles=roles)

        roles = self._security.get_roles_for_user(result.user_id)

        if not roles and result.user_role:
            # Auto-migrate: assign the provider's suggested role to Casbin
            self._security.assign_role(result.user_id, result.user_role)
            roles = [result.user_role]

        return dataclasses.replace(result, user_roles=roles)

    # ── Session management ─────────────────────────────────────────────────

    async def verify_session(self, token: str) -> SessionInfo:
        """
        Verify a session token and return SessionInfo.
        Raises: SessionNotFound, SessionExpired.
        """
        return await self._sessions.get(token)

    async def revoke_session(self, token: str) -> None:
        """Revoke a specific session (logout)."""
        await self._sessions.revoke(token)

    async def revoke_all_sessions(self, user_id: str) -> int:
        """Revoke every active session for a user. Returns count revoked."""
        return await self._sessions.revoke_all_for_user(user_id)

    async def refresh_session(self, token: str) -> Optional[AuthResult]:
        """
        Attempt to extend a session via its provider without re-entering credentials.
        Returns a new AuthResult with fresh token, or None if unsupported.
        """
        try:
            session = await self._sessions.get(token)
        except (SessionNotFound, SessionExpired):
            return None
        provider = self._providers.get(session.provider)
        if provider is None:
            return None
        new_result = await provider.refresh(session)
        if new_result:
            new_result = self._enrich_roles(new_result)
            await self._sessions.save(new_result)
        return new_result
