"""
SecurityManager — wraps PyCasbin for runtime policy management.

Policies are hot-reloadable (no kernel restart required).
All policy mutations emit security.policy_changed on the bus.

Permission model:
  - Named permissions (perm:<ns>:<cap>) are atomic capabilities declared by core
    and plugins. They are Casbin subjects with policy rules (p lines).
  - Roles are collections of permissions, granted via Casbin grouping (g lines).
  - Users are assigned one or more roles, also via g lines.
  - Enforcement subject can be a user_id (resolved transitively through roles
    to permissions) or a role name directly.
"""
import os
from typing import Optional, TYPE_CHECKING

import casbin

if TYPE_CHECKING:
    from core.bus import VeraBus

_PERM_PREFIX = "perm:"


class SecurityManager:
    """
    Thin wrapper over casbin.Enforcer with bus signal emission.
    The enforcer is the source of truth for all permission checks.
    """

    def __init__(
        self,
        model_path: Optional[str] = None,
        policy_path: Optional[str] = None,
        bus: Optional["VeraBus"] = None,
    ):
        self._model_path = model_path or os.getenv("VERA_CASBIN_MODEL", "data/casbin/rbac_model.conf")
        self._policy_path = policy_path or os.getenv("VERA_CASBIN_POLICY", "data/casbin/policy.csv")
        self._enforcer = casbin.Enforcer(self._model_path, self._policy_path)
        self._bus = bus

    @property
    def enforcer(self) -> casbin.Enforcer:
        """Direct access to the casbin enforcer (used in ToolCallContext)."""
        return self._enforcer

    # ── Enforcement ────────────────────────────────────────────────────────

    def enforce(self, subject: str, obj: str, action: str) -> bool:
        """
        Return True if subject (user_id or role name) can perform action on obj.
        Subject is resolved transitively through role→permission assignments.
        """
        return self._enforcer.enforce(subject, obj, action)

    def enforce_any(self, roles: list[str], obj: str, action: str) -> bool:
        """Return True if ANY of the given roles can perform action on obj."""
        return any(self._enforcer.enforce(role, obj, action) for role in roles)

    # ── Named permission management ────────────────────────────────────────

    def register_permission(
        self,
        name: str,
        obj: str,
        action: str,
        effect: str = "allow",
    ) -> None:
        """
        Define a named permission and save.

        name    — permission identifier, e.g. 'perm:gmail:send'
        obj     — Casbin object pattern, e.g. 'gmail.*'
        action  — e.g. 'execute', 'read', 'manage'
        effect  — 'allow' (default) or 'deny'

        Idempotent: no-op if an identical rule already exists.
        """
        if not name.startswith(_PERM_PREFIX):
            name = f"{_PERM_PREFIX}{name}"
        existing = self._enforcer.get_filtered_policy(0, name, obj, action, effect)
        if existing:
            return
        self._enforcer.add_policy(name, obj, action, effect)
        self._enforcer.save_policy()
        self._emit_change("register_permission", name, obj, action, effect)

    def grant_permission_to_role(self, role: str, permission: str) -> None:
        """
        Grant a named permission to a role. Emits security.policy_changed.
        Idempotent: no-op if already granted.
        """
        if not permission.startswith(_PERM_PREFIX):
            permission = f"{_PERM_PREFIX}{permission}"
        if self._enforcer.has_role_for_user(role, permission):
            return
        self._enforcer.add_role_for_user(role, permission)
        self._enforcer.save_policy()
        self._emit_change("grant_permission", role, permission, "", "")

    def revoke_permission_from_role(self, role: str, permission: str) -> None:
        """Revoke a named permission from a role."""
        if not permission.startswith(_PERM_PREFIX):
            permission = f"{_PERM_PREFIX}{permission}"
        self._enforcer.delete_role_for_user(role, permission)
        self._enforcer.save_policy()
        self._emit_change("revoke_permission", role, permission, "", "")

    def get_permissions_for_role(self, role: str) -> list[str]:
        """
        Return the named permissions directly granted to a role.
        Only returns perm:* entries (not inherited role names).
        """
        all_roles = self._enforcer.get_roles_for_user(role)
        return [r for r in all_roles if r.startswith(_PERM_PREFIX)]

    def get_all_permissions(self) -> list[dict]:
        """
        Return all defined named permissions with their policy rules.
        Each dict: {name, obj, action, effect}
        """
        result = []
        for rule in self._enforcer.get_policy():
            if rule[0].startswith(_PERM_PREFIX):
                result.append({
                    "name":   rule[0],
                    "obj":    rule[1],
                    "action": rule[2],
                    "effect": rule[3] if len(rule) > 3 else "allow",
                })
        return result

    def get_users_for_role(self, role: str) -> list[str]:
        """Return user_ids directly assigned to a role (not via inheritance)."""
        return [
            u for u in self._enforcer.get_users_in_role(role)
            if not u.startswith(_PERM_PREFIX)
        ]

    # ── Role management ────────────────────────────────────────────────────

    def assign_role(self, user_id: str, role: str) -> None:
        """Assign a role to a user and save. Emits security.policy_changed."""
        self._enforcer.add_role_for_user(user_id, role)
        self._enforcer.save_policy()
        self._emit_change("assign_role", user_id, role, "", "")

    def revoke_role(self, user_id: str, role: str) -> None:
        """Remove a role from a user and save."""
        self._enforcer.delete_role_for_user(user_id, role)
        self._enforcer.save_policy()
        self._emit_change("revoke_role", user_id, role, "", "")

    def get_roles_for_user(self, user_id: str) -> list[str]:
        """Return role names assigned to user_id (excludes perm:* entries)."""
        return [
            r for r in self._enforcer.get_roles_for_user(user_id)
            if not r.startswith(_PERM_PREFIX)
        ]

    # ── Raw policy management ──────────────────────────────────────────────

    def add_policy(self, subject: str, obj: str, action: str, effect: str = "allow") -> None:
        """Add a raw policy rule and save. Emits security.policy_changed."""
        self._enforcer.add_policy(subject, obj, action, effect)
        self._enforcer.save_policy()
        self._emit_change("add", subject, obj, action, effect)

    def remove_policy(self, subject: str, obj: str, action: str, effect: str = "allow") -> None:
        """Remove a raw policy rule and save. Emits security.policy_changed."""
        self._enforcer.remove_policy(subject, obj, action, effect)
        self._enforcer.save_policy()
        self._emit_change("remove", subject, obj, action, effect)

    def reload_policy(self) -> None:
        """Reload policy from disk (useful after external edits)."""
        self._enforcer.load_policy()

    # ── Internal ──────────────────────────────────────────────────────────

    def _emit_change(self, action: str, subject: str, obj: str, perm: str, effect: str) -> None:
        if self._bus:
            import asyncio
            asyncio.get_event_loop().create_task(
                self._bus.emit("security.policy_changed", {
                    "action": action, "subject": subject,
                    "object": obj, "permission": perm, "effect": effect,
                })
            )
