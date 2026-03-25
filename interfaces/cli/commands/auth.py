"""vera auth — Authentication and user management."""
import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from interfaces.cli._session import (
    clear_session,
    load_session,
    require_session,
    save_session,
)

app = typer.Typer(help="Authenticate and manage users", no_args_is_help=True)
console = Console()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _kernel():
    from core.setup import setup_kernel
    return await setup_kernel()


def _local_provider(auth_manager):
    from core.auth.base import AuthProviderNotFound
    p = auth_manager.get_provider("local")
    if p is None:
        raise AuthProviderNotFound("Local auth provider is not registered.")
    return p


def _require_owner(session):
    """Exit if the session does not hold the owner role."""
    if "owner" not in session.get("user_roles", [session.get("user_role", "")]):
        console.print("[red]Only owners can perform this action.[/red]")
        raise typer.Exit(1)


# ── Login / logout / whoami ───────────────────────────────────────────────────

@app.command("login")
def auth_login(
    username: str = typer.Option(..., "--username", "-u", prompt="Username"),
    password: str = typer.Option(..., "--password", "-p", prompt="Password", hide_input=True),
    provider: str = typer.Option("local", "--provider", help="Auth provider name"),
) -> None:
    """Authenticate and save a local session token."""
    asyncio.run(_login(username, password, provider))


async def _login(username: str, password: str, provider: str) -> None:
    from core.auth.base import AuthenticationFailed, AuthProviderNotFound
    kernel, bus, vfs, secrets, security, tracer, factory = await _kernel()
    auth_manager = kernel.get_auth_manager()
    if auth_manager is None:
        console.print("[red]Auth manager not initialised.[/red]")
        await vfs.close()
        raise typer.Exit(1)
    try:
        result = await auth_manager.authenticate(
            provider, {"username": username, "password": password}
        )
    except AuthenticationFailed as e:
        console.print(f"[red]Login failed:[/red] {e}")
        await vfs.close()
        raise typer.Exit(1)
    except AuthProviderNotFound as e:
        console.print(f"[red]{e}[/red]")
        await vfs.close()
        raise typer.Exit(1)

    save_session(result)
    roles_str = ", ".join(result.user_roles) if result.user_roles else "none"
    console.print(Panel(
        f"[bold]{result.user_id}[/bold]  roles=[cyan]{roles_str}[/cyan]  "
        f"provider={result.provider}  "
        f"expires {result.expires_at.strftime('%Y-%m-%d %H:%M')} UTC",
        title="[green]Logged in[/green]",
        expand=False,
    ))
    await vfs.close()


@app.command("logout")
def auth_logout() -> None:
    """Revoke the current session and clear local credentials."""
    asyncio.run(_logout())


async def _logout() -> None:
    session = load_session()
    if not session:
        console.print("[yellow]No active session.[/yellow]")
        return
    vfs = None
    try:
        kernel, bus, vfs, secrets, security, tracer, factory = await _kernel()
        auth_manager = kernel.get_auth_manager()
        if auth_manager:
            await auth_manager.revoke_session(session["session_token"])
    except Exception:
        pass  # best-effort server-side revocation
    finally:
        clear_session()
        console.print(f"[green]✓[/green] Logged out [bold]{session['user_id']}[/bold]")
        if vfs:
            try:
                await vfs.close()
            except Exception:
                pass


@app.command("whoami")
def auth_whoami() -> None:
    """Show the currently authenticated user and session details."""
    session = load_session()
    if not session:
        console.print("[yellow]Not authenticated.[/yellow]  Run [cyan]vera auth login[/cyan]")
        raise typer.Exit(1)
    roles_str = ", ".join(session.get("user_roles", [])) or session.get("user_role", "none")
    console.print(Panel(
        f"[bold]{session['user_id']}[/bold]  roles=[cyan]{roles_str}[/cyan]  "
        f"provider={session['provider']}  "
        f"expires {session['expires_at'][:16]} UTC",
        title="Current Session",
        expand=False,
    ))


@app.command("providers")
def auth_providers() -> None:
    """List all registered authentication providers."""
    asyncio.run(_providers())


async def _providers() -> None:
    kernel, bus, vfs, secrets, security, tracer, factory = await _kernel()
    auth_manager = kernel.get_auth_manager()
    if auth_manager is None:
        console.print("[red]Auth manager not initialised.[/red]")
        await vfs.close()
        raise typer.Exit(1)
    providers = auth_manager.list_providers()
    table = Table(title="Auth Providers", show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Type")
    for p_name in providers:
        p = auth_manager.get_provider(p_name)
        table.add_row(p_name, type(p).__name__)
    console.print(table)
    await vfs.close()


# ── User management (owner only) ──────────────────────────────────────────────

@app.command("add-user")
def auth_add_user(
    username: str = typer.Argument(..., help="New username"),
    role: str = typer.Argument(..., help="Initial role: owner | manager | intern | guest | …"),
    password: str = typer.Option(
        ..., "--password", "-p",
        prompt="Password", hide_input=True, confirmation_prompt=True,
    ),
) -> None:
    """Add a user. Bootstrap mode (0 users): no session required. Otherwise requires owner."""
    asyncio.run(_add_user(username, password, role))


async def _add_user(username: str, password: str, role: str) -> None:
    from core.auth.base import UserAlreadyExists
    kernel, bus, vfs, secrets, security, tracer, factory = await _kernel()
    auth_manager = kernel.get_auth_manager()
    try:
        provider = _local_provider(auth_manager)
        existing = await provider.registry.list_users()
        is_bootstrap = len(existing) == 0

        if not is_bootstrap:
            session = load_session()
            if not session:
                console.print("[red]Not authenticated.[/red]  Run [cyan]vera auth login[/cyan]")
                raise typer.Exit(1)
            _require_owner(session)

        # Create user record (role stored for display/migration)
        await provider.registry.add_user(username, password, role)

        # Assign initial role via Casbin (authoritative for authorization)
        sec = kernel.get_security()
        if sec:
            sec.assign_role(username, role)

        if is_bootstrap:
            console.print(
                f"[green]✓[/green] Bootstrap: first user [bold]{username}[/bold] created  "
                f"role=[cyan]{role}[/cyan]\n"
                f"  Run [cyan]vera auth login[/cyan] to start your session."
            )
        else:
            console.print(
                f"[green]✓[/green] User [bold]{username}[/bold] added  role=[cyan]{role}[/cyan]"
            )
    except UserAlreadyExists as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    finally:
        await vfs.close()


@app.command("list-users")
def auth_list_users() -> None:
    """List all users and their Casbin roles. Requires owner session."""
    session = require_session()
    _require_owner(session)
    asyncio.run(_list_users())


async def _list_users() -> None:
    kernel, bus, vfs, secrets, security, tracer, factory = await _kernel()
    auth_manager = kernel.get_auth_manager()
    sec = kernel.get_security()
    try:
        provider = _local_provider(auth_manager)
        users = await provider.registry.list_users()
        if not users:
            console.print("[yellow]No users registered.[/yellow]")
            return
        table = Table(title="Users", show_header=True, header_style="bold")
        table.add_column("Username", style="cyan")
        table.add_column("Roles (Casbin)")
        table.add_column("DB Role", style="dim")
        table.add_column("Created", style="dim")
        for u in users:
            casbin_roles = sec.get_roles_for_user(u["user_id"]) if sec else []
            roles_str = ", ".join(casbin_roles) if casbin_roles else "[dim]none[/dim]"
            table.add_row(u["user_id"], roles_str, u["role"], u["created_at"][:10])
        console.print(table)
    finally:
        await vfs.close()


@app.command("delete-user")
def auth_delete_user(
    username: str = typer.Argument(...),
    yes: bool = typer.Option(False, "--yes", "-y"),
) -> None:
    """Delete a user and revoke all their sessions. Requires owner session."""
    session = require_session()
    _require_owner(session)
    if not yes:
        typer.confirm(f"Delete user '{username}' and all their sessions?", abort=True)
    asyncio.run(_delete_user(username))


async def _delete_user(username: str) -> None:
    from core.auth.base import UserNotFound
    kernel, bus, vfs, secrets, security, tracer, factory = await _kernel()
    auth_manager = kernel.get_auth_manager()
    sec = kernel.get_security()
    try:
        provider = _local_provider(auth_manager)
        await provider.registry.delete_user(username)
        # Revoke all Casbin role assignments for this user
        if sec:
            for role in sec.get_roles_for_user(username):
                sec.revoke_role(username, role)
        revoked = await auth_manager.revoke_all_sessions(username)
        console.print(
            f"[green]✓[/green] User [bold]{username}[/bold] deleted  "
            f"({revoked} session(s) revoked)"
        )
    except UserNotFound as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    finally:
        await vfs.close()


@app.command("change-password")
def auth_change_password(
    old_password: str = typer.Option(
        ..., "--old", prompt="Current password", hide_input=True
    ),
    new_password: str = typer.Option(
        ..., "--new", prompt="New password",
        hide_input=True, confirmation_prompt=True,
    ),
) -> None:
    """Change the current user's password."""
    session = require_session()
    asyncio.run(_change_password(session["user_id"], old_password, new_password))


async def _change_password(user_id: str, old_password: str, new_password: str) -> None:
    from core.auth.base import AuthenticationFailed
    kernel, bus, vfs, secrets, security, tracer, factory = await _kernel()
    auth_manager = kernel.get_auth_manager()
    try:
        provider = _local_provider(auth_manager)
        await provider.registry.change_password(user_id, old_password, new_password)
        console.print("[green]✓[/green] Password changed.")
    except AuthenticationFailed as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    finally:
        await vfs.close()


@app.command("update-role")
def auth_update_role(
    username: str = typer.Argument(...),
    role: str = typer.Argument(..., help="New role to assign"),
) -> None:
    """
    Replace a user's roles with a single new role.
    For fine-grained control use: vera policy assign-role / revoke-role.
    Requires owner session.
    """
    session = require_session()
    _require_owner(session)
    asyncio.run(_update_role(username, role))


async def _update_role(username: str, role: str) -> None:
    from core.auth.base import UserNotFound
    kernel, bus, vfs, secrets, security, tracer, factory = await _kernel()
    auth_manager = kernel.get_auth_manager()
    sec = kernel.get_security()
    try:
        provider = _local_provider(auth_manager)
        # Update the display column
        await provider.registry.update_role(username, role)
        # Replace Casbin roles: revoke all, assign new
        if sec:
            for old_role in sec.get_roles_for_user(username):
                sec.revoke_role(username, old_role)
            sec.assign_role(username, role)
        # Revoke existing sessions so the new role takes effect on next login
        revoked = await auth_manager.revoke_all_sessions(username)
        console.print(
            f"[green]✓[/green] [bold]{username}[/bold] → role=[cyan]{role}[/cyan]  "
            f"({revoked} session(s) revoked — user must log in again)"
        )
    except UserNotFound as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    finally:
        await vfs.close()
