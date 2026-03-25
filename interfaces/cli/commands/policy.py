"""vera policy — Permission, role, and policy management.

Permission model:
  Permissions (perm:*) are named capabilities: an object pattern + action.
  Roles are collections of permissions (granted via `vera policy grant`).
  Users hold one or more roles (managed via `vera policy assign-role`).

Command groups:
  define-permission   — register a new named permission
  list-permissions    — show all named permissions
  grant               — grant a permission to a role
  revoke-permission   — revoke a permission from a role
  assign-role         — assign a role to a user
  revoke-role         — revoke a role from a user
  list                — show full policy state (permissions + grants + assignments)
  add                 — raw Casbin policy rule (advanced)
  remove              — remove raw Casbin policy rule (advanced)
  test                — dry-run permission check
"""
import typer
from rich.console import Console
from rich.table import Table

from interfaces.cli._session import require_role, require_session

app = typer.Typer(help="Manage permissions, roles, and policy assignments", no_args_is_help=True)
console = Console()


def _security():
    from core.security import SecurityManager
    return SecurityManager()


# ── Named permissions ──────────────────────────────────────────────────────────

@app.command("define-permission")
def policy_define_permission(
    name: str = typer.Argument(..., help="Permission name, e.g. perm:gmail:send"),
    obj: str = typer.Argument(..., help="Object pattern, e.g. gmail.*"),
    action: str = typer.Argument("execute", help="Action, e.g. execute, read, manage"),
    effect: str = typer.Option("allow", "--effect", help="allow | deny"),
    description: str = typer.Option("", "--desc", help="Human-readable description"),
) -> None:
    """Define a new named permission. Idempotent. Requires owner role."""
    require_role("owner")
    sec = _security()
    sec.register_permission(name, obj, action, effect)
    console.print(
        f"[green]✓[/green] Permission [bold]{name}[/bold] defined  "
        f"[cyan]{obj}[/cyan] → {action} ([{'green' if effect == 'allow' else 'red'}]{effect}[/])"
        + (f"\n  {description}" if description else "")
    )


@app.command("list-permissions")
def policy_list_permissions() -> None:
    """Show all defined named permissions."""
    require_session()
    sec = _security()
    perms = sec.get_all_permissions()
    if not perms:
        console.print("[yellow]No named permissions defined.[/yellow]")
        return
    table = Table(title="Named Permissions", show_header=True, header_style="bold")
    table.add_column("Name", style="cyan")
    table.add_column("Object Pattern")
    table.add_column("Action")
    table.add_column("Effect")
    for p in sorted(perms, key=lambda x: x["name"]):
        eff = p["effect"]
        eff_str = f"[green]{eff}[/green]" if eff == "allow" else f"[red]{eff}[/red]"
        table.add_row(p["name"], p["obj"], p["action"], eff_str)
    console.print(table)


@app.command("grant")
def policy_grant(
    role: str = typer.Argument(..., help="Role to grant the permission to"),
    permission: str = typer.Argument(..., help="Permission name, e.g. perm:gmail:send"),
) -> None:
    """Grant a named permission to a role. Requires owner role."""
    require_role("owner")
    sec = _security()
    sec.grant_permission_to_role(role, permission)
    console.print(
        f"[green]✓[/green] [bold]{role}[/bold] granted [cyan]{permission}[/cyan]"
    )


@app.command("revoke-permission")
def policy_revoke_permission(
    role: str = typer.Argument(..., help="Role to revoke the permission from"),
    permission: str = typer.Argument(..., help="Permission name, e.g. perm:gmail:send"),
) -> None:
    """Revoke a named permission from a role. Requires owner role."""
    require_role("owner")
    sec = _security()
    sec.revoke_permission_from_role(role, permission)
    console.print(
        f"[green]✓[/green] [bold]{role}[/bold] revoked [cyan]{permission}[/cyan]"
    )


# ── Role assignments ───────────────────────────────────────────────────────────

@app.command("assign-role")
def policy_assign_role(
    user_id: str = typer.Argument(..., help="User ID"),
    role: str = typer.Argument(..., help="Role to assign, e.g. manager"),
) -> None:
    """Assign a role to a user. Requires owner role."""
    require_role("owner")
    sec = _security()
    sec.assign_role(user_id, role)
    console.print(f"[green]✓[/green] Assigned [bold]{role}[/bold] to [cyan]{user_id}[/cyan]")


@app.command("revoke-role")
def policy_revoke_role(
    user_id: str = typer.Argument(...),
    role: str = typer.Argument(...),
) -> None:
    """Revoke a role from a user. Requires owner role."""
    require_role("owner")
    sec = _security()
    sec.revoke_role(user_id, role)
    console.print(f"[green]✓[/green] Revoked [bold]{role}[/bold] from [cyan]{user_id}[/cyan]")


# ── Full state listing ─────────────────────────────────────────────────────────

@app.command("list")
def policy_list() -> None:
    """Show full policy state: named permissions, role grants, user assignments."""
    require_session()
    sec = _security()
    enforcer = sec.enforcer

    # Table 1 — Named permissions
    perms = sec.get_all_permissions()
    p_table = Table(title="Named Permissions", show_header=True, header_style="bold")
    p_table.add_column("Name", style="cyan")
    p_table.add_column("Object Pattern")
    p_table.add_column("Action")
    p_table.add_column("Effect")
    for p in sorted(perms, key=lambda x: x["name"]):
        eff = p["effect"]
        eff_str = f"[green]{eff}[/green]" if eff == "allow" else f"[red]{eff}[/red]"
        p_table.add_row(p["name"], p["obj"], p["action"], eff_str)

    # Table 2 — Raw / deny policies (non-perm:* subjects)
    raw_table = Table(title="Raw Policies", show_header=True, header_style="bold")
    raw_table.add_column("Subject", style="cyan")
    raw_table.add_column("Object")
    raw_table.add_column("Action")
    raw_table.add_column("Effect")
    for rule in enforcer.get_policy():
        if not rule[0].startswith("perm:"):
            eff = rule[3] if len(rule) > 3 else "allow"
            eff_str = f"[green]{eff}[/green]" if eff == "allow" else f"[red]{eff}[/red]"
            raw_table.add_row(rule[0], rule[1], rule[2], eff_str)

    # Table 3 — Role → permission grants and user → role assignments
    g_table = Table(title="Role Grants & User Assignments", show_header=True, header_style="bold")
    g_table.add_column("Subject", style="cyan")
    g_table.add_column("Inherits / Granted")
    for g in sorted(enforcer.get_grouping_policy(), key=lambda x: x[0]):
        g_table.add_row(g[0], g[1])

    console.print(p_table)
    if raw_table.row_count:
        console.print()
        console.print(raw_table)
    console.print()
    console.print(g_table)


# ── Raw policy management (advanced) ──────────────────────────────────────────

@app.command("add")
def policy_add(
    subject: str = typer.Argument(..., help="Subject (role or perm name)"),
    object_pattern: str = typer.Argument(..., help="Object pattern, e.g. llm.*"),
    action: str = typer.Argument(..., help="Action, e.g. execute"),
    effect: str = typer.Option("allow", "--effect", help="allow | deny"),
) -> None:
    """Add a raw Casbin policy rule (advanced). Requires owner role."""
    require_role("owner")
    sec = _security()
    sec.add_policy(subject, object_pattern, action, effect)
    console.print(
        f"[green]✓[/green] Added: [bold]{subject}[/bold] → [cyan]{object_pattern}[/cyan]"
        f" → {action} ([{'green' if effect == 'allow' else 'red'}]{effect}[/])"
    )


@app.command("remove")
def policy_remove(
    subject: str = typer.Argument(...),
    object_pattern: str = typer.Argument(...),
    action: str = typer.Argument(...),
    effect: str = typer.Option("allow", "--effect"),
) -> None:
    """Remove a raw Casbin policy rule (advanced). Requires owner role."""
    require_role("owner")
    sec = _security()
    sec.remove_policy(subject, object_pattern, action, effect)
    console.print(f"[green]✓[/green] Removed: [bold]{subject}[/bold] → [cyan]{object_pattern}[/cyan]")


# ── Permission test ────────────────────────────────────────────────────────────

@app.command("test")
def policy_test(
    subject: str = typer.Argument(..., help="User ID or role name to test"),
    tool: str = typer.Argument(..., help="Tool or object pattern"),
    action: str = typer.Argument("execute", help="Action (default: execute)"),
) -> None:
    """
    Test whether a user or role can perform an action.
    Resolves the full permission chain (user → roles → permissions).
    Exit 0=allowed, 1=denied.
    """
    require_session()
    sec = _security()
    allowed = sec.enforce(subject, tool, action)
    if allowed:
        console.print(
            f"[green]✓ ALLOWED[/green]  subject=[bold]{subject}[/bold]"
            f"  tool=[cyan]{tool}[/cyan]  action={action}"
        )
    else:
        console.print(
            f"[red]✗ DENIED[/red]   subject=[bold]{subject}[/bold]"
            f"  tool=[cyan]{tool}[/cyan]  action={action}"
        )
    raise typer.Exit(0 if allowed else 1)
