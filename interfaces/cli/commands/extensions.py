"""
vera ext — Inspect the extension point registry.

Commands
--------
vera ext points                     List all registered extension points
vera ext contributions [--point P]  List contributions (optionally filtered)
vera ext show <point-id>            Full detail for one extension point
"""

from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from interfaces.cli._session import require_session

app = typer.Typer(
    name="ext",
    help="Inspect extension points and plugin contributions.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)
console = Console()


def _registry():
    """Return the live registry from the loaded kernel."""
    from core.extensions import ExtensionRegistry
    import os
    # Lightweight path: scan manifests without booting the kernel.
    # Sufficient for all display commands.
    plugins_dir = os.getenv("VERA_PLUGINS_DIR", "plugins")
    reg = ExtensionRegistry()   # built-ins already in
    for manifest in ExtensionRegistry.scan_manifests(plugins_dir):
        reg.register_from_manifest(manifest)
    return reg


# ── Commands ─────────────────────────────────────────────────────────────────

@app.command("points")
def ext_points() -> None:
    """List all registered extension points."""
    require_session()
    reg = _registry()
    points = reg.list_points()

    if not points:
        console.print("[yellow]No extension points registered.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("ID", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Owner", style="dim yellow")
    table.add_column("Contributions", justify="right")
    table.add_column("Description", style="dim")

    for pt in sorted(points, key=lambda p: p.id):
        n = len(reg.get_contributions(pt.id))
        contrib_str = f"[bold]{n}[/bold]" if n else "[dim]0[/dim]"
        table.add_row(pt.id, pt.type, pt.owner, contrib_str, pt.description)

    console.print()
    console.print(table)
    console.print()
    console.print(f"[dim]{len(points)} extension point(s).  "
                  f"Run [bold]vera ext show <id>[/bold] for details.[/dim]")
    console.print()


@app.command("contributions")
def ext_contributions(
    point: Optional[str] = typer.Option(None, "--point", "-p", help="Filter by extension point ID"),
    plugin: Optional[str] = typer.Option(None, "--plugin", help="Filter by contributing plugin"),
) -> None:
    """List plugin contributions, optionally filtered by point or plugin."""
    require_session()
    reg = _registry()

    if point:
        contribs = reg.get_contributions(point)
    else:
        contribs = reg.list_contributions()

    if plugin:
        contribs = [c for c in contribs if c.plugin == plugin]

    if not contribs:
        hint = f" to [bold]{point}[/bold]" if point else ""
        console.print(f"[yellow]No contributions found{hint}.[/yellow]")
        return

    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Plugin", style="cyan")
    table.add_column("Point", style="yellow")
    table.add_column("Type", style="green")
    table.add_column("Key params", style="dim")

    for c in sorted(contribs, key=lambda x: (x.point, x.plugin)):
        # Show the most descriptive params (name, title, path — whatever exists)
        key_params = _summarise_params(c.params)
        table.add_row(c.plugin, c.point, c.type, key_params)

    console.print()
    console.print(table)
    console.print()
    console.print(f"[dim]{len(contribs)} contribution(s)[/dim]")
    console.print()


@app.command("show")
def ext_show(
    point_id: str = typer.Argument(..., help="Extension point ID  e.g. interfaces.cli.commands"),
) -> None:
    """Show full detail for an extension point including its schema and all contributions."""
    require_session()
    reg = _registry()
    pt = reg.get_point(point_id)

    console.print()

    if pt is None:
        console.print(f"[red]Extension point not found:[/red] {point_id!r}")
        console.print("[dim]Run [bold]vera ext points[/bold] to see all registered points.[/dim]")
        raise typer.Exit(1)

    # Header
    console.print(Panel(
        Text.assemble(
            (pt.id, "bold cyan"), "\n",
            (f"Type: {pt.type}  ·  Owner: {pt.owner}", "dim"),
            ("\n" + pt.description if pt.description else ""),
        ),
        title="[bold]Extension Point[/bold]",
        expand=False,
    ))

    # Schema
    if pt.schema:
        console.print()
        console.print("[bold]Expected params[/bold]")
        schema_table = Table(show_header=True, header_style="dim", box=None, padding=(0, 2))
        schema_table.add_column("Param")
        schema_table.add_column("Type")
        schema_table.add_column("Required")
        schema_table.add_column("Notes", style="dim")
        for param, meta in pt.schema.items():
            if not isinstance(meta, dict):
                continue
            req = "[bold green]yes[/bold green]" if meta.get("required") else "no"
            notes_parts = []
            if "default" in meta:
                notes_parts.append(f"default: {meta['default']}")
            if "values" in meta:
                notes_parts.append("values: " + ", ".join(str(v) for v in meta["values"]))
            if "description" in meta:
                notes_parts.append(meta["description"])
            schema_table.add_row(param, meta.get("type", ""), req, "  ".join(notes_parts))
        console.print(schema_table)

    # Contributions
    contribs = reg.get_contributions(pt.id)
    console.print()
    if contribs:
        console.print(f"[bold]Contributions[/bold]  [dim]({len(contribs)})[/dim]")
        for c in sorted(contribs, key=lambda x: x.plugin):
            tree = Tree(
                Text.assemble(("[", "dim"), (c.plugin, "cyan"), ("]", "dim"),
                              f"  type: [green]{c.type}[/green]")
            )
            for k, v in c.params.items():
                tree.add(Text.assemble((f"{k}: ", "dim"), (str(v), "")))
            console.print(tree)
    else:
        console.print("[dim]No contributions yet.[/dim]")

    console.print()


# ── Helpers ──────────────────────────────────────────────────────────────────

def _summarise_params(params: dict) -> str:
    """Return a short human-readable summary of the most important params."""
    for key in ("name", "title", "path", "id", "handler", "component"):
        if key in params:
            return f"{key}={params[key]!r}"
    items = list(params.items())
    if items:
        k, v = items[0]
        return f"{k}={v!r}"
    return ""
