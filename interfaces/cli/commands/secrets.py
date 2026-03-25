"""vera secrets — Secrets management subcommands."""
import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from interfaces.cli._session import require_role

app = typer.Typer(help="Manage VERA secrets", no_args_is_help=True)
console = Console()


def _sm():
    from core.secrets import SecretsManager
    return SecretsManager()


@app.command("set")
def secrets_set(
    key: str = typer.Argument(..., help="Secret key  e.g. gmail.oauth_token"),
    value: str = typer.Argument(..., help="Secret value"),
) -> None:
    """Store a secret. Requires owner role."""
    require_role("owner")
    asyncio.run(_set(key, value))


async def _set(key: str, value: str) -> None:
    await _sm().set(key, value)
    console.print(f"[green]✓[/green] [bold]{key}[/bold] stored.")


@app.command("get")
def secrets_get(
    key: str = typer.Argument(..., help="Secret key"),
    show: bool = typer.Option(False, "--show", help="Reveal actual value (masked by default)"),
) -> None:
    """Retrieve a secret (masked by default). Requires owner role."""
    require_role("owner")
    asyncio.run(_get(key, show))


async def _get(key: str, show: bool) -> None:
    try:
        value = await _sm().get(key)
    except Exception:
        console.print(f"[red]Secret not found:[/red] {key}")
        console.print(f"  Hint: [cyan]vera secrets set {key} <value>[/cyan]")
        raise typer.Exit(1)

    if show:
        console.print(f"[bold]{key}[/bold] = {value}")
    else:
        masked = value[:4] + "****" if len(value) > 4 else "****"
        console.print(f"[bold]{key}[/bold] = {masked}  [dim](--show to reveal)[/dim]")


@app.command("list")
def secrets_list(
    prefix: Optional[str] = typer.Argument(None, help="Key prefix filter (e.g. gmail)"),
) -> None:
    """List secret keys. Values are never shown. Requires owner role."""
    require_role("owner")
    asyncio.run(_list(prefix or ""))


async def _list(prefix: str) -> None:
    keys = await _sm().list_keys(prefix)
    if not keys:
        note = f" with prefix '{prefix}'" if prefix else ""
        console.print(f"[yellow]No secrets found{note}.[/yellow]")
        console.print("[dim]Note: the keyring backend cannot enumerate keys.[/dim]")
        return
    table = Table(
        title=f"Secrets{' (prefix: ' + prefix + ')' if prefix else ''}",
        show_header=True,
    )
    table.add_column("Key", style="cyan")
    for k in sorted(keys):
        table.add_row(k)
    console.print(table)


@app.command("delete")
def secrets_delete(
    key: str = typer.Argument(..., help="Secret key to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a secret. Requires owner role."""
    require_role("owner")
    if not yes:
        typer.confirm(f"Delete secret '{key}'?", abort=True)
    asyncio.run(_delete(key))


async def _delete(key: str) -> None:
    await _sm().delete(key)
    console.print(f"[green]✓[/green] Secret [bold]{key}[/bold] deleted.")
