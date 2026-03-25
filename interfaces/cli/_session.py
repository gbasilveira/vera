"""
CLI session helper — reads and writes the local session file.

Session is stored at ~/.config/vera/session.json (permissions 0o600).
Created on `vera auth login`, cleared on `vera auth logout`.

Every command that touches the kernel calls require_session() or get_identity()
at its entry point. There are no anonymous fallbacks — VERA is always in production.

Commands that intentionally skip auth:
  vera init      — filesystem bootstrap, runs before any user exists
  vera doctor    — diagnostic, must work even when auth is broken
  vera auth login     — the entry point itself
  vera auth whoami    — reads the local file only
  vera auth add-user  — allows the very first user to be created (bootstrap mode)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

_SESSION_DIR  = Path.home() / ".config" / "vera"
_SESSION_FILE = _SESSION_DIR / "session.json"


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def save_session(result) -> None:
    """Persist an AuthResult to the local session file."""
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)
    roles = result.user_roles if result.user_roles else (
        [result.user_role] if result.user_role else []
    )
    data = {
        "session_token": result.session_token,
        "user_id":       result.user_id,
        "user_roles":    roles,
        "user_role":     roles[0] if roles else "",   # primary role, for display
        "expires_at":    result.expires_at.isoformat(),
        "provider":      result.provider,
    }
    _SESSION_FILE.write_text(json.dumps(data, indent=2))
    _SESSION_FILE.chmod(0o600)


def load_session() -> dict | None:
    """
    Read the session file.
    Returns None if the file is missing, unreadable, or the session has expired.
    Does NOT exit — callers that require a session must call require_session().
    Normalises old single-role sessions to the user_roles list format.
    """
    if not _SESSION_FILE.exists():
        return None
    try:
        data = json.loads(_SESSION_FILE.read_text())
        if _utcnow_iso() > data.get("expires_at", ""):
            return None
        # Normalize: ensure user_roles is always a list
        if "user_roles" not in data or not data["user_roles"]:
            legacy = data.get("user_role", "")
            data["user_roles"] = [legacy] if legacy else []
        if "user_role" not in data or not data["user_role"]:
            data["user_role"] = data["user_roles"][0] if data["user_roles"] else ""
        return data
    except Exception:
        return None


def clear_session() -> None:
    """Delete the local session file."""
    if _SESSION_FILE.exists():
        _SESSION_FILE.unlink()


def require_session() -> dict:
    """
    Return session data or exit with a clear error.
    Call this at the top of every command that must be authenticated.
    """
    import typer
    from rich.console import Console
    session = load_session()
    if session is None:
        Console().print(
            "[red]Not authenticated.[/red]  Run [cyan]vera auth login[/cyan]"
        )
        raise typer.Exit(1)
    return session


def require_role(role: str) -> dict:
    """
    Require an active session AND membership in the given role.
    With multi-role support: passes if the user holds the role among any of
    their assigned roles.
    Exits with an error if unauthenticated or the role is not held.
    """
    import typer
    from rich.console import Console
    session = require_session()
    held_roles = session.get("user_roles", [session.get("user_role", "")])
    if role not in held_roles:
        Console().print(
            f"[red]Requires role '{role}'.[/red]  "
            f"Your roles: [cyan]{', '.join(held_roles) or 'none'}[/cyan]"
        )
        raise typer.Exit(1)
    return session


def get_identity() -> tuple[str, list[str]]:
    """
    Return (user_id, user_roles) from the active session.
    Exits if not authenticated — no anonymous fallback.
    """
    session = require_session()
    return session["user_id"], session.get("user_roles", [session.get("user_role", "")])
