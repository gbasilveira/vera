"""vera middleware — Manage the middleware execution chain."""
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from interfaces.cli._session import require_role, require_session

app = typer.Typer(help="Manage the middleware execution chain", no_args_is_help=True)
console = Console()

_CONFIG_PATH = "data/middleware.json"


def _bare_kernel():
    from core.kernel import VeraKernel
    VeraKernel.reset()
    return VeraKernel.get_instance()


@app.command("list")
def middleware_list() -> None:
    """List all discovered middlewares and their current config state."""
    require_session()
    kernel = _bare_kernel()

    discovered = {d["name"]: d for d in kernel.discover_middlewares()}
    chain = kernel.get_middleware_config(_CONFIG_PATH)
    no_config = chain is None

    configured: dict[str, dict] = {e["name"]: e for e in (chain or [])}

    table = Table(title="Middleware Chain", show_header=True, header_style="bold")
    table.add_column("Order", justify="right")
    table.add_column("Name", style="cyan")
    table.add_column("Status")
    table.add_column("Class", style="dim")
    table.add_column("Description", style="dim")

    shown: set[str] = set()

    # Configured entries first, sorted by order
    if chain:
        for entry in sorted(chain, key=lambda e: e.get("order", 99)):
            name = entry["name"]
            shown.add(name)
            enabled = entry.get("enabled", True)
            status = "[green]enabled[/green]" if enabled else "[red]disabled[/red]"
            disc = discovered.get(name, {})
            table.add_row(
                str(entry.get("order", "?")),
                name,
                status,
                entry.get("class", disc.get("class", "?")),
                disc.get("description", ""),
            )

    # Discovered-but-not-configured
    for name, d in sorted(discovered.items(), key=lambda x: x[1].get("order_hint", 99)):
        if name not in shown:
            table.add_row(
                f"[dim]{d['order_hint']}[/dim]",
                name,
                "[yellow]not configured[/yellow]",
                d["class"],
                d["description"],
            )

    console.print(table)

    if no_config:
        console.print(
            f"\n[yellow]No config file at {_CONFIG_PATH}.[/yellow] "
            "Using built-in defaults at runtime."
        )
        console.print(
            f"  Run [cyan]vera middleware init[/cyan] to create "
            f"[bold]{_CONFIG_PATH}[/bold] and take full control."
        )


@app.command("init")
def middleware_init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing config"),
) -> None:
    """Create data/middleware.json with the built-in default chain."""
    require_role("owner")
    from pathlib import Path

    kernel = _bare_kernel()

    if Path(_CONFIG_PATH).exists() and not force:
        console.print(
            f"[yellow]{_CONFIG_PATH} already exists.[/yellow]  Use --force to overwrite."
        )
        raise typer.Exit(1)

    chain = kernel.default_middleware_config()
    kernel.save_middleware_config(chain, _CONFIG_PATH)
    console.print(
        f"[green]✓[/green] Created [bold]{_CONFIG_PATH}[/bold] "
        f"with {len(chain)} middlewares."
    )
    console.print(
        "  Use [cyan]vera middleware enable/disable/set-order[/cyan] to customise."
    )


@app.command("enable")
def middleware_enable(
    name: str = typer.Argument(..., help="Middleware name"),
    order: int = typer.Option(None, "--order", "-o", help="Execution order (integer)"),
    cls: str = typer.Option(
        None, "--class", "-c",
        help="Full class path  e.g. mypackage.mymodule.MyMiddleware",
    ),
) -> None:
    """Add or re-enable a middleware in the chain."""
    require_role("owner")
    kernel = _bare_kernel()

    chain = kernel.get_middleware_config(_CONFIG_PATH) or kernel.default_middleware_config()
    existing = next((e for e in chain if e["name"] == name), None)

    # Resolve class path
    class_path = cls
    order_resolved = order

    if not class_path:
        discovered = {d["name"]: d for d in kernel.discover_middlewares()}
        if name in discovered:
            class_path = discovered[name]["class"]
            if order_resolved is None:
                order_resolved = discovered[name]["order_hint"]
        elif existing:
            class_path = existing.get("class")

    if not class_path:
        console.print(
            f"[red]Cannot determine class for '{name}'.[/red]  "
            f"Use [cyan]--class module.ClassName[/cyan] to specify it explicitly."
        )
        raise typer.Exit(1)

    if order_resolved is None and existing:
        order_resolved = existing["order"]

    if order_resolved is None:
        console.print(
            f"[red]Specify [cyan]--order N[/cyan] for '{name}'.[/red]"
        )
        raise typer.Exit(1)

    if existing:
        existing["enabled"] = True
        existing["order"] = order_resolved
        existing["class"] = class_path
        console.print(
            f"[green]✓[/green] Re-enabled [bold]{name}[/bold]  order={order_resolved}"
        )
    else:
        chain.append({
            "name": name,
            "class": class_path,
            "order": order_resolved,
            "enabled": True,
        })
        console.print(
            f"[green]✓[/green] Added [bold]{name}[/bold]  order={order_resolved}"
        )

    kernel.save_middleware_config(chain, _CONFIG_PATH)


@app.command("disable")
def middleware_disable(
    name: str = typer.Argument(..., help="Middleware name"),
) -> None:
    """Disable a middleware (keeps it in config but skips it at runtime)."""
    require_role("owner")
    kernel = _bare_kernel()

    chain = kernel.get_middleware_config(_CONFIG_PATH)
    if chain is None:
        console.print(
            f"[red]No config at {_CONFIG_PATH}.[/red]  "
            "Run [cyan]vera middleware init[/cyan] first."
        )
        raise typer.Exit(1)

    entry = next((e for e in chain if e["name"] == name), None)
    if not entry:
        console.print(f"[red]'{name}' not found in config.[/red]")
        raise typer.Exit(1)

    entry["enabled"] = False
    kernel.save_middleware_config(chain, _CONFIG_PATH)
    console.print(f"[green]✓[/green] Disabled [bold]{name}[/bold]")


@app.command("set-order")
def middleware_set_order(
    name: str = typer.Argument(..., help="Middleware name"),
    order: int = typer.Argument(..., help="New execution order (integer, lower = earlier)"),
) -> None:
    """Change the execution order of a configured middleware."""
    require_role("owner")
    kernel = _bare_kernel()

    chain = kernel.get_middleware_config(_CONFIG_PATH)
    if chain is None:
        console.print(
            f"[red]No config at {_CONFIG_PATH}.[/red]  "
            "Run [cyan]vera middleware init[/cyan] first."
        )
        raise typer.Exit(1)

    entry = next((e for e in chain if e["name"] == name), None)
    if not entry:
        console.print(
            f"[red]'{name}' not found in config.[/red]  "
            f"Use [cyan]vera middleware enable {name}[/cyan] to add it first."
        )
        raise typer.Exit(1)

    old = entry["order"]
    entry["order"] = order
    kernel.save_middleware_config(chain, _CONFIG_PATH)
    console.print(f"[green]✓[/green] [bold]{name}[/bold]  order {old} → {order}")


@app.command("info")
def middleware_info(
    name: str = typer.Argument(..., help="Middleware name"),
) -> None:
    """Show details for a middleware: class, description, and config state."""
    require_session()
    kernel = _bare_kernel()

    discovered = {d["name"]: d for d in kernel.discover_middlewares()}
    chain = kernel.get_middleware_config(_CONFIG_PATH) or []
    configured = {e["name"]: e for e in chain}

    disc = discovered.get(name)
    conf = configured.get(name)

    if not disc and not conf:
        console.print(f"[red]'{name}' not found.[/red]")
        raise typer.Exit(1)

    console.print()
    console.print(Panel(
        f"[bold cyan]{name}[/bold cyan]",
        title="Middleware Info",
        expand=False,
    ))

    if disc:
        console.print(f"  [bold]class:[/bold]        {disc['class']}")
        console.print(f"  [bold]description:[/bold]  {disc['description']}")
        console.print(f"  [bold]order_hint:[/bold]   {disc['order_hint']}")

    if conf:
        enabled_str = "[green]yes[/green]" if conf.get("enabled", True) else "[red]no[/red]"
        console.print(f"  [bold]configured order:[/bold]  {conf['order']}")
        console.print(f"  [bold]enabled:[/bold]           {enabled_str}")
    else:
        console.print("  [dim]Not in config file — use [cyan]vera middleware enable[/cyan][/dim]")

    console.print()
