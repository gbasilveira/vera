"""
VERA Auth — base contracts.

VeraAuthProvider is the ABC every auth plugin must implement.
AuthManager (core/auth/manager.py) holds the provider registry and is
stored on the kernel so plugins and the interface layer can reach it.

Implementing an auth plugin:
    1. Subclass VeraAuthProvider and implement authenticate().
    2. In your VeraPlugin subclass, override register_auth_providers()
       and call auth_manager.register_provider(YourProvider()).
    3. That is all — the kernel calls register_auth_providers() automatically
       during load_plugin().

Permission model note:
    AuthResult and SessionInfo carry user_roles: list[str] — the list of
    Casbin role names the user holds at login time.  Authorization decisions
    use this list; it is never reduced to a single string at enforcement time.
    The legacy user_role property returns the first role (or 'guest') for
    display and backward-compatibility purposes only.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from core.auth.manager import AuthManager
    from core.secrets import SecretsManager
    from core.vfs.base import VeraFileSystem


# ── Exceptions ────────────────────────────────────────────────────────────────

class AuthenticationFailed(Exception):
    """Wrong credentials or provider-level rejection."""

class SessionExpired(Exception):
    """The session token exists but its TTL has elapsed."""

class SessionNotFound(Exception):
    """No session matches the given token."""

class AuthProviderNotFound(Exception):
    """No provider with the requested name is registered."""

class UserAlreadyExists(Exception):
    """Attempt to create a user_id that already exists in the registry."""

class UserNotFound(Exception):
    """No user with the given user_id exists in the registry."""


# ── Value objects ─────────────────────────────────────────────────────────────

@dataclass
class AuthResult:
    """Returned by a successful authenticate() call."""
    user_id:       str
    session_token: str
    expires_at:    datetime
    provider:      str
    # user_roles is the authoritative list of role names for this session.
    # AuthManager fills this from Casbin after the provider authenticates.
    user_roles:    list[str] = field(default_factory=list)
    # user_role is a hint from the provider (e.g. DB column).
    # AuthManager uses it as a migration fallback when Casbin has no roles yet.
    user_role:     str = ""
    metadata:      dict = field(default_factory=dict)

    @property
    def primary_role(self) -> str:
        """First role or 'guest'. Use for display only."""
        return self.user_roles[0] if self.user_roles else (self.user_role or "guest")


@dataclass
class SessionInfo:
    """Returned by verify_session(); represents a live, verified session."""
    user_id:       str
    session_token: str
    expires_at:    datetime
    provider:      str
    user_roles:    list[str] = field(default_factory=list)
    # Legacy single-role field kept for display / backward compat.
    user_role:     str = ""

    @property
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

    @property
    def primary_role(self) -> str:
        """First role or 'guest'. Use for display only."""
        return self.user_roles[0] if self.user_roles else (self.user_role or "guest")


# ── Abstract base ─────────────────────────────────────────────────────────────

class VeraAuthProvider(ABC):
    """
    Abstract base class for VERA authentication providers.

    Core contract:
      - authenticate(credentials) — verify identity, return AuthResult.
        Raise AuthenticationFailed on any rejection.
      - name — unique provider identifier ("local", "github_oauth", "ldap", …)

    Optional hooks:
      - setup(vfs, secrets) — called once during AuthManager.setup().
        Use it to initialise DB tables, load provider config from secrets, etc.
      - refresh(session_info) — extend an active session without re-entering
        credentials. Return None if the provider does not support refresh.
      - teardown() — called on graceful shutdown.
    """

    name: str  # must be set as a class attribute

    @abstractmethod
    async def authenticate(self, credentials: dict) -> AuthResult:
        """
        Verify the supplied credentials and return an AuthResult.
        Raise AuthenticationFailed if the credentials are invalid.

        credentials is a free-form dict; the schema is provider-specific:
          LocalAuthProvider  → {"username": str, "password": str}
          OAuthProvider      → {"code": str, "redirect_uri": str}
          TOTPProvider       → {"username": str, "password": str, "otp": str}

        Set user_role to the provider's suggestion (e.g. a DB column).
        AuthManager will overwrite user_roles from Casbin after this call.
        """

    async def refresh(self, session: SessionInfo) -> Optional[AuthResult]:
        """
        Attempt to extend an active session without re-authentication.
        Return a new AuthResult with a fresh token, or None if unsupported.
        Default: unsupported.
        """
        return None

    async def setup(self, vfs: "VeraFileSystem", secrets: "SecretsManager") -> None:
        """Initialise provider resources. Called once by AuthManager.setup()."""

    async def teardown(self) -> None:
        """Release provider resources. Called on graceful shutdown."""
